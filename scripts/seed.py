import random
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from faker import Faker
from sqlalchemy import func
from sqlmodel import Session, select

from app.database import create_db_and_tables, engine
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
from app.models.registration import Registration, RegistrationStatus
from app.models.users import Role, User
from app.security import hash_password
from app.services.roll_number import next_roll_number

DEPARTMENTS = [
    ("CSE", "Computer Science and Engineering"),
    ("ECE", "Electronics and Communication Engineering"),
    ("EEE", "Electrical and Electronics Engineering"),
    ("MECH", "Mechanical Engineering"),
    ("CIVIL", "Civil Engineering"),
]

SUBJECT_TOPICS = [
    "Engineering Mathematics",
    "Programming & Problem Solving",
    "Data Structures",
    "Digital Logic & Systems",
    "Database Management",
    "Soft Skills & Aptitude",
]

ATTENDANCE_PERIODS = range(1, 7)
ATTENDANCE_WORKING_DAYS = 6


def academic_progress(admission_year: int, today: date) -> tuple[int, int]:
    """Calculate year/semester using a July-June academic calendar."""
    completed_years = today.year - admission_year
    if today.month < 7:
        completed_years -= 1

    current_year = min(max(completed_years + 1, 1), 4)
    semester_in_year = 1 if today.month >= 7 else 2
    current_semester = (current_year - 1) * 2 + semester_in_year
    return current_year, current_semester


def recent_working_days(today: date) -> list[date]:
    """Return the six most recent Monday-Saturday dates before today."""
    working_days: list[date] = []
    candidate = today - timedelta(days=1)
    while len(working_days) < ATTENDANCE_WORKING_DAYS:
        if candidate.weekday() != 6:  # Sunday
            working_days.append(candidate)
        candidate -= timedelta(days=1)
    return working_days


def generate_attendance(
    students: list[tuple[Student, int, int]],
    today: date,
) -> tuple[list[Attendance], Counter[str], dict[int, dict[str, int]]]:
    """Create deterministic attendance rows and per-student status counts.

    The tuple for each student contains the student object, section ID, and
    mentor user ID. Attendance plans are assigned after a deterministic shuffle:
    10% at-risk students receive 12 absences, 85% receive 2-7 absences, and the
    remaining students receive 8 absences. Late marks replace a small number of
    present periods and therefore still count as attended.
    """
    working_days = recent_working_days(today)
    slots = [(day, period) for day in working_days for period in ATTENDANCE_PERIODS]
    shuffled_students = students.copy()
    random.shuffle(shuffled_students)

    total_students = len(shuffled_students)
    at_risk_count = round(total_students * 0.10)
    normal_count = round(total_students * 0.85)
    late_student_count = max(1, total_students // 20)
    late_students = set(random.sample(range(total_students), late_student_count))

    attendance_rows: list[Attendance] = []
    status_counts: Counter[str] = Counter()
    per_student_counts: dict[int, dict[str, int]] = {}

    for position, (student, section_id, mentor_user_id) in enumerate(shuffled_students):
        if position < at_risk_count:
            absence_count = 12
        elif position < at_risk_count + normal_count:
            absence_count = random.randint(2, 7)
        else:
            absence_count = 8

        absent_slots = set(random.sample(range(len(slots)), absence_count))
        present_slots = [idx for idx in range(len(slots)) if idx not in absent_slots]
        late_slot = (
            random.choice(present_slots)
            if position in late_students
            else None
        )

        counts = Counter[str]()
        for slot_index, (attendance_date, period) in enumerate(slots):
            if slot_index in absent_slots:
                status = "absent"
            elif slot_index == late_slot:
                status = "late"
            else:
                status = "present"

            attendance_rows.append(
                Attendance(
                    student_id=student.id,
                    section_id=section_id,
                    date=attendance_date,
                    period=period,
                    status=status,
                    marked_by_user_id=mentor_user_id,
                )
            )
            counts[status] += 1
            status_counts[status] += 1

        per_student_counts[student.id] = dict(counts)

    return attendance_rows, status_counts, per_student_counts


def seed() -> None:
    """Reset sms.db and populate realistic Indian demo data."""
    random.seed(42)
    fake = Faker("en_IN")
    Faker.seed(42)
    current_date = date.today()

    # Delete the configured SQLite file so the script can be re-run cleanly anytime
    engine.dispose()
    db_file = engine.url.database if engine.url.get_backend_name() == "sqlite" else None
    if db_file and db_file != ":memory:":
        db_path = Path(db_file)
        if db_path.exists():
            db_path.unlink()

    create_db_and_tables()

    # Pre-hash shared demo passwords once so seeding 500+ users is fast
    admin_hash = hash_password("Admin@123")
    hod_hash = hash_password("Hod@123")
    mentor_hash = hash_password("Mentor@123")
    trainer_hash = hash_password("Trainer@123")
    student_hash = hash_password("Student@123")

    sample_student_roll = None
    attendance_students: list[tuple[Student, int, int]] = []

    with Session(engine) as session:
        # 1. Management user
        mgmt = User(
            username="management@college.edu",
            full_name="Dr. Ramesh Rao",
            email="management@college.edu",
            password_hash=admin_hash,
            role=Role.MANAGEMENT,
        )
        session.add(mgmt)

        # Separate system administrator for the /admin database panel
        session.add(
            User(
                username="admin@college.edu",
                full_name="System Administrator",
                email="admin@college.edu",
                password_hash=hash_password("SuperAdmin@123"),
                role=Role.ADMIN,
            )
        )
        session.flush()

        # 2. 5 Departments + 5 HODs
        dept_objs: list[Department] = []
        hod_objs: dict[int, User] = {}
        for code, name in DEPARTMENTS:
            dept = Department(code=code, name=name, intake=120)
            session.add(dept)
            session.flush()

            hod_email = f"hod.{code.lower()}@college.edu"
            hod_user = User(
                username=hod_email,
                full_name=f"Dr. {fake.name()}",
                email=hod_email,
                password_hash=hod_hash,
                role=Role.HOD,
                department_id=dept.id,
            )
            session.add(hod_user)
            session.flush()

            dept.hod_user_id = hod_user.id
            session.add(dept)
            dept_objs.append(dept)
            hod_objs[dept.id] = hod_user

        # 3. 3 External Trainers
        trainers: list[User] = []
        for idx in range(1, 4):
            t_email = f"trainer{idx}@college.edu"
            trainer = User(
                username=t_email,
                full_name=fake.name(),
                email=t_email,
                password_hash=trainer_hash,
                role=Role.TRAINER,
            )
            session.add(trainer)
            trainers.append(trainer)
        session.flush()

        # 4. Batches, Sections, MentorGroups, Students, Subjects & TeachingAssignments
        reg_serial = 0
        for dept in dept_objs:
            # 6 subjects per department and year (years 1..4)
            subjects_by_year: dict[int, list[Subject]] = {}
            for yr in range(1, 5):
                sem = (yr - 1) * 2 + 1
                year_subjects = []
                for s_idx, topic in enumerate(SUBJECT_TOPICS, start=1):
                    subj = Subject(
                        code=f"{dept.code}{yr}0{s_idx}",
                        name=f"{topic} ({yr} Yr)",
                        department_id=dept.id,
                        year=yr,
                        semester=sem,
                        credits=3 if s_idx < 6 else 2,
                    )
                    session.add(subj)
                    year_subjects.append(subj)
                subjects_by_year[yr] = year_subjects
            session.flush()

            for adm_year in range(current_date.year, current_date.year - 4, -1):
                cur_year, cur_sem = academic_progress(adm_year, current_date)
                batch = Batch(
                    department_id=dept.id,
                    start_year=adm_year,
                    end_year=adm_year + 4,
                )
                session.add(batch)
                session.flush()

                for sec_name, stu_count in [("A", 13), ("B", 12)]:
                    section = Section(
                        batch_id=batch.id,
                        name=sec_name,
                        current_year=cur_year,
                        current_semester=cur_sem,
                        capacity=60,
                    )
                    session.add(section)
                    session.flush()

                    # Mentor user & MentorGroup (1 per section, < 30 students)
                    m_email = f"mentor.{dept.code.lower()}.{adm_year}{sec_name.lower()}@college.edu"
                    mentor = User(
                        username=m_email,
                        full_name=fake.name(),
                        email=m_email,
                        password_hash=mentor_hash,
                        role=Role.MENTOR,
                        department_id=dept.id,
                    )
                    session.add(mentor)
                    session.flush()

                    mgroup = MentorGroup(
                        section_id=section.id,
                        name=f"{dept.code}-{adm_year}{sec_name} Group 1",
                        mentor_user_id=mentor.id,
                        capacity=30,
                    )
                    session.add(mgroup)
                    session.flush()

                    # Assign subjects: first 5 to mentor, 6th (Soft Skills) to an external trainer
                    for idx_s, subj in enumerate(subjects_by_year[cur_year]):
                        teacher = (
                            trainers[dept.id % len(trainers)]
                            if idx_s == len(subjects_by_year[cur_year]) - 1
                            else mentor
                        )
                        session.add(
                            TeachingAssignment(
                                subject_id=subj.id,
                                section_id=section.id,
                                teacher_user_id=teacher.id,
                            )
                        )

                    # Create 12-13 students per section (~500 total)
                    for _ in range(stu_count):
                        roll_no = next_roll_number(session, dept, adm_year)
                        if sample_student_roll is None:
                            sample_student_roll = roll_no

                        gender = random.choice(["Male", "Female"])
                        full_name = (
                            fake.name_male()
                            if gender == "Male"
                            else fake.name_female()
                        )
                        stu_email = f"{roll_no.lower()}@student.college.edu"

                        stu_user = User(
                            username=roll_no,
                            full_name=full_name,
                            email=stu_email,
                            password_hash=student_hash,
                            role=Role.STUDENT,
                            department_id=dept.id,
                            must_change_password=False,
                        )
                        session.add(stu_user)
                        session.flush()

                        dob_year = adm_year - 18
                        student = Student(
                            user_id=stu_user.id,
                            roll_number=roll_no,
                            full_name=full_name,
                            dob=date(
                                dob_year,
                                random.randint(1, 12),
                                random.randint(1, 28),
                            ),
                            gender=gender,
                            phone=f"9{random.randint(100000000, 999999999)}",
                            email=stu_email,
                            parent_name=fake.name(),
                            department_id=dept.id,
                            batch_id=batch.id,
                            section_id=section.id,
                            mentor_group_id=mgroup.id,
                            quota=random.choice(["convener", "management", "spot"]),
                            admission_year=adm_year,
                            status="active",
                        )
                        session.add(student)
                        attendance_students.append((student, section.id, mentor.id))

            # 5. Registrations per department: 6 pending, 1 correction, 1 rejected
            reg_plan = (
                [(RegistrationStatus.PENDING, None)] * 6
                + [(RegistrationStatus.CORRECTION, "Please re-upload a clearer 12th marks memo.")]
                + [(RegistrationStatus.REJECTED, "Minimum eligibility percentage not met.")]
            )
            for status_val, remarks in reg_plan:
                reg_serial += 1
                ref_no = f"REG-2026-{reg_serial:05d}"
                gender = random.choice(["Male", "Female"])
                quota = random.choice(["convener", "management", "spot"])
                session.add(
                    Registration(
                        reference_no=ref_no,
                        full_name=fake.name(),
                        dob=date(2008, random.randint(1, 12), random.randint(1, 28)),
                        gender=gender,
                        phone=f"9{random.randint(100000000, 999999999)}",
                        email=fake.email(),
                        parent_name=fake.name(),
                        department_id=dept.id,
                        quota=quota,
                        entrance_rank=(
                            random.randint(1200, 35000)
                            if quota == "convener"
                            else None
                        ),
                        tenth_percent=round(random.uniform(72.0, 97.5), 2),
                        inter_percent=round(random.uniform(68.0, 96.5), 2),
                        photo_path="/static/uploads/demo/photo.jpg",
                        marks_memo_path="/static/uploads/demo/marks_memo.pdf",
                        id_proof_path="/static/uploads/demo/id_proof.pdf",
                        status=status_val,
                        hod_remarks=remarks,
                        decided_at=(
                            datetime.now(timezone.utc)
                            if status_val != RegistrationStatus.PENDING
                            else None
                        ),
                        decided_by_user_id=(
                            hod_objs[dept.id].id
                            if status_val != RegistrationStatus.PENDING
                            else None
                        ),
                    )
                )

        session.flush()

        # 6. Historical attendance for the six most recent working days.
        attendance_rows, attendance_status_counts, per_student_counts = generate_attendance(
            attendance_students,
            current_date,
        )
        session.add_all(attendance_rows)

        # 7. 3 Notices
        notices = [
            Notice(
                title="Welcome to Academic Year 2026-27",
                body="Classes for all B.Tech semesters commence on Monday at 9:00 AM.",
                audience="all",
                created_by_user_id=mgmt.id,
            ),
            Notice(
                title="CSE Orientation & Lab Induction",
                body="First-year CSE students must report to Seminar Hall 1 at 10:00 AM.",
                audience="department",
                department_id=dept_objs[0].id,
                created_by_user_id=hod_objs[dept_objs[0].id].id,
            ),
            Notice(
                title="Soft Skills Training Schedule",
                body="External trainer sessions will be held every Wednesday and Friday.",
                audience="role",
                role="student",
                created_by_user_id=mgmt.id,
            ),
        ]
        session.add_all(notices)
        session.commit()

        total_periods = ATTENDANCE_WORKING_DAYS * len(ATTENDANCE_PERIODS)
        at_risk_students = sum(
            counts.get("present", 0) + counts.get("late", 0)
            < total_periods * 0.75
            for counts in per_student_counts.values()
        )
        attended_periods = (
            attendance_status_counts["present"] + attendance_status_counts["late"]
        )
        overall_percentage = attended_periods / len(attendance_rows) * 100

        print("\n=== ATTENDANCE SUMMARY ===")
        print(f"Working days             : {ATTENDANCE_WORKING_DAYS}")
        print(f"Periods per working day : {len(ATTENDANCE_PERIODS)}")
        print(f"Total records generated : {len(attendance_rows)}")
        print(f"Total students included : {len(attendance_students)}")
        print(f"Present records         : {attendance_status_counts['present']}")
        print(f"Absent records          : {attendance_status_counts['absent']}")
        print(f"Late records            : {attendance_status_counts['late']}")
        print(f"Students below 75%      : {at_risk_students}")
        print(f"Overall attendance      : {overall_percentage:.2f}%")

        # Print demo logins table and record counts
        print("\n=== DEMO-ONLY LOGINS (One per Role) ===")
        print(f"{'Role':<12} {'Username':<35} {'Password':<15}")
        print("-" * 64)
        print(f"{'admin':<12} {'admin@college.edu':<35} {'SuperAdmin@123':<15}")
        print(f"{'management':<12} {'management@college.edu':<35} {'Admin@123':<15}")
        print(f"{'hod':<12} {'hod.cse@college.edu':<35} {'Hod@123':<15}")
        print(f"{'mentor':<12} {'mentor.cse.2026a@college.edu':<35} {'Mentor@123':<15}")
        print(f"{'trainer':<12} {'trainer1@college.edu':<35} {'Trainer@123':<15}")
        print(f"{'student':<12} {sample_student_roll:<35} {'Student@123':<15}")

        print("\n=== DATABASE TABLE COUNTS ===")
        models_to_count = [
            ("Department", Department),
            ("Batch", Batch),
            ("Section", Section),
            ("MentorGroup", MentorGroup),
            ("User", User),
            ("Student", Student),
            ("Subject", Subject),
            ("TeachingAssignment", TeachingAssignment),
            ("RollCounter", RollCounter),
            ("Registration", Registration),
            ("Notice", Notice),
            ("Attendance", Attendance),
            ("Mark", Mark),
            ("Exam", Exam),
            ("ExamSchedule", ExamSchedule),
            ("HallTicket", HallTicket),
            ("LeaveRequest", LeaveRequest),
        ]
        for label, model in models_to_count:
            cnt = session.exec(select(func.count(model.id))).one()
            print(f"{label:<20}: {cnt}")


if __name__ == "__main__":
    seed()
