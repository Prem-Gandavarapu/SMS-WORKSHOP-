import secrets
import string
from datetime import datetime, timezone

from sqlmodel import Session

from app.config import settings
from app.models.academics import Department, Student
from app.models.registration import Registration, RegistrationStatus
from app.models.users import Role, User
from app.security import hash_password
from app.services.placement import (
    get_or_create_batch,
    pick_mentor_group,
    pick_section,
)
from app.services.roll_number import next_roll_number


def _generate_temp_password(length: int = 8) -> str:
    """Generate a random 8-character temporary password."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def approve_registration(
    session: Session,
    registration: Registration,
    hod_user: User,
) -> dict:
    """
    Approve a pending registration in one atomic database transaction.
    Rolls back all changes if anything fails.
    """
    if registration.status != RegistrationStatus.PENDING:
        raise ValueError("This registration has already been processed.")

    if hod_user.department_id != registration.department_id:
        raise ValueError("HOD can only approve registrations for their own department.")

    department = session.get(Department, registration.department_id)
    if not department:
        raise ValueError("Department not found for this registration.")

    admission_year = settings.ADMISSION_YEAR

    try:
        # 1. Generate roll number and temporary password
        roll_number = next_roll_number(session, department, admission_year)
        temp_password = _generate_temp_password(8)

        # 2. Create student login account
        student_user = User(
            username=roll_number,
            full_name=registration.full_name,
            email=registration.email,
            password_hash=hash_password(temp_password),
            role=Role.STUDENT,
            department_id=department.id,
            is_active=True,
            must_change_password=True,
        )
        session.add(student_user)
        session.flush()

        # 3. Assign batch, section, and mentor group
        batch = get_or_create_batch(session, department, admission_year)
        section = pick_section(session, batch)
        mentor_group = pick_mentor_group(session, section)
        mentor_user = (
            session.get(User, mentor_group.mentor_user_id)
            if mentor_group
            else None
        )

        # 4. Create Student profile
        student = Student(
            user_id=student_user.id,
            roll_number=roll_number,
            full_name=registration.full_name,
            dob=registration.dob,
            gender=registration.gender,
            phone=registration.phone,
            email=registration.email,
            parent_name=registration.parent_name,
            department_id=department.id,
            batch_id=batch.id,
            section_id=section.id,
            mentor_group_id=mentor_group.id if mentor_group else None,
            quota=registration.quota,
            admission_year=admission_year,
            status="active",
        )
        session.add(student)
        session.flush()

        # 5. Mark registration as approved
        registration.status = RegistrationStatus.APPROVED
        registration.decided_at = datetime.now(timezone.utc)
        registration.decided_by_user_id = hod_user.id
        registration.student_id = student.id
        session.add(registration)

        # Commit everything once at the end
        session.commit()
        session.refresh(student)
    except Exception:
        session.rollback()
        raise

    return {
        "roll_number": roll_number,
        "temp_password": temp_password,
        "section_name": section.name,
        "mentor_group_name": mentor_group.name if mentor_group else None,
        "mentor_name": mentor_user.full_name if mentor_user else None,
        "warning": (
            "Create a new mentor group for this section"
            if mentor_group is None
            else None
        ),
        "registration": registration,
        "student": student,
        "student_user": student_user,
        "department": department,
        "section": section,
        "mentor_group": mentor_group,
        "mentor_user": mentor_user,
        "yy": f"{admission_year % 100:02d}",
        "branch_code": department.code,
        "serial_str": roll_number[-3:],
    }
