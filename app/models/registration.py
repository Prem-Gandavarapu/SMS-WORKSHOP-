from datetime import date, datetime, timezone
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


class RegistrationStatus(str, Enum):
    """Review status for a student's admission application."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CORRECTION = "correction"


class Registration(SQLModel, table=True):
    """Public first-year admission application reviewed by the department HOD."""

    id: Optional[int] = Field(default=None, primary_key=True)
    # Format: REG-2026-00001
    reference_no: str = Field(unique=True, index=True)
    full_name: str
    dob: date
    gender: str
    phone: str
    email: str
    parent_name: str
    department_id: int = Field(foreign_key="department.id", index=True)
    # convener, management, or spot
    quota: str
    entrance_rank: Optional[int] = Field(default=None)
    tenth_percent: float
    inter_percent: float
    photo_path: str
    marks_memo_path: str
    id_proof_path: str
    status: RegistrationStatus = Field(
        default=RegistrationStatus.PENDING, index=True
    )
    hod_remarks: Optional[str] = Field(default=None)
    submitted_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    decided_at: Optional[datetime] = Field(default=None)
    decided_by_user_id: Optional[int] = Field(
        default=None, foreign_key="user.id"
    )
    # Populated after HOD approval creates the Student record
    student_id: Optional[int] = Field(default=None, foreign_key="student.id")
