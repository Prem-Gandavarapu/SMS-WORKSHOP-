from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_
from sqlmodel import Session, select

from app.database import get_session
from app.deps import require_role
from app.models.academics import (
    Batch,
    Department,
    MentorGroup,
    Section,
    Student,
    Subject,
    TeachingAssignment,
)
from app.models.later import Attendance, LeaveRequest, Notice
from app.models.registration import Registration, RegistrationStatus
from app.models.users import Role, User
from app.navigation import build_nav
from app.services.attendance import (
    approved_leave_dates,
    calculate_attendance_summary,
    calendar_days,
    period_details,
    subject_attendance,
)

router = APIRouter(tags=["dashboards"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def _student_attendance_data(session: Session, student: Student) -> dict:
    """Load all attendance inputs for one authenticated student."""
    section = session.get(Section, student.section_id)
    current_year = section.current_year if section else 1
    current_semester = section.current_semester if section else 1
    subjects = session.exec(
        select(Subject)
        .where(
            Subject.department_id == student.department_id,
            Subject.year == current_year,
            Subject.semester == current_semester,
        )
        .order_by(Subject.code)
    ).all()
    records = session.exec(
        select(Attendance)
        .where(Attendance.student_id == student.id)
        .order_by(Attendance.date, Attendance.period)
    ).all()
    leaves = session.exec(
        select(LeaveRequest).where(
            LeaveRequest.student_id == student.id,
            LeaveRequest.status == "approved",
        )
    ).all()
    leave_dates = approved_leave_dates(leaves)
    return {
        "section": section,
        "subjects": subjects,
        "records": records,
        "leaves": leaves,
        "leave_dates": leave_dates,
        "summary": calculate_attendance_summary(records, leave_dates),
    }


@router.get("/management")
def management_dashboard(
    request: Request,
    current_user: User = Depends(require_role(Role.MANAGEMENT)),
    session: Session = Depends(get_session),
):
    """College-wide KPIs, department bar chart, and department summary table."""
    total_students = session.exec(select(func.count(Student.id))).one()
    departments = session.exec(select(Department).order_by(Department.code)).all()
    pending_total = session.exec(
        select(func.count(Registration.id)).where(
            Registration.status == RegistrationStatus.PENDING
        )
    ).one()

    # Students per current academic year (1..4)
    year_rows = session.exec(
        select(Section.current_year, func.count(Student.id))
        .join(Student, Student.section_id == Section.id)
        .group_by(Section.current_year)
        .order_by(Section.current_year)
    ).all()
    year_counts = {yr: cnt for yr, cnt in year_rows}

    dept_rows = []
    chart_labels = []
    chart_values = []
    for dept in departments:
        hod = session.get(User, dept.hod_user_id) if dept.hod_user_id else None
        stu_cnt = session.exec(
            select(func.count(Student.id)).where(Student.department_id == dept.id)
        ).one()
        pend_cnt = session.exec(
            select(func.count(Registration.id)).where(
                Registration.department_id == dept.id,
                Registration.status == RegistrationStatus.PENDING,
            )
        ).one()
        dept_rows.append(
            {
                "code": dept.code,
                "name": dept.name,
                "hod_name": hod.full_name if hod else "Unassigned",
                "students": stu_cnt,
                "pending": pend_cnt,
            }
        )
        chart_labels.append(dept.code)
        chart_values.append(stu_cnt)

    nav_links = build_nav(Role.MANAGEMENT, "dashboard")

    return templates.TemplateResponse(
        request,
        "dashboards/management.html",
        {
            "current_user": current_user,
            "page_title": "Management Dashboard",
            "nav_links": nav_links,
            "total_students": total_students,
            "year_counts": year_counts,
            "dept_count": len(departments),
            "pending_total": pending_total,
            "dept_rows": dept_rows,
            "chart_labels": chart_labels,
            "chart_values": chart_values,
        },
    )


@router.get("/hod")
def hod_dashboard(
    request: Request,
    current_user: User = Depends(require_role(Role.HOD)),
    session: Session = Depends(get_session),
):
    """Department KPIs, sections with mentor names, and ungrouped-student warning."""
    if not current_user.department_id:
        raise HTTPException(status_code=403, detail="No department assigned.")
    dept = session.get(Department, current_user.department_id)
    if not dept:
        raise HTTPException(status_code=403, detail="Department not found.")

    total_students = session.exec(
        select(func.count(Student.id)).where(Student.department_id == dept.id)
    ).one()
    pending_count = session.exec(
        select(func.count(Registration.id)).where(
            Registration.department_id == dept.id,
            Registration.status == RegistrationStatus.PENDING,
        )
    ).one()

    sections = session.exec(
        select(Section, Batch)
        .join(Batch, Section.batch_id == Batch.id)
        .where(Batch.department_id == dept.id)
        .order_by(Batch.start_year.desc(), Section.name)
    ).all()

    section_rows = []
    total_groups = 0
    sections_missing_group = []

    for sec, batch in sections:
        stu_cnt = session.exec(
            select(func.count(Student.id)).where(Student.section_id == sec.id)
        ).one()
        ungrouped_cnt = session.exec(
            select(func.count(Student.id)).where(
                Student.section_id == sec.id,
                Student.mentor_group_id.is_(None),
            )
        ).one()
        groups = session.exec(
            select(MentorGroup).where(MentorGroup.section_id == sec.id)
        ).all()
        total_groups += len(groups)

        mentor_names = []
        for g in groups:
            m = session.get(User, g.mentor_user_id)
            if m:
                mentor_names.append(m.full_name)

        label = f"{dept.code}-{batch.start_year} Sec {sec.name}"
        if ungrouped_cnt > 0:
            sections_missing_group.append(f"{label} ({ungrouped_cnt} students)")

        section_rows.append(
            {
                "label": label,
                "year": sec.current_year,
                "semester": sec.current_semester,
                "students": stu_cnt,
                "mentors": ", ".join(mentor_names) if mentor_names else "No mentor assigned",
            }
        )

    nav_links = build_nav(Role.HOD, "dashboard", pending_count)

    return templates.TemplateResponse(
        request,
        "dashboards/hod.html",
        {
            "current_user": current_user,
            "page_title": f"{dept.code} HOD Dashboard",
            "nav_links": nav_links,
            "department": dept,
            "total_students": total_students,
            "section_count": len(sections),
            "group_count": total_groups,
            "pending_count": pending_count,
            "section_rows": section_rows,
            "sections_missing_group": sections_missing_group,
        },
    )


@router.get("/mentor")
def mentor_dashboard(
    request: Request,
    current_user: User = Depends(require_role(Role.MENTOR)),
    session: Session = Depends(get_session),
):
    """Mentor's assigned group, student roster, and Day 2 attendance button."""
    group = session.exec(
        select(MentorGroup).where(MentorGroup.mentor_user_id == current_user.id)
    ).first()

    section_label = "Unassigned"
    students: list[Student] = []
    if group:
        sec = session.get(Section, group.section_id)
        if sec:
            batch = session.get(Batch, sec.batch_id)
            dept = session.get(Department, batch.department_id) if batch else None
            if dept and batch:
                section_label = f"{dept.code} {batch.start_year} - Section {sec.name} (Year {sec.current_year})"
        students = session.exec(
            select(Student)
            .where(Student.mentor_group_id == group.id)
            .order_by(Student.roll_number)
        ).all()

    nav_links = build_nav(Role.MENTOR, "dashboard")

    return templates.TemplateResponse(
        request,
        "dashboards/mentor.html",
        {
            "current_user": current_user,
            "page_title": "Mentor Dashboard",
            "nav_links": nav_links,
            "group": group,
            "section_label": section_label,
            "students": students,
        },
    )


@router.get("/trainer")
def trainer_dashboard(
    request: Request,
    current_user: User = Depends(require_role(Role.TRAINER)),
    session: Session = Depends(get_session),
):
    """External trainer's teaching assignments and Day 3 marks entry button."""
    assignments = session.exec(
        select(TeachingAssignment).where(
            TeachingAssignment.teacher_user_id == current_user.id
        )
    ).all()

    rows = []
    for ta in assignments:
        subj = session.get(Subject, ta.subject_id)
        sec = session.get(Section, ta.section_id)
        batch = session.get(Batch, sec.batch_id) if sec else None
        dept = session.get(Department, batch.department_id) if batch else None
        stu_cnt = (
            session.exec(
                select(func.count(Student.id)).where(Student.section_id == sec.id)
            ).one()
            if sec
            else 0
        )
        rows.append(
            {
                "subject_code": subj.code if subj else "-",
                "subject_name": subj.name if subj else "-",
                "section_label": (
                    f"{dept.code} {batch.start_year} - Sec {sec.name} (Yr {sec.current_year})"
                    if dept and batch and sec
                    else "-"
                ),
                "student_count": stu_cnt,
            }
        )

    nav_links = build_nav(Role.TRAINER, "dashboard")

    return templates.TemplateResponse(
        request,
        "dashboards/trainer.html",
        {
            "current_user": current_user,
            "page_title": "Trainer Dashboard",
            "nav_links": nav_links,
            "assignments": rows,
        },
    )


@router.get("/student")
def student_dashboard(
    request: Request,
    current_user: User = Depends(require_role(Role.STUDENT)),
    session: Session = Depends(get_session),
):
    """Student's personal KPIs, details, mentor info, and latest notice."""
    student = session.exec(
        select(Student).where(Student.user_id == current_user.id)
    ).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student profile not found.")

    batch = session.get(Batch, student.batch_id)
    mentor_user = (
        session.get(User, student.mentor_group.mentor_user_id)
        if student.mentor_group
        else None
    )
    latest_notice = session.exec(
        select(Notice)
        .where(
            or_(
                Notice.audience == "all",
                (Notice.audience == "department")
                & (Notice.department_id == student.department_id),
                (Notice.audience == "section")
                & (Notice.section_id == student.section_id),
                (Notice.audience == "role") & (Notice.role == Role.STUDENT.value),
            )
        )
        .order_by(Notice.created_at.desc())
    ).first()

    first_name = student.full_name.split()[0] if student.full_name else "Student"
    attendance_data = _student_attendance_data(session, student)

    nav_links = build_nav(Role.STUDENT, "dashboard")

    return templates.TemplateResponse(
        request,
        "dashboards/student.html",
        {
            "current_user": current_user,
            "page_title": f"Welcome, {first_name}",
            "nav_links": nav_links,
            "student": student,
            "batch": batch,
            "mentor_user": mentor_user,
            "latest_notice": latest_notice,
            "attendance_summary": attendance_data["summary"],
        },
    )


@router.get("/student/attendance")
def student_attendance(
    request: Request,
    selected_date: str | None = None,
    current_user: User = Depends(require_role(Role.STUDENT)),
    session: Session = Depends(get_session),
):
    """Show the authenticated student's overall, subject, and daily attendance."""
    student = session.exec(
        select(Student).where(Student.user_id == current_user.id)
    ).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student profile not found.")

    attendance_data = _student_attendance_data(session, student)
    today = date.today()
    parsed_date = None
    if selected_date:
        try:
            parsed_date = date.fromisoformat(selected_date)
        except ValueError:
            parsed_date = None
    if not parsed_date or (parsed_date.year, parsed_date.month) != (today.year, today.month):
        month_dates = [
            record.date
            for record in attendance_data["records"]
            if (record.date.year, record.date.month) == (today.year, today.month)
        ]
        parsed_date = max(month_dates) if month_dates else today

    nav_links = build_nav(Role.STUDENT, "attendance")
    return templates.TemplateResponse(
        request,
        "dashboards/student_attendance.html",
        {
            "current_user": current_user,
            "page_title": "My Attendance",
            "nav_links": nav_links,
            "student": student,
            "attendance_summary": attendance_data["summary"],
            "subject_rows": subject_attendance(
                attendance_data["records"],
                attendance_data["subjects"],
                attendance_data["leave_dates"],
            ),
            "calendar_days": calendar_days(
                today.year,
                today.month,
                attendance_data["records"],
                attendance_data["leave_dates"],
            ),
            "selected_date": parsed_date,
            "selected_periods": period_details(
                parsed_date,
                attendance_data["records"],
                attendance_data["subjects"],
                attendance_data["leave_dates"],
            ),
            "month_label": today.strftime("%B %Y"),
        },
    )
