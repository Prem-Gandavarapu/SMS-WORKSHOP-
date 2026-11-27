import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import SQLModel, Session, create_engine, select

import app.models  # noqa: F401
from app.models.academics import Batch, Department, MentorGroup, Section, Student
from app.models.later import Attendance, LeaveRequest
from app.models.users import Role, User
from app.services.mark_attendance import (
    default_attendance_date,
    marked_periods,
    save_period_attendance,
    students_on_leave,
    validate_attendance_date,
)

TODAY = date(2026, 11, 27)  # a Friday


class TestMarkAttendance(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)

        dept = Department(code="CSE", name="Computer Science")
        self.session.add(dept)
        self.session.flush()
        batch = Batch(department_id=dept.id, start_year=2026, end_year=2030)
        self.session.add(batch)
        self.session.flush()
        section = Section(batch_id=batch.id, name="A")
        self.session.add(section)
        self.mentor = User(
            username="mentor@college.edu", full_name="Mentor", password_hash="x", role=Role.MENTOR
        )
        self.session.add(self.mentor)
        self.session.flush()
        self.group = MentorGroup(section_id=section.id, name="G1", mentor_user_id=self.mentor.id)
        self.session.add(self.group)
        self.session.flush()

        self.students = []
        for n in range(1, 4):
            user = User(username=f"26CSE00{n}", full_name=f"S{n}", password_hash="x", role=Role.STUDENT)
            self.session.add(user)
            self.session.flush()
            student = Student(
                user_id=user.id, roll_number=f"26CSE00{n}", full_name=f"S{n}", dob=date(2008, 1, 1),
                gender="Male", phone="9999999999", email=f"s{n}@x.com", parent_name="P",
                department_id=dept.id, batch_id=batch.id, section_id=section.id,
                mentor_group_id=self.group.id, quota="convener", admission_year=2026,
            )
            self.session.add(student)
            self.students.append(student)
        self.session.commit()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def statuses(self, *values):
        return {s.id: v for s, v in zip(self.students, values)}

    def test_save_creates_one_row_per_student(self):
        result = save_period_attendance(
            self.session, self.students, TODAY, 1, self.statuses("present", "absent", "late"), self.mentor.id
        )
        self.assertEqual(result, {"created": 3, "updated": 0})
        rows = self.session.exec(select(Attendance).order_by(Attendance.student_id)).all()
        self.assertEqual([r.status for r in rows], ["present", "absent", "late"])
        self.assertTrue(all(r.section_id == self.students[0].section_id for r in rows))

    def test_saving_again_updates_instead_of_duplicating(self):
        save_period_attendance(self.session, self.students, TODAY, 2, self.statuses("present", "present", "present"), self.mentor.id)
        result = save_period_attendance(self.session, self.students, TODAY, 2, self.statuses("absent", "present", "present"), self.mentor.id)
        self.assertEqual(result, {"created": 0, "updated": 3})
        rows = self.session.exec(select(Attendance).where(Attendance.period == 2)).all()
        self.assertEqual(len(rows), 3)
        self.assertEqual(sorted(r.status for r in rows), ["absent", "present", "present"])

    def test_every_student_must_be_marked(self):
        partial = {self.students[0].id: "present"}
        with self.assertRaises(ValueError):
            save_period_attendance(self.session, self.students, TODAY, 1, partial, self.mentor.id)
        self.assertEqual(self.session.exec(select(Attendance)).all(), [])

    def test_invalid_status_and_period_are_rejected(self):
        with self.assertRaises(ValueError):
            save_period_attendance(self.session, self.students, TODAY, 1, self.statuses("present", "sick", "present"), self.mentor.id)
        with self.assertRaises(ValueError):
            save_period_attendance(self.session, self.students, TODAY, 7, self.statuses("present", "present", "present"), self.mentor.id)

    def test_marked_periods_reports_completed_periods(self):
        ids = [s.id for s in self.students]
        self.assertEqual(marked_periods(self.session, ids, TODAY), set())
        save_period_attendance(self.session, self.students, TODAY, 3, self.statuses("present", "present", "present"), self.mentor.id)
        self.assertEqual(marked_periods(self.session, ids, TODAY), {3})

    def test_approved_leave_is_detected(self):
        self.session.add(LeaveRequest(student_id=self.students[1].id, from_date=date(2026, 11, 26), to_date=date(2026, 11, 28), reason="Fever", status="approved"))
        self.session.add(LeaveRequest(student_id=self.students[2].id, from_date=TODAY, to_date=TODAY, reason="Trip", status="pending"))
        self.session.commit()
        ids = [s.id for s in self.students]
        self.assertEqual(students_on_leave(self.session, ids, TODAY), {self.students[1].id})

    def test_date_rules(self):
        self.assertIsNone(validate_attendance_date(TODAY, TODAY))
        self.assertIsNone(validate_attendance_date(date(2026, 11, 20), TODAY))  # 7 days back
        self.assertIn("future", validate_attendance_date(date(2026, 11, 28), TODAY))
        self.assertIn("Sunday", validate_attendance_date(date(2026, 11, 22), TODAY))
        self.assertIn("last 7 days", validate_attendance_date(date(2026, 11, 19), TODAY))
        self.assertEqual(default_attendance_date(date(2026, 11, 29)), date(2026, 11, 28))  # Sunday -> Saturday


if __name__ == "__main__":
    unittest.main()
