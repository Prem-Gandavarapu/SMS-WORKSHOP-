import sys
import unittest
from datetime import date
from pathlib import Path

# Allow running directly from the project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import SQLModel, Session, create_engine

import app.models  # noqa: F401
from app.models.academics import Batch, Department, MentorGroup, Section, Student
from app.models.registration import Registration
from app.models.users import Role, User
from app.services.approval import approve_registration
from app.services.placement import pick_mentor_group
from app.services.roll_number import next_roll_number


class TestAdmissionServices(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)

        self.dept = Department(code="CSE", name="Computer Science and Engineering")
        self.session.add(self.dept)
        self.session.flush()

        self.hod = User(
            username="hod.cse@college.edu",
            full_name="Dr. CSE HOD",
            email="hod.cse@college.edu",
            password_hash="hashed",
            role=Role.HOD,
            department_id=self.dept.id,
        )
        self.session.add(self.hod)
        self.session.commit()

    def tearDown(self):
        self.session.close()

    def _make_registration(self, ref_no: str, name: str = "Test Student") -> Registration:
        reg = Registration(
            reference_no=ref_no,
            full_name=name,
            dob=date(2008, 5, 10),
            gender="Male",
            phone="9876543210",
            email=f"{ref_no.lower()}@example.com",
            parent_name="Parent Name",
            department_id=self.dept.id,
            quota="convener",
            tenth_percent=90.0,
            inter_percent=92.0,
            photo_path="/static/photo.jpg",
            marks_memo_path="/static/memo.pdf",
            id_proof_path="/static/id.pdf",
        )
        self.session.add(reg)
        self.session.commit()
        return reg

    def test_roll_number_serials_increment(self):
        r1 = next_roll_number(self.session, self.dept, 2026)
        r2 = next_roll_number(self.session, self.dept, 2026)
        r3 = next_roll_number(self.session, self.dept, 2026)
        self.assertEqual(r1, "26CSE001")
        self.assertEqual(r2, "26CSE002")
        self.assertEqual(r3, "26CSE003")

    def test_full_mentor_group_of_30_is_skipped(self):
        batch = Batch(department_id=self.dept.id, start_year=2026, end_year=2030)
        self.session.add(batch)
        self.session.flush()

        section = Section(batch_id=batch.id, name="A", current_year=1, current_semester=1)
        self.session.add(section)
        self.session.flush()

        m1 = User(username="m1@college.edu", full_name="Mentor 1", password_hash="x", role=Role.MENTOR, department_id=self.dept.id)
        m2 = User(username="m2@college.edu", full_name="Mentor 2", password_hash="x", role=Role.MENTOR, department_id=self.dept.id)
        self.session.add_all([m1, m2])
        self.session.flush()

        g1 = MentorGroup(section_id=section.id, name="CSE-A Group 1", mentor_user_id=m1.id, capacity=30)
        g2 = MentorGroup(section_id=section.id, name="CSE-A Group 2", mentor_user_id=m2.id, capacity=30)
        self.session.add_all([g1, g2])
        self.session.flush()

        # Fill Group 1 with 30 students
        for i in range(30):
            u = User(username=f"26CSE{i+1:03d}", full_name=f"Student {i+1}", password_hash="x", role=Role.STUDENT, department_id=self.dept.id)
            self.session.add(u)
            self.session.flush()
            self.session.add(
                Student(
                    user_id=u.id,
                    roll_number=u.username,
                    full_name=u.full_name,
                    dob=date(2008, 1, 1),
                    gender="Male",
                    phone="9876543210",
                    email=f"s{i+1}@example.com",
                    parent_name="Parent",
                    department_id=self.dept.id,
                    batch_id=batch.id,
                    section_id=section.id,
                    mentor_group_id=g1.id,
                    quota="convener",
                    admission_year=2026,
                )
            )
        self.session.commit()

        picked = pick_mentor_group(self.session, section)
        self.assertIsNotNone(picked)
        self.assertEqual(picked.id, g2.id)

    def test_second_approve_call_fails(self):
        reg = self._make_registration("REG-2026-00001", "Aarav")
        result = approve_registration(self.session, reg, self.hod)
        self.assertEqual(result["roll_number"], "26CSE001")

        with self.assertRaises(ValueError):
            approve_registration(self.session, reg, self.hod)


if __name__ == "__main__":
    unittest.main()
