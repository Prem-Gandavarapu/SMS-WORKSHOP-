from sqlmodel import Session, select

from app.models.academics import Department, RollCounter


def next_roll_number(
    session: Session,
    department: Department,
    admission_year: int,
) -> str:
    """
    Generate the next roll number in the format YY + BRANCH + 3-digit serial
    (for example: 26CSE001, 26CSE002).
    """
    # Using a dedicated RollCounter table is safer than counting Student rows:
    # if a student record is ever deleted or dropped, counting rows would reuse
    # an old serial number and cause duplicates, whereas a counter only moves forward.
    counter = session.exec(
        select(RollCounter).where(
            RollCounter.department_id == department.id,
            RollCounter.admission_year == admission_year,
        )
    ).first()

    if not counter:
        counter = RollCounter(
            department_id=department.id,
            admission_year=admission_year,
            last_serial=0,
        )
        session.add(counter)
        session.flush()

    counter.last_serial += 1
    session.add(counter)
    session.flush()

    return f"{admission_year % 100:02d}{department.code}{counter.last_serial:03d}"
