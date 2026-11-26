from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


class Role(str, Enum):
    """User roles in GIST SMS."""

    MANAGEMENT = "management"
    HOD = "hod"
    MENTOR = "mentor"
    TRAINER = "trainer"
    STUDENT = "student"


class User(SQLModel, table=True):
    """Login account for staff, trainers, and students."""

    id: Optional[int] = Field(default=None, primary_key=True)
    # Email for staff/trainers, roll number for students
    username: str = Field(unique=True, index=True)
    full_name: str
    email: Optional[str] = Field(default=None, index=True)
    password_hash: str
    role: Role = Field(index=True)
    department_id: Optional[int] = Field(
        default=None, foreign_key="department.id", index=True
    )
    is_active: bool = Field(default=True)
    must_change_password: bool = Field(default=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
