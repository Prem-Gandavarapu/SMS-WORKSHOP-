import unittest
from datetime import date

from app.models.academics import Subject
from app.models.later import Attendance, LeaveRequest
from app.services.attendance import (
    approved_leave_dates,
    calculate_attendance_summary,
    calendar_days,
    period_details,
    subject_attendance,
)


def make_records(statuses: list[str], attendance_date: date = date(2026, 11, 26)):
    return [
        Attendance(
            student_id=1,
            section_id=1,
            date=attendance_date,
            period=(index % 6) + 1,
            status=status,
            marked_by_user_id=10,
        )
        for index, status in enumerate(statuses)
    ]


class TestStudentAttendanceCalculations(unittest.TestCase):
    def test_30_present_out_of_36_is_green_with_four_safe_absences(self):
        summary = calculate_attendance_summary(
            make_records(["present"] * 30 + ["absent"] * 6)
        )
        self.assertAlmostEqual(summary["percentage"], 83.3, places=1)
        self.assertFalse(summary["is_low"])
        self.assertEqual(summary["max_additional_absences"], 4)

    def test_25_present_out_of_36_needs_eight_future_periods(self):
        summary = calculate_attendance_summary(
            make_records(["present"] * 25 + ["absent"] * 11)
        )
        self.assertAlmostEqual(summary["percentage"], 69.4, places=1)
        self.assertTrue(summary["is_low"])
        self.assertEqual(summary["required_consecutive_periods"], 8)
        self.assertIn("Your attendance is below 75%.", summary["warning"])

    def test_late_counts_as_attended(self):
        summary = calculate_attendance_summary(
            make_records(["present"] * 30 + ["late"] * 2 + ["absent"] * 4)
        )
        self.assertEqual(summary["late"], 2)
        self.assertEqual(summary["attended"], 32)
        self.assertAlmostEqual(summary["percentage"], 88.9, places=1)

    def test_zero_records_are_safe(self):
        summary = calculate_attendance_summary([])
        self.assertEqual(summary["total"], 0)
        self.assertEqual(summary["percentage"], 0.0)
        self.assertIsNone(summary["max_additional_absences"])

    def test_subject_period_mapping_and_totals(self):
        subjects = [
            Subject(
                id=index,
                code=f"CSE101{index}",
                name=f"Subject {index}",
                department_id=1,
                year=1,
                semester=1,
                credits=3,
            )
            for index in range(1, 7)
        ]
        records = [
            Attendance(
                student_id=1,
                section_id=1,
                date=date(2026, 11, 26),
                period=period,
                status="absent" if period == 2 else "present",
                marked_by_user_id=10,
            )
            for period in range(1, 7)
        ]
        rows = subject_attendance(records, subjects)
        self.assertEqual([row["period"] for row in rows], list(range(1, 7)))
        self.assertEqual(sum(row["held"] for row in rows), 6)
        self.assertEqual(sum(row["attended"] for row in rows), 5)
        self.assertTrue(rows[1]["is_low"])

    def test_calendar_colors_and_selected_period_details(self):
        selected = date(2026, 11, 26)
        records = [
            Attendance(
                student_id=1,
                section_id=1,
                date=selected,
                period=period,
                status=("absent" if period == 2 else "present"),
                marked_by_user_id=10,
            )
            for period in range(1, 7)
        ]
        subjects = [
            Subject(
                id=index,
                code=f"S{index}",
                name=f"Subject {index}",
                department_id=1,
                year=1,
                semester=1,
                credits=3,
            )
            for index in range(1, 7)
        ]
        days = calendar_days(2026, 11, records)
        selected_day = next(day for day in days if day["date"] == selected)
        sunday = next(day for day in days if day["date"].weekday() == 6)
        self.assertEqual(selected_day["color"], "amber")
        self.assertEqual(sunday["color"], "grey")

        details = period_details(selected, records, subjects)
        self.assertEqual(len(details), 6)
        self.assertEqual(details[1]["subject_code"], "S2")
        self.assertEqual(details[1]["status"], "absent")

    def test_approved_leave_overrides_attendance_status(self):
        leave = LeaveRequest(
            student_id=1,
            from_date=date(2026, 11, 26),
            to_date=date(2026, 11, 26),
            reason="Medical",
            status="approved",
        )
        leave_dates = approved_leave_dates([leave])
        summary = calculate_attendance_summary(
            make_records(["present"] * 6), leave_dates
        )
        self.assertEqual(summary["present"], 0)
        self.assertEqual(summary["absent"], 6)


if __name__ == "__main__":
    unittest.main()
