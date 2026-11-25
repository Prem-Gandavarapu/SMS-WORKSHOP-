from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from app.models.users import User


class Department(SQLModel, table=True):
    """Engineering department such as CSE, ECE, EEE, MECH, or CIVIL."""

    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(unique=True, index=True)
    name: str
    intake: int = Field(default=120)
    hod_user_id: Optional[int] = Field(default=None, foreign_key="user.id")


class Batch(SQLModel, table=True):
    """Admission year batch for a department (e.g. 2026 to 2030)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    department_id: int = Field(foreign_key="department.id", index=True)
    start_year: int = Field(index=True)
    end_year: int


class Section(SQLModel, table=True):
    """Class section within a batch (e.g. A or B)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    batch_id: int = Field(foreign_key="batch.id", index=True)
    name: str
    current_year: int = Field(default=1)
    current_semester: int = Field(default=1)
    capacity: int = Field(default=60)


class MentorGroup(SQLModel, table=True):
    """Mentor group of up to 30 students within a section."""

    id: Optional[int] = Field(default=None, primary_key=True)
    section_id: int = Field(foreign_key="section.id", index=True)
    name: str
    mentor_user_id: int = Field(foreign_key="user.id", index=True)
    capacity: int = Field(default=30)


class Student(SQLModel, table=True):
    """Enrolled student profile linked to a user login and academic placement."""

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", unique=True, index=True)
    roll_number: str = Field(unique=True, index=True)
    full_name: str
    dob: date
    gender: str
    phone: str
    email: str
    parent_name: str
    department_id: int = Field(foreign_key="department.id", index=True)
    batch_id: int = Field(foreign_key="batch.id", index=True)
    section_id: int = Field(foreign_key="section.id", index=True)
    mentor_group_id: Optional[int] = Field(
        default=None, foreign_key="mentorgroup.id", index=True
    )
    quota: str
    admission_year: int = Field(index=True)
    status: str = Field(default="active", index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    # Relationships to simplify template rendering
    user: Optional[User] = Relationship()
    department: Optional[Department] = Relationship()
    section: Optional[Section] = Relationship()
    mentor_group: Optional[MentorGroup] = Relationship()


class Subject(SQLModel, table=True):
    """Academic subject offered by a department."""

    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True)
    name: str
    department_id: int = Field(foreign_key="department.id", index=True)
    year: int
    semester: int
    credits: int


class TeachingAssignment(SQLModel, table=True):
    """Assigns a mentor or external trainer to teach a subject for a section."""

    id: Optional[int] = Field(default=None, primary_key=True)
    subject_id: int = Field(foreign_key="subject.id", index=True)
    section_id: int = Field(foreign_key="section.id", index=True)
    teacher_user_id: int = Field(foreign_key="user.id", index=True)


class RollCounter(SQLModel, table=True):
    """Tracks the last generated roll number serial per department and year."""

    __table_args__ = (
        UniqueConstraint(
            "department_id", "admission_year", name="uq_rollcounter_dept_year"
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    department_id: int = Field(foreign_key="department.id", index=True)
    admission_year: int = Field(index=True)
    last_serial: int = Field(default=0)
