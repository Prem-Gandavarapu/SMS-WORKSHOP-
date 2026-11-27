from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.database import get_session
from app.deps import require_role
from app.models.academics import Batch, Department, MentorGroup, Section
from app.models.users import Role, User
from app.navigation import build_nav
from app.services.attendance import ATTENDANCE_PERIODS
from app.services.mark_attendance import (
    EDIT_WINDOW_DAYS,
    default_attendance_date,
    existing_statuses,
    group_students,
    marked_periods,
    period_options,
    save_period_attendance,
    section_subjects,
    students_on_leave,
    validate_attendance_date,
)

router = APIRouter(prefix="/mentor", tags=["mentor"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def _parse_date(value: Optional[str]) -> Optional[date]:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _parse_period(value: Optional[str]) -> Optional[int]:
    return int(value) if value and value.isdigit() and int(value) in ATTENDANCE_PERIODS else None


def _render(
    request: Request,
    session: Session,
    mentor: User,
    selected: date,
    period: Optional[int],
    error: Optional[str] = None,
    saved: Optional[str] = None,
    submitted: Optional[dict[int, str]] = None,
    status_code: int = 200,
):
    """Build the mark-attendance page for the mentor's group."""
    today = date.today()
    group = session.exec(
        select(MentorGroup).where(MentorGroup.mentor_user_id == mentor.id)
    ).first()

    context = {
        "current_user": mentor,
        "page_title": "Mark Attendance",
        "nav_links": build_nav(Role.MENTOR, "attendance"),
        "group": group,
        "today": today,
        "min_date": today - timedelta(days=EDIT_WINDOW_DAYS),
        "selected_date": selected,
        "error": error,
        "saved": saved,
        "edit_window_days": EDIT_WINDOW_DAYS,
    }
    if not group:
        return templates.TemplateResponse(
            request, "mentor/attendance.html", context, status_code=status_code
        )

    section = session.get(Section, group.section_id)
    batch = session.get(Batch, section.batch_id) if section else None
    dept = session.get(Department, batch.department_id) if batch else None
    section_label = (
        f"{dept.code} {batch.start_year} - Section {section.name} (Year {section.current_year})"
        if section and batch and dept
        else "Unassigned"
    )

    students = group_students(session, group)
    student_ids = [s.id for s in students]
    subjects = section_subjects(session, section, dept.id if dept else mentor.department_id)
    done_periods = marked_periods(session, student_ids, selected)
    if period is None:
        # Default to the first period of the day that has not been marked yet
        period = next((p for p in ATTENDANCE_PERIODS if p not in done_periods), 1)

    saved_rows = existing_statuses(session, student_ids, selected, period)
    on_leave = students_on_leave(session, student_ids, selected)
    date_error = validate_attendance_date(selected, today)

    rows = []
    for student in students:
        saved_row = saved_rows.get(student.id)
        if submitted and student.id in submitted:
            status = submitted[student.id]
        elif saved_row:
            status = saved_row.status
        else:
            status = "absent" if student.id in on_leave else "present"
        rows.append({"student": student, "status": status, "on_leave": student.id in on_leave})

    context.update(
        {
            "section_label": section_label,
            "period": period,
            "periods": period_options(subjects),
            "marked_periods": done_periods,
            "already_marked": bool(saved_rows),
            "rows": rows,
            "can_mark": date_error is None and bool(students),
            "date_error": date_error,
        }
    )
    return templates.TemplateResponse(
        request, "mentor/attendance.html", context, status_code=status_code
    )


@router.get("/attendance")
def mark_attendance_page(
    request: Request,
    period: Optional[str] = None,
    saved: Optional[str] = None,
    current_user: User = Depends(require_role(Role.MENTOR)),
    session: Session = Depends(get_session),
):
    """Show the roster for one date and period with Present / Absent / Late choices."""
    selected = _parse_date(request.query_params.get("date")) or default_attendance_date(date.today())
    return _render(
        request,
        session,
        current_user,
        selected,
        _parse_period(period),
        saved=saved if saved in ("created", "updated") else None,
    )


@router.post("/attendance")
async def mark_attendance_submit(
    request: Request,
    current_user: User = Depends(require_role(Role.MENTOR)),
    session: Session = Depends(get_session),
):
    """Save one period's attendance for the whole mentor group."""
    form = await request.form()
    selected = _parse_date(str(form.get("date", "")))
    period = _parse_period(str(form.get("period", "")))
    today = date.today()

    submitted: dict[int, str] = {}
    for key, value in form.items():
        if key.startswith("status_") and key[7:].isdigit():
            submitted[int(key[7:])] = str(value)

    if selected is None or period is None:
        return _render(
            request, session, current_user, default_attendance_date(today), None,
            error="Please choose a valid date and period.", status_code=400,
        )

    date_error = validate_attendance_date(selected, today)
    if date_error:
        return _render(
            request, session, current_user, selected, period,
            error=date_error, submitted=submitted, status_code=400,
        )

    group = session.exec(
        select(MentorGroup).where(MentorGroup.mentor_user_id == current_user.id)
    ).first()
    if not group:
        return _render(
            request, session, current_user, selected, period,
            error="You do not have a mentor group assigned.", status_code=400,
        )

    students = group_students(session, group)
    # Ignore any student ids that are not in this mentor's group
    allowed = {s.id for s in students}
    statuses = {sid: status for sid, status in submitted.items() if sid in allowed}

    try:
        result = save_period_attendance(
            session, students, selected, period, statuses, current_user.id
        )
    except ValueError as exc:
        return _render(
            request, session, current_user, selected, period,
            error=str(exc), submitted=submitted, status_code=400,
        )

    outcome = "updated" if result["updated"] and not result["created"] else "created"
    return RedirectResponse(
        url=f"/mentor/attendance?date={selected.isoformat()}&period={period}&saved={outcome}",
        status_code=303,
    )
