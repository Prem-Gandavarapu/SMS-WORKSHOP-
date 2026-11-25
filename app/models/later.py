from datetime import date as DateType, datetime, timezone
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class Attendance(SQLModel, table=True):
    """Period-wise attendance record for a student (Day 2)."""

    __table_args__ = (
        UniqueConstraint(
            "student_id", "date", "period", name="uq_attendance_student_date_period"
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    student_id: int = Field(foreign_key="student.id", index=True)
    section_id: int = Field(foreign_key="section.id", index=True)
    date: DateType = Field(index=True)
    # Period number from 1 to 7
    period: int
    # present, absent, or late
    status: str
    marked_by_user_id: int = Field(foreign_key="user.id")


class Mark(SQLModel, table=True):
    """Exam marks for a student in a subject (Day 2/3)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    student_id: int = Field(foreign_key="student.id", index=True)
    subject_id: int = Field(foreign_key="subject.id", index=True)
    # mid1, mid2, internal, or semester
    exam_type: str
    max_marks: float
    marks_obtained: float
    entered_by_user_id: int = Field(foreign_key="user.id")


class Exam(SQLModel, table=True):
    """Examination event for a department, year, and semester (Day 3)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    department_id: int = Field(foreign_key="department.id", index=True)
    year: int
    semester: int
    start_date: DateType
    end_date: DateType
    is_published: bool = Field(default=False)


class ExamSchedule(SQLModel, table=True):
    """Timetable entry for an exam subject, session, and room (Day 3)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    exam_id: int = Field(foreign_key="exam.id", index=True)
    subject_id: int = Field(foreign_key="subject.id", index=True)
    exam_date: DateType
    # FN or AN
    session: str
    room: str


class HallTicket(SQLModel, table=True):
    """Generated exam hall ticket and eligibility status for a student (Day 3)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    exam_id: int = Field(foreign_key="exam.id", index=True)
    student_id: int = Field(foreign_key="student.id", index=True)
    ticket_no: str = Field(unique=True, index=True)
    is_eligible: bool = Field(default=True)
    reason: Optional[str] = Field(default=None)
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class LeaveRequest(SQLModel, table=True):
    """Student leave application reviewed by mentor or HOD (Day 2/3)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    student_id: int = Field(foreign_key="student.id", index=True)
    from_date: DateType
    to_date: DateType
    reason: str
    # pending, approved, or rejected
    status: str = Field(default="pending", index=True)
    decided_by_user_id: Optional[int] = Field(
        default=None, foreign_key="user.id"
    )


class Notice(SQLModel, table=True):
    """College, department, section, or role-targeted announcement (Day 2/3)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    body: str
    # all, department, section, or role
    audience: str
    department_id: Optional[int] = Field(
        default=None, foreign_key="department.id"
    )
    section_id: Optional[int] = Field(default=None, foreign_key="section.id")
    role: Optional[str] = Field(default=None)
    created_by_user_id: int = Field(foreign_key="user.id")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
