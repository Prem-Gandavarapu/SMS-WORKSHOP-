from fastapi import FastAPI, Request
from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from sqlmodel import Session, select

from app.config import settings
from app.database import engine
from app.models.academics import (
    Batch,
    Department,
    MentorGroup,
    RollCounter,
    Section,
    Student,
    Subject,
    TeachingAssignment,
)
from app.models.later import (
    Attendance,
    Exam,
    ExamSchedule,
    HallTicket,
    LeaveRequest,
    Mark,
    Notice,
)
from app.models.registration import Registration
from app.models.users import Role, User
from app.security import verify_password


class AdminAuth(AuthenticationBackend):
    """Protect /admin so only active Admin users can sign in."""

    async def login(self, request: Request) -> bool:
        form = await request.form()
        username = str(form.get("username", "")).strip()
        password = str(form.get("password", ""))

        with Session(engine) as session:
            user = session.exec(
                select(User).where(User.username == username)
            ).first()
            if (
                user
                and user.is_active
                and user.role == Role.ADMIN
                and verify_password(password, user.password_hash)
            ):
                request.session.update({"admin_user_id": user.id})
                return True
        return False

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        admin_user_id = request.session.get("admin_user_id")
        if not admin_user_id:
            return False

        with Session(engine) as session:
            user = session.get(User, int(admin_user_id))
            return bool(
                user and user.is_active and user.role == Role.ADMIN
            )


# --- People ---
class UserAdmin(ModelView, model=User):
    category = "People"
    name = "User"
    name_plural = "Users"
    column_list = [
        User.id,
        User.username,
        User.full_name,
        User.role,
        User.department_id,
        User.is_active,
    ]
    column_searchable_list = [User.username, User.role]
    # Never display or allow editing password_hash
    form_excluded_columns = [User.password_hash]
    column_details_exclude_list = [User.password_hash]


class StudentAdmin(ModelView, model=Student):
    category = "People"
    name = "Student"
    name_plural = "Students"
    column_list = [
        Student.id,
        Student.roll_number,
        Student.full_name,
        Student.department_id,
        Student.section_id,
        Student.status,
    ]
    column_searchable_list = [Student.roll_number, Student.full_name]


# --- Academics ---
class DepartmentAdmin(ModelView, model=Department):
    category = "Academics"
    column_list = [Department.id, Department.code, Department.name, Department.intake]
    column_searchable_list = [Department.code, Department.name]


class BatchAdmin(ModelView, model=Batch):
    category = "Academics"
    column_list = [Batch.id, Batch.department_id, Batch.start_year, Batch.end_year]


class SectionAdmin(ModelView, model=Section):
    category = "Academics"
    column_list = [
        Section.id,
        Section.batch_id,
        Section.name,
        Section.current_year,
        Section.current_semester,
        Section.capacity,
    ]


class MentorGroupAdmin(ModelView, model=MentorGroup):
    category = "Academics"
    column_list = [
        MentorGroup.id,
        MentorGroup.section_id,
        MentorGroup.name,
        MentorGroup.mentor_user_id,
        MentorGroup.capacity,
    ]


class SubjectAdmin(ModelView, model=Subject):
    category = "Academics"
    column_list = [
        Subject.id,
        Subject.code,
        Subject.name,
        Subject.department_id,
        Subject.year,
        Subject.semester,
        Subject.credits,
    ]
    column_searchable_list = [Subject.code, Subject.name]


class TeachingAssignmentAdmin(ModelView, model=TeachingAssignment):
    category = "Academics"
    column_list = [
        TeachingAssignment.id,
        TeachingAssignment.subject_id,
        TeachingAssignment.section_id,
        TeachingAssignment.teacher_user_id,
    ]


class RollCounterAdmin(ModelView, model=RollCounter):
    category = "Academics"
    column_list = [
        RollCounter.id,
        RollCounter.department_id,
        RollCounter.admission_year,
        RollCounter.last_serial,
    ]


# --- Admissions ---
class RegistrationAdmin(ModelView, model=Registration):
    category = "Admissions"
    column_list = [
        Registration.id,
        Registration.reference_no,
        Registration.full_name,
        Registration.department_id,
        Registration.quota,
        Registration.status,
    ]
    column_searchable_list = [Registration.reference_no, Registration.status]


# --- Exams and attendance ---
class AttendanceAdmin(ModelView, model=Attendance):
    category = "Exams and attendance"
    column_list = [
        Attendance.id,
        Attendance.student_id,
        Attendance.section_id,
        Attendance.date,
        Attendance.period,
        Attendance.status,
    ]


class MarkAdmin(ModelView, model=Mark):
    category = "Exams and attendance"
    column_list = [
        Mark.id,
        Mark.student_id,
        Mark.subject_id,
        Mark.exam_type,
        Mark.max_marks,
        Mark.marks_obtained,
    ]


class ExamAdmin(ModelView, model=Exam):
    category = "Exams and attendance"
    column_list = [
        Exam.id,
        Exam.name,
        Exam.department_id,
        Exam.year,
        Exam.semester,
        Exam.is_published,
    ]


class ExamScheduleAdmin(ModelView, model=ExamSchedule):
    category = "Exams and attendance"
    column_list = [
        ExamSchedule.id,
        ExamSchedule.exam_id,
        ExamSchedule.subject_id,
        ExamSchedule.exam_date,
        ExamSchedule.session,
        ExamSchedule.room,
    ]


class HallTicketAdmin(ModelView, model=HallTicket):
    category = "Exams and attendance"
    column_list = [
        HallTicket.id,
        HallTicket.exam_id,
        HallTicket.student_id,
        HallTicket.ticket_no,
        HallTicket.is_eligible,
    ]


class LeaveRequestAdmin(ModelView, model=LeaveRequest):
    category = "Exams and attendance"
    column_list = [
        LeaveRequest.id,
        LeaveRequest.student_id,
        LeaveRequest.from_date,
        LeaveRequest.to_date,
        LeaveRequest.status,
    ]


class NoticeAdmin(ModelView, model=Notice):
    category = "Exams and attendance"
    column_list = [
        Notice.id,
        Notice.title,
        Notice.audience,
        Notice.created_at,
    ]


def setup_admin(app: FastAPI) -> Admin:
    """Mount SQLAdmin at /admin with session authentication."""
    auth_backend = AdminAuth(secret_key=settings.SECRET_KEY)
    admin = Admin(
        app=app,
        engine=engine,
        base_url="/admin",
        title="GIST SMS Admin",
        authentication_backend=auth_backend,
    )

    views = [
        UserAdmin,
        StudentAdmin,
        DepartmentAdmin,
        BatchAdmin,
        SectionAdmin,
        MentorGroupAdmin,
        SubjectAdmin,
        TeachingAssignmentAdmin,
        RollCounterAdmin,
        RegistrationAdmin,
        AttendanceAdmin,
        MarkAdmin,
        ExamAdmin,
        ExamScheduleAdmin,
        HallTicketAdmin,
        LeaveRequestAdmin,
        NoticeAdmin,
    ]
    for view in views:
        admin.add_view(view)

    return admin
