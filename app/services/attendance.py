from calendar import monthrange
from collections import Counter
from datetime import date, timedelta
from math import ceil, floor
from typing import Iterable

from app.models.academics import Subject
from app.models.later import Attendance, LeaveRequest

ATTENDANCE_PERIODS = tuple(range(1, 7))
LOW_ATTENDANCE_THRESHOLD = 75.0


def normalize_status(status: str, attendance_date: date, leave_dates: set[date]) -> str:
    """Treat approved leave periods as absent without changing stored records."""
    if attendance_date in leave_dates:
        return "absent"
    return status.lower()


def calculate_attendance_summary(
    records: Iterable[Attendance],
    leave_dates: set[date] | None = None,
) -> dict:
    """Calculate overall attendance from actual records, with late as attended."""
    leave_dates = leave_dates or set()
    counts: Counter[str] = Counter()
    for record in records:
        status = normalize_status(record.status, record.date, leave_dates)
        if status in {"present", "absent", "late"}:
            counts[status] += 1

    total = sum(counts.values())
    present = counts["present"]
    absent = counts["absent"]
    late = counts["late"]
    attended = present + late
    percentage = attended / total * 100 if total else 0.0

    summary = {
        "total": total,
        "present": present,
        "absent": absent,
        "late": late,
        "attended": attended,
        "percentage": round(percentage, 1),
        "is_low": total > 0 and percentage < LOW_ATTENDANCE_THRESHOLD,
        "warning": None,
        "max_additional_absences": None,
        "required_consecutive_periods": None,
        "guidance": None,
    }

    if total == 0:
        summary["guidance"] = "No attendance records are available yet."
    elif percentage < LOW_ATTENDANCE_THRESHOLD:
        # Solve (attended + x) / (total + x) >= 0.75.
        required = ceil(
            (LOW_ATTENDANCE_THRESHOLD / 100 * total - attended)
            / (1 - LOW_ATTENDANCE_THRESHOLD / 100)
        )
        summary["required_consecutive_periods"] = max(required, 0)
        summary["warning"] = (
            "Your attendance is below 75%. You may not be eligible for exams. "
            "Please meet your mentor."
        )
        summary["guidance"] = (
            f"Attend the next {summary['required_consecutive_periods']} "
            "consecutive periods to reach 75%."
        )
    else:
        # Solve attended / (total + x) >= 0.75.
        maximum = floor(
            attended / (LOW_ATTENDANCE_THRESHOLD / 100) - total + 1e-9
        )
        summary["max_additional_absences"] = max(maximum, 0)
        summary["guidance"] = (
            f"You can miss up to {summary['max_additional_absences']} more "
            "periods and remain at or above 75%."
        )

    return summary


def subject_attendance(
    records: Iterable[Attendance],
    subjects: list[Subject],
    leave_dates: set[date] | None = None,
) -> list[dict]:
    """Map periods 1-6 to the section's six subjects and calculate totals."""
    leave_dates = leave_dates or set()
    by_subject: dict[int, list[Attendance]] = {index: [] for index in range(6)}
    for record in records:
        if 1 <= record.period <= 6 and record.period <= len(subjects):
            by_subject[record.period - 1].append(record)

    rows = []
    for index, subject in enumerate(subjects[:6]):
        subject_records = by_subject[index]
        statuses = [
            normalize_status(record.status, record.date, leave_dates)
            for record in subject_records
        ]
        held = len(statuses)
        attended = sum(status in {"present", "late"} for status in statuses)
        rows.append(
            {
                "code": subject.code,
                "name": subject.name,
                "period": index + 1,
                "held": held,
                "attended": attended,
                "percentage": round(attended / held * 100, 1) if held else 0.0,
                "is_low": held > 0 and attended / held * 100 < LOW_ATTENDANCE_THRESHOLD,
            }
        )
    return rows


def calendar_days(
    year: int,
    month: int,
    records: Iterable[Attendance],
    leave_dates: set[date] | None = None,
) -> list[dict]:
    """Build the current month's calendar state from stored attendance rows."""
    leave_dates = leave_dates or set()
    records_by_date: dict[date, list[Attendance]] = {}
    for record in records:
        if record.date.year == year and record.date.month == month:
            records_by_date.setdefault(record.date, []).append(record)

    first_day = date(year, month, 1)
    start = first_day - timedelta(days=first_day.weekday())
    last_day = date(year, month, monthrange(year, month)[1])
    end = last_day + timedelta(days=6 - last_day.weekday())

    days = []
    current = start
    while current <= end:
        day_records = records_by_date.get(current, [])
        statuses = [
            normalize_status(record.status, current, leave_dates)
            for record in day_records
        ]
        absent_count = statuses.count("absent")
        if current.weekday() == 6 or not statuses:
            color = "grey"
        elif absent_count == 0:
            color = "green"
        elif absent_count == len(statuses):
            color = "red"
        else:
            color = "amber"

        days.append(
            {
                "date": current,
                "day": current.day,
                "color": color,
                "is_current_month": current.month == month,
                "is_leave": current in leave_dates,
                "is_sunday": current.weekday() == 6,
            }
        )
        current += timedelta(days=1)
    return days


def period_details(
    selected_date: date,
    records: Iterable[Attendance],
    subjects: list[Subject],
    leave_dates: set[date] | None = None,
) -> list[dict]:
    """Return six period rows for a selected date, including missing records."""
    leave_dates = leave_dates or set()
    by_period = {
        record.period: record
        for record in records
        if record.date == selected_date
    }
    details = []
    for period in ATTENDANCE_PERIODS:
        record = by_period.get(period)
        status = (
            normalize_status(record.status, selected_date, leave_dates)
            if record
            else "no record"
        )
        subject = subjects[period - 1] if period <= len(subjects) else None
        details.append(
            {
                "period": period,
                "subject_code": subject.code if subject else "-",
                "subject_name": subject.name if subject else "Subject unavailable",
                "status": status,
                "label": status.title(),
            }
        )
    return details


def approved_leave_dates(leaves: Iterable[LeaveRequest]) -> set[date]:
    """Expand approved leave ranges into individual dates."""
    dates: set[date] = set()
    for leave in leaves:
        if leave.status != "approved":
            continue
        current = leave.from_date
        while current <= leave.to_date:
            dates.add(current)
            current += timedelta(days=1)
    return dates
