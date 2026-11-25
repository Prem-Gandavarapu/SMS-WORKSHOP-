from typing import Optional

from sqlalchemy import func
from sqlmodel import Session, select

from app.models.academics import Batch, Department, MentorGroup, Section, Student


def get_or_create_batch(
    session: Session,
    department: Department,
    admission_year: int,
) -> Batch:
    """Return the batch for a department and admission year, creating it if needed."""
    batch = session.exec(
        select(Batch).where(
            Batch.department_id == department.id,
            Batch.start_year == admission_year,
        )
    ).first()

    if not batch:
        batch = Batch(
            department_id=department.id,
            start_year=admission_year,
            end_year=admission_year + 4,
        )
        session.add(batch)
        session.flush()

    return batch


def pick_section(session: Session, batch: Batch) -> Section:
    """
    Return the section in this batch with the fewest students that is still
    below capacity. If all sections are full (or none exist), create the next
    section (A, B, C...) with year 1 and semester 1.
    """
    sections = session.exec(
        select(Section)
        .where(Section.batch_id == batch.id)
        .order_by(Section.name)
    ).all()

    best_section: Optional[Section] = None
    best_count = 0

    for sec in sections:
        count = session.exec(
            select(func.count(Student.id)).where(Student.section_id == sec.id)
        ).one()
        if count < sec.capacity:
            if best_section is None or count < best_count:
                best_section = sec
                best_count = count

    if best_section is not None:
        return best_section

    next_name = chr(ord("A") + len(sections))
    new_section = Section(
        batch_id=batch.id,
        name=next_name,
        current_year=1,
        current_semester=1,
        capacity=60,
    )
    session.add(new_section)
    session.flush()
    return new_section


def pick_mentor_group(
    session: Session, section: Section
) -> Optional[MentorGroup]:
    """
    Return the mentor group in this section with fewer than 30 students and
    the fewest current students. Return None if no group has space.
    """
    groups = session.exec(
        select(MentorGroup)
        .where(MentorGroup.section_id == section.id)
        .order_by(MentorGroup.name)
    ).all()

    best_group: Optional[MentorGroup] = None
    best_count = 0

    for grp in groups:
        max_allowed = min(grp.capacity, 30)
        count = session.exec(
            select(func.count(Student.id)).where(Student.mentor_group_id == grp.id)
        ).one()
        if count < max_allowed:
            if best_group is None or count < best_count:
                best_group = grp
                best_count = count

    return best_group
