from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlmodel import Session, select

from app.database import get_session
from app.deps import require_role
from app.models.academics import Department
from app.models.registration import Registration, RegistrationStatus
from app.models.users import Role, User
from app.services.approval import approve_registration

router = APIRouter(prefix="/hod", tags=["hod"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def _hod_nav_links(active_key: str, pending_count: int) -> list[dict]:
    """Build the sidebar menu for HOD pages."""
    return [
        {"label": "Dashboard", "url": "/hod", "active": active_key == "dashboard"},
        {
            "label": "Registrations",
            "url": "/hod/registrations",
            "active": active_key == "registrations",
            "badge": pending_count if pending_count > 0 else None,
        },
        {"label": "Students", "url": "#", "disabled": True, "tag": "Day 2"},
        {"label": "Mentor groups", "url": "#", "disabled": True, "tag": "Day 2"},
        {"label": "Subjects", "url": "#", "disabled": True, "tag": "Day 2"},
        {"label": "Leave requests", "url": "#", "disabled": True, "tag": "Day 2"},
    ]


def _get_hod_department(session: Session, hod_user: User) -> Department:
    """Return the HOD's own department or raise 403 if unassigned."""
    if not hod_user.department_id:
        raise HTTPException(status_code=403, detail="No department assigned to this HOD account.")
    dept = session.get(Department, hod_user.department_id)
    if not dept:
        raise HTTPException(status_code=403, detail="Assigned department not found.")
    return dept


def _get_hod_registration(
    session: Session, reg_id: int, hod_user: User
) -> Registration:
    """Load a registration only if it belongs to the HOD's department."""
    reg = session.get(Registration, reg_id)
    if not reg:
        raise HTTPException(status_code=404, detail="Registration not found.")
    if reg.department_id != hod_user.department_id:
        raise HTTPException(
            status_code=403,
            detail="You can only view registrations for your own department.",
        )
    return reg


def _count_by_status(session: Session, department_id: int) -> dict:
    """Return counts of registrations by status for a department."""
    counts = {s.value: 0 for s in RegistrationStatus}
    rows = session.exec(
        select(Registration.status, func.count(Registration.id))
        .where(Registration.department_id == department_id)
        .group_by(Registration.status)
    ).all()
    for status_val, cnt in rows:
        counts[status_val.value] = cnt
    return counts


@router.get("/registrations")
def list_registrations(
    request: Request,
    status: str = "all",
    current_user: User = Depends(require_role(Role.HOD)),
    session: Session = Depends(get_session),
):
    """Show KPI cards and filterable registration list for the HOD's department."""
    dept = _get_hod_department(session, current_user)
    counts = _count_by_status(session, dept.id)

    stmt = select(Registration).where(Registration.department_id == dept.id)
    valid_statuses = {s.value: s for s in RegistrationStatus}
    if status in valid_statuses:
        stmt = stmt.where(Registration.status == valid_statuses[status])

    registrations = session.exec(
        stmt.order_by(Registration.submitted_at.desc())
    ).all()

    return templates.TemplateResponse(
        request,
        "hod/registrations.html",
        {
            "current_user": current_user,
            "page_title": f"{dept.code} Registrations",
            "nav_links": _hod_nav_links("registrations", counts["pending"]),
            "department": dept,
            "counts": counts,
            "active_status": status,
            "registrations": registrations,
        },
    )


@router.get("/registrations/{reg_id}")
def registration_detail(
    request: Request,
    reg_id: int,
    current_user: User = Depends(require_role(Role.HOD)),
    session: Session = Depends(get_session),
):
    """Show full application details, photo, and document links for HOD review."""
    dept = _get_hod_department(session, current_user)
    reg = _get_hod_registration(session, reg_id, current_user)
    counts = _count_by_status(session, dept.id)

    return templates.TemplateResponse(
        request,
        "hod/registration_detail.html",
        {
            "current_user": current_user,
            "page_title": f"Application {reg.reference_no}",
            "nav_links": _hod_nav_links("registrations", counts["pending"]),
            "department": dept,
            "reg": reg,
            "error": None,
        },
    )


@router.post("/registrations/{reg_id}/approve")
def approve_registration_route(
    request: Request,
    reg_id: int,
    current_user: User = Depends(require_role(Role.HOD)),
    session: Session = Depends(get_session),
):
    """Approve a pending registration and show the generated roll number & credentials."""
    dept = _get_hod_department(session, current_user)
    reg = _get_hod_registration(session, reg_id, current_user)
    counts = _count_by_status(session, dept.id)

    if reg.status != RegistrationStatus.PENDING:
        return templates.TemplateResponse(
            request,
            "hod/registration_detail.html",
            {
                "current_user": current_user,
                "page_title": f"Application {reg.reference_no}",
                "nav_links": _hod_nav_links("registrations", counts["pending"]),
                "department": dept,
                "reg": reg,
                "error": f"Cannot approve: application is already '{reg.status.value}'.",
            },
            status_code=400,
        )

    result = approve_registration(session, reg, current_user)
    new_counts = _count_by_status(session, dept.id)

    return templates.TemplateResponse(
        request,
        "hod/approval_result.html",
        {
            "current_user": current_user,
            "page_title": "Student Approved",
            "nav_links": _hod_nav_links("registrations", new_counts["pending"]),
            **result,
        },
    )


@router.post("/registrations/{reg_id}/reject")
def reject_registration_route(
    request: Request,
    reg_id: int,
    remarks: str = Form(""),
    current_user: User = Depends(require_role(Role.HOD)),
    session: Session = Depends(get_session),
):
    """Reject a pending registration (remarks required)."""
    dept = _get_hod_department(session, current_user)
    reg = _get_hod_registration(session, reg_id, current_user)
    counts = _count_by_status(session, dept.id)

    if reg.status != RegistrationStatus.PENDING:
        return templates.TemplateResponse(
            request,
            "hod/registration_detail.html",
            {
                "current_user": current_user,
                "page_title": f"Application {reg.reference_no}",
                "nav_links": _hod_nav_links("registrations", counts["pending"]),
                "department": dept,
                "reg": reg,
                "error": f"Cannot reject: application is already '{reg.status.value}'.",
            },
            status_code=400,
        )

    clean_remarks = remarks.strip()
    if not clean_remarks:
        return templates.TemplateResponse(
            request,
            "hod/registration_detail.html",
            {
                "current_user": current_user,
                "page_title": f"Application {reg.reference_no}",
                "nav_links": _hod_nav_links("registrations", counts["pending"]),
                "department": dept,
                "reg": reg,
                "error": "Remarks are required when rejecting an application.",
            },
            status_code=400,
        )

    reg.status = RegistrationStatus.REJECTED
    reg.hod_remarks = clean_remarks
    reg.decided_at = datetime.now(timezone.utc)
    reg.decided_by_user_id = current_user.id
    session.add(reg)
    session.commit()

    return RedirectResponse(url=f"/hod/registrations/{reg_id}", status_code=303)


@router.post("/registrations/{reg_id}/correction")
def correction_registration_route(
    request: Request,
    reg_id: int,
    remarks: str = Form(""),
    current_user: User = Depends(require_role(Role.HOD)),
    session: Session = Depends(get_session),
):
    """Send a pending registration back for correction (remarks required)."""
    dept = _get_hod_department(session, current_user)
    reg = _get_hod_registration(session, reg_id, current_user)
    counts = _count_by_status(session, dept.id)

    if reg.status != RegistrationStatus.PENDING:
        return templates.TemplateResponse(
            request,
            "hod/registration_detail.html",
            {
                "current_user": current_user,
                "page_title": f"Application {reg.reference_no}",
                "nav_links": _hod_nav_links("registrations", counts["pending"]),
                "department": dept,
                "reg": reg,
                "error": f"Cannot send back: application is already '{reg.status.value}'.",
            },
            status_code=400,
        )

    clean_remarks = remarks.strip()
    if not clean_remarks:
        return templates.TemplateResponse(
            request,
            "hod/registration_detail.html",
            {
                "current_user": current_user,
                "page_title": f"Application {reg.reference_no}",
                "nav_links": _hod_nav_links("registrations", counts["pending"]),
                "department": dept,
                "reg": reg,
                "error": "Remarks are required when sending an application back for correction.",
            },
            status_code=400,
        )

    reg.status = RegistrationStatus.CORRECTION
    reg.hod_remarks = clean_remarks
    reg.decided_at = datetime.now(timezone.utc)
    reg.decided_by_user_id = current_user.id
    session.add(reg)
    session.commit()

    return RedirectResponse(url=f"/hod/registrations/{reg_id}", status_code=303)
