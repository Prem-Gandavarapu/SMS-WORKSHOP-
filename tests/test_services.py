import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

# Allow running directly from the project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import SQLModel, Session, create_engine, select

import app.models  # noqa: F401
from app.models.academics import (
    Batch,
    Department,
    MentorGroup,
    RollCounter,
    Section,
    Student,
)
from app.models.registration import Registration, RegistrationStatus
from app.models.users import Role, User
from app.routers.hod import _hod_nav_links
from app.services.approval import approve_registration
from app.services.placement import pick_mentor_group
from app.services.roll_number import next_roll_number
from scripts.seed import academic_progress, recent_working_days


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

    def test_approval_rejects_cross_department_registration(self):
        ece = Department(code="ECE", name="Electronics and Communication Engineering")
        self.session.add(ece)
        self.session.commit()
        reg = self._make_registration("REG-2026-00002", "Bhavna")
        reg.department_id = ece.id
        self.session.add(reg)
        self.session.commit()

        with self.assertRaises(ValueError):
            approve_registration(self.session, reg, self.hod)

        self.session.refresh(reg)
        self.assertEqual(reg.status, RegistrationStatus.PENDING)
        self.assertEqual(
            self.session.exec(select(RollCounter)).all(),
            [],
        )

    def test_approval_rolls_back_when_account_creation_fails(self):
        reg = self._make_registration("REG-2026-00003", "Charan")

        with patch(
            "app.services.approval.hash_password",
            side_effect=RuntimeError("simulated failure"),
        ):
            with self.assertRaises(RuntimeError):
                approve_registration(self.session, reg, self.hod)

        self.session.refresh(reg)
        self.assertEqual(reg.status, RegistrationStatus.PENDING)
        self.assertEqual(self.session.exec(select(RollCounter)).all(), [])
        self.assertEqual(
            self.session.exec(
                select(User).where(User.username == "26CSE001")
            ).all(),
            [],
        )

    def test_academic_progress_uses_july_june_calendar(self):
        self.assertEqual(academic_progress(2026, date(2026, 11, 27)), (1, 1))
        self.assertEqual(academic_progress(2025, date(2026, 11, 27)), (2, 3))
        self.assertEqual(academic_progress(2024, date(2026, 11, 27)), (3, 5))
        self.assertEqual(academic_progress(2023, date(2026, 11, 27)), (4, 7))

    def test_recent_working_days_excludes_today_and_sunday(self):
        days = recent_working_days(date(2026, 11, 27))
        self.assertEqual(len(days), 6)
        self.assertTrue(all(day.weekday() != 6 for day in days))
        self.assertNotIn(date(2026, 11, 27), days)

    def test_hod_upcoming_navigation_items_open_coming_soon_pages(self):
        links = _hod_nav_links("registrations", pending_count=2)
        self.assertEqual(links[1]["url"], "/hod/registrations")
        self.assertTrue(links[1]["active"])
        self.assertEqual(links[1]["badge"], 2)
        upcoming = links[2:]
        self.assertTrue(upcoming)
        self.assertTrue(all(link["url"].startswith("/coming-soon/") for link in upcoming))
        self.assertTrue(all(link["tag"] == "Soon" for link in upcoming))


if __name__ == "__main__":
    unittest.main()
