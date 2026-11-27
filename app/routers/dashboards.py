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
from app.models.later import Notice
from app.models.registration import Registration, RegistrationStatus
from app.models.users import Role, User

router = APIRouter(tags=["dashboards"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)


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

    nav_links = [
        {"label": "Dashboard", "url": "/management", "active": True},
        {"label": "Admin", "url": "/admin", "active": False},
        {"label": "Notices", "url": "#", "disabled": True, "tag": "Day 2"},
        {"label": "Exams", "url": "#", "disabled": True, "tag": "Day 3"},
    ]

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

    nav_links = [
        {"label": "Dashboard", "url": "/hod", "active": True},
        {
            "label": "Registrations",
            "url": "/hod/registrations",
            "active": False,
            "badge": pending_count if pending_count > 0 else None,
        },
        {"label": "Students", "url": "#", "disabled": True, "tag": "Day 2"},
        {"label": "Mentor groups", "url": "#", "disabled": True, "tag": "Day 2"},
        {"label": "Subjects", "url": "#", "disabled": True, "tag": "Day 2"},
        {"label": "Leave requests", "url": "#", "disabled": True, "tag": "Day 2"},
    ]

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

    nav_links = [
        {"label": "Dashboard", "url": "/mentor", "active": True},
        {"label": "Mark attendance", "url": "#", "disabled": True, "tag": "Day 2"},
        {"label": "Leave requests", "url": "#", "disabled": True, "tag": "Day 2"},
        {"label": "Marks", "url": "#", "disabled": True, "tag": "Day 3"},
    ]

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

    nav_links = [
        {"label": "Dashboard", "url": "/trainer", "active": True},
        {"label": "Enter marks", "url": "#", "disabled": True, "tag": "Day 3"},
        {"label": "Schedule", "url": "#", "disabled": True, "tag": "Day 3"},
    ]

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

    nav_links = [
        {"label": "Dashboard", "url": "/student", "active": True},
        {"label": "Change password", "url": "/change-password", "active": False},
        {"label": "Attendance", "url": "#", "disabled": True, "tag": "Day 2"},
        {"label": "Marks", "url": "#", "disabled": True, "tag": "Day 3"},
        {"label": "Hall ticket", "url": "#", "disabled": True, "tag": "Day 3"},
    ]

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
        },
    )
