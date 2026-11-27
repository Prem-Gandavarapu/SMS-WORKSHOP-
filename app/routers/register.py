from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlmodel import Session, select

from app.config import settings
from app.database import get_session
from app.models.academics import Department, Student
from app.models.registration import Registration, RegistrationStatus

router = APIRouter()

APP_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = APP_DIR / "templates"
UPLOAD_BASE = (
    Path(settings.UPLOAD_DIR) if settings.UPLOAD_DIR else APP_DIR / "static" / "uploads"
) / "registrations"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf"}
MAX_FILE_BYTES = 2 * 1024 * 1024  # 2 MB
VALID_QUOTAS = {"convener", "management", "spot"}


def _calculate_age(dob: date, today: date) -> int:
    """Return full years of age on today's date."""
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


async def _validate_upload(upload: UploadFile, label: str) -> tuple[bytes, str]:
    """Read and validate an uploaded document's extension and 2 MB size limit."""
    filename = (upload.filename or "").strip()
    ext = Path(filename).suffix.lower()
    if not filename or ext not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"{label} must be a .jpg, .jpeg, .png, or .pdf file."
        )

    data = await upload.read()
    if len(data) == 0:
        raise ValueError(f"{label} file cannot be empty.")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError(f"{label} exceeds the 2 MB size limit.")

    return data, ext


def _validate_registration_fields(
    full_name: str,
    dob_str: str,
    gender: str,
    phone: str,
    email: str,
    parent_name: str,
    department_id: int,
    quota: str,
    entrance_rank_str: str,
    tenth_percent_str: str,
    inter_percent_str: str,
    session: Session,
) -> dict:
    """Validate text/numeric registration fields and return parsed values."""
    clean_name = full_name.strip()
    clean_gender = gender.strip()
    clean_phone = phone.strip()
    clean_email = email.strip()
    clean_parent = parent_name.strip()
    clean_quota = quota.strip().lower()

    if not all([clean_name, dob_str, clean_gender, clean_phone, clean_email, clean_parent]):
        raise ValueError("All personal details fields are required.")

    if not (clean_phone.isdigit() and len(clean_phone) == 10):
        raise ValueError("Phone number must be exactly 10 digits.")

    try:
        dob_val = date.fromisoformat(dob_str)
    except ValueError:
        raise ValueError("Please enter a valid date of birth.")

    if _calculate_age(dob_val, date.today()) < 16:
        raise ValueError("Applicant must be at least 16 years old.")

    department = session.get(Department, department_id)
    if not department:
        raise ValueError("Please select a valid branch.")

    if clean_quota not in VALID_QUOTAS:
        raise ValueError("Please select a valid admission quota.")

    entrance_rank: Optional[int] = None
    if entrance_rank_str.strip():
        try:
            entrance_rank = int(entrance_rank_str.strip())
            if entrance_rank <= 0:
                raise ValueError
        except ValueError:
            raise ValueError("Entrance rank must be a positive whole number.")

    try:
        tenth_val = float(tenth_percent_str)
        inter_val = float(inter_percent_str)
    except ValueError:
        raise ValueError("10th and Inter percentages must be valid numbers.")

    if not (0.0 <= tenth_val <= 100.0) or not (0.0 <= inter_val <= 100.0):
        raise ValueError("10th and Inter percentages must be between 0 and 100.")

    return {
        "full_name": clean_name,
        "dob": dob_val,
        "gender": clean_gender,
        "phone": clean_phone,
        "email": clean_email,
        "parent_name": clean_parent,
        "department_id": department_id,
        "quota": clean_quota,
        "entrance_rank": entrance_rank,
        "tenth_percent": tenth_val,
        "inter_percent": inter_val,
    }


@router.get("/register")
def register_page(request: Request, session: Session = Depends(get_session)):
    """Show the 4-step public first-year registration form."""
    departments = session.exec(select(Department).order_by(Department.code)).all()
    return templates.TemplateResponse(
        request,
        "register/form.html",
        {"departments": departments, "error": None, "form": {}},
    )


@router.post("/register")
async def register_submit(
    request: Request,
    full_name: str = Form(""),
    dob: str = Form(""),
    gender: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    parent_name: str = Form(""),
    department_id: int = Form(0),
    quota: str = Form(""),
    entrance_rank: str = Form(""),
    tenth_percent: str = Form(""),
    inter_percent: str = Form(""),
    photo: UploadFile = File(...),
    marks_memo: UploadFile = File(...),
    id_proof: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    """Validate form inputs and uploads, save registration, and redirect."""
    departments = session.exec(select(Department).order_by(Department.code)).all()
    form_data = {
        "full_name": full_name,
        "dob": dob,
        "gender": gender,
        "phone": phone,
        "email": email,
        "parent_name": parent_name,
        "department_id": department_id,
        "quota": quota,
        "entrance_rank": entrance_rank,
        "tenth_percent": tenth_percent,
        "inter_percent": inter_percent,
    }

    try:
        parsed = _validate_registration_fields(
            full_name=full_name,
            dob_str=dob,
            gender=gender,
            phone=phone,
            email=email,
            parent_name=parent_name,
            department_id=department_id,
            quota=quota,
            entrance_rank_str=entrance_rank,
            tenth_percent_str=tenth_percent,
            inter_percent_str=inter_percent,
            session=session,
        )
        photo_bytes, photo_ext = await _validate_upload(photo, "Photo")
        memo_bytes, memo_ext = await _validate_upload(marks_memo, "Marks Memo")
        id_bytes, id_ext = await _validate_upload(id_proof, "ID Proof")
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "register/form.html",
            {"departments": departments, "error": str(exc), "form": form_data},
            status_code=400,
        )

    # Generate reference_no based on the highest existing Registration id
    max_id = session.exec(select(func.max(Registration.id))).one() or 0
    next_serial = max_id + 1
    reference_no = f"REG-{settings.ADMISSION_YEAR}-{next_serial:05d}"

    # Save uploaded files under app/static/uploads/registrations/<reference_no>/
    dest_dir = UPLOAD_BASE / reference_no
    dest_dir.mkdir(parents=True, exist_ok=True)

    (dest_dir / f"photo{photo_ext}").write_bytes(photo_bytes)
    (dest_dir / f"marks_memo{memo_ext}").write_bytes(memo_bytes)
    (dest_dir / f"id_proof{id_ext}").write_bytes(id_bytes)

    web_prefix = f"/static/uploads/registrations/{reference_no}"
    registration = Registration(
        reference_no=reference_no,
        **parsed,
        photo_path=f"{web_prefix}/photo{photo_ext}",
        marks_memo_path=f"{web_prefix}/marks_memo{memo_ext}",
        id_proof_path=f"{web_prefix}/id_proof{id_ext}",
        status=RegistrationStatus.PENDING,
    )
    session.add(registration)
    session.commit()

    return RedirectResponse(url=f"/register/done/{reference_no}", status_code=303)


@router.get("/register/done/{reference_no}")
def register_done(
    request: Request,
    reference_no: str,
    session: Session = Depends(get_session),
):
    """Display confirmation with the generated reference number."""
    reg = session.exec(
        select(Registration).where(Registration.reference_no == reference_no)
    ).first()
    if not reg:
        raise HTTPException(status_code=404, detail="Registration not found.")

    return templates.TemplateResponse(
        request,
        "register/done.html",
        {"registration": reg},
    )


@router.get("/register/status")
def register_status(
    request: Request,
    ref: Optional[str] = None,
    session: Session = Depends(get_session),
):
    """Track application status by reference number."""
    clean_ref = (ref or "").strip().upper()
    reg = None
    department = None
    student = None
    not_found = False

    if clean_ref:
        reg = session.exec(
            select(Registration).where(Registration.reference_no == clean_ref)
        ).first()
        if not reg:
            not_found = True
        else:
            department = session.get(Department, reg.department_id)
            if reg.student_id:
                student = session.get(Student, reg.student_id)

    return templates.TemplateResponse(
        request,
        "register/status.html",
        {
            "ref": clean_ref,
            "registration": reg,
            "department": department,
            "student": student,
            "not_found": not_found,
        },
    )


@router.get("/register/edit/{reference_no}")
def register_edit_page(
    request: Request,
    reference_no: str,
    session: Session = Depends(get_session),
):
    """Allow applicant to edit and resubmit when status is correction."""
    reg = session.exec(
        select(Registration).where(Registration.reference_no == reference_no)
    ).first()
    if not reg:
        raise HTTPException(status_code=404, detail="Registration not found.")

    if reg.status != RegistrationStatus.CORRECTION:
        return RedirectResponse(
            url=f"/register/status?ref={reference_no}", status_code=303
        )

    departments = session.exec(select(Department).order_by(Department.code)).all()
    return templates.TemplateResponse(
        request,
        "register/edit.html",
        {"registration": reg, "departments": departments, "error": None},
    )


@router.post("/register/edit/{reference_no}")
async def register_edit_submit(
    request: Request,
    reference_no: str,
    full_name: str = Form(""),
    dob: str = Form(""),
    gender: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    parent_name: str = Form(""),
    department_id: int = Form(0),
    quota: str = Form(""),
    entrance_rank: str = Form(""),
    tenth_percent: str = Form(""),
    inter_percent: str = Form(""),
    photo: Optional[UploadFile] = File(None),
    marks_memo: Optional[UploadFile] = File(None),
    id_proof: Optional[UploadFile] = File(None),
    session: Session = Depends(get_session),
):
    """Validate corrected details, optionally replace files, and set status back to pending."""
    reg = session.exec(
        select(Registration).where(Registration.reference_no == reference_no)
    ).first()
    if not reg:
        raise HTTPException(status_code=404, detail="Registration not found.")

    if reg.status != RegistrationStatus.CORRECTION:
        return RedirectResponse(
            url=f"/register/status?ref={reference_no}", status_code=303
        )

    departments = session.exec(select(Department).order_by(Department.code)).all()

    try:
        parsed = _validate_registration_fields(
            full_name=full_name,
            dob_str=dob,
            gender=gender,
            phone=phone,
            email=email,
            parent_name=parent_name,
            department_id=department_id,
            quota=quota,
            entrance_rank_str=entrance_rank,
            tenth_percent_str=tenth_percent,
            inter_percent_str=inter_percent,
            session=session,
        )

        dest_dir = UPLOAD_BASE / reference_no
        dest_dir.mkdir(parents=True, exist_ok=True)
        web_prefix = f"/static/uploads/registrations/{reference_no}"

        if photo and photo.filename:
            data, ext = await _validate_upload(photo, "Photo")
            (dest_dir / f"photo{ext}").write_bytes(data)
            reg.photo_path = f"{web_prefix}/photo{ext}"

        if marks_memo and marks_memo.filename:
            data, ext = await _validate_upload(marks_memo, "Marks Memo")
            (dest_dir / f"marks_memo{ext}").write_bytes(data)
            reg.marks_memo_path = f"{web_prefix}/marks_memo{ext}"

        if id_proof and id_proof.filename:
            data, ext = await _validate_upload(id_proof, "ID Proof")
            (dest_dir / f"id_proof{ext}").write_bytes(data)
            reg.id_proof_path = f"{web_prefix}/id_proof{ext}"
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "register/edit.html",
            {"registration": reg, "departments": departments, "error": str(exc)},
            status_code=400,
        )

    for key, value in parsed.items():
        setattr(reg, key, value)

    reg.status = RegistrationStatus.PENDING
    reg.decided_at = None
    reg.decided_by_user_id = None
    session.add(reg)
    session.commit()

    return RedirectResponse(
        url=f"/register/status?ref={reference_no}", status_code=303
    )
