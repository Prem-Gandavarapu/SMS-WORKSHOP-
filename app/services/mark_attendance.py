"""Mentor attendance marking: one period for one date across a mentor group."""

from datetime import date, timedelta
from typing import Optional

from sqlmodel import Session, select

from app.models.academics import MentorGroup, Section, Student, Subject
from app.models.later import Attendance, LeaveRequest
from app.services.attendance import ATTENDANCE_PERIODS

VALID_STATUSES = ("present", "absent", "late")
# How many days back a mentor may mark or correct attendance
EDIT_WINDOW_DAYS = 7


def default_attendance_date(today: date) -> date:
    """Today, or the previous Saturday when today is a Sunday."""
    return today - timedelta(days=1) if today.weekday() == 6 else today


def validate_attendance_date(selected: date, today: date) -> Optional[str]:
    """Return an error message when attendance cannot be marked for this date."""
    if selected > today:
        return "Attendance cannot be marked for a future date."
    if selected.weekday() == 6:
        return "Sunday is a holiday. Please choose a working day."
    if selected < today - timedelta(days=EDIT_WINDOW_DAYS):
        return f"Attendance can only be marked or corrected for the last {EDIT_WINDOW_DAYS} days."
    return None


def section_subjects(session: Session, section: Optional[Section], department_id: int) -> list[Subject]:
    """Subjects for the section's current semester, ordered so period N maps to subject N."""
    if not section:
        return []
    return list(
        session.exec(
            select(Subject)
            .where(
                Subject.department_id == department_id,
                Subject.year == section.current_year,
                Subject.semester == section.current_semester,
            )
            .order_by(Subject.code)
        ).all()
    )


def period_options(subjects: list[Subject]) -> list[dict]:
    """Label each period with the subject taught in it."""
    options = []
    for period in ATTENDANCE_PERIODS:
        subject = subjects[period - 1] if period <= len(subjects) else None
        label = f"Period {period}"
        if subject:
            label += f" · {subject.code} {subject.name}"
        options.append({"period": period, "label": label, "subject": subject})
    return options


def group_students(session: Session, group: MentorGroup) -> list[Student]:
    """Students in a mentor group, by roll number."""
    return list(
        session.exec(
            select(Student)
            .where(Student.mentor_group_id == group.id)
            .order_by(Student.roll_number)
        ).all()
    )


def existing_statuses(
    session: Session, student_ids: list[int], selected: date, period: int
) -> dict[int, Attendance]:
    """Saved attendance rows for these students in one period, keyed by student id."""
    if not student_ids:
        return {}
    rows = session.exec(
        select(Attendance).where(
            Attendance.student_id.in_(student_ids),
            Attendance.date == selected,
            Attendance.period == period,
        )
    ).all()
    return {row.student_id: row for row in rows}


def marked_periods(session: Session, student_ids: list[int], selected: date) -> set[int]:
    """Periods on a date that already have attendance for this group."""
    if not student_ids:
        return set()
    rows = session.exec(
        select(Attendance.period)
        .where(Attendance.student_id.in_(student_ids), Attendance.date == selected)
        .distinct()
    ).all()
    return set(rows)


def students_on_leave(session: Session, student_ids: list[int], selected: date) -> set[int]:
    """Students with approved leave covering the date."""
    if not student_ids:
        return set()
    rows = session.exec(
        select(LeaveRequest.student_id).where(
            LeaveRequest.student_id.in_(student_ids),
            LeaveRequest.status == "approved",
            LeaveRequest.from_date <= selected,
            LeaveRequest.to_date >= selected,
        )
    ).all()
    return set(rows)


def save_period_attendance(
    session: Session,
    students: list[Student],
    selected: date,
    period: int,
    statuses: dict[int, str],
    marked_by_user_id: int,
) -> dict[str, int]:
    """Create or update one period's attendance for every student in the group.

    Every student must have a valid status, so a period is never saved half-marked.
    Returns counts of created and updated rows.
    """
    if period not in ATTENDANCE_PERIODS:
        raise ValueError("Please choose a valid period.")

    missing = [s.roll_number for s in students if s.id not in statuses]
    if missing:
        raise ValueError(
            "Please mark every student. Missing: " + ", ".join(missing[:5])
            + ("…" if len(missing) > 5 else "")
        )
    invalid = {value for value in statuses.values() if value not in VALID_STATUSES}
    if invalid:
        raise ValueError("Attendance status must be present, absent or late.")

    existing = existing_statuses(session, [s.id for s in students], selected, period)
    created = updated = 0
    for student in students:
        status = statuses[student.id]
        row = existing.get(student.id)
        if row:
            if row.status != status or row.marked_by_user_id != marked_by_user_id:
                row.status = status
                row.marked_by_user_id = marked_by_user_id
                session.add(row)
            updated += 1
        else:
            session.add(
                Attendance(
                    student_id=student.id,
                    section_id=student.section_id,
                    date=selected,
                    period=period,
                    status=status,
                    marked_by_user_id=marked_by_user_id,
                )
            )
            created += 1
    session.commit()
    return {"created": created, "updated": updated}
