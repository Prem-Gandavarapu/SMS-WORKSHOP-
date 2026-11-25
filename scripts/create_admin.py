import sys
from pathlib import Path

# Allow running this script directly from the project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select

from app.database import create_db_and_tables, engine
from app.models.users import Role, User
from app.security import hash_password


def main() -> None:
    """Create a temporary management admin user for testing login."""
    create_db_and_tables()

    email = "management@college.edu"
    with Session(engine) as session:
        existing = session.exec(select(User).where(User.username == email)).first()
        if existing:
            print(f"Admin user already exists: {email}")
            return

        admin = User(
            username=email,
            full_name="College Management",
            email=email,
            password_hash=hash_password("Admin@123"),
            role=Role.MANAGEMENT,
            is_active=True,
            must_change_password=False,
        )
        session.add(admin)
        session.commit()
        print(f"Created management user: {email} / Admin@123")


if __name__ == "__main__":
    main()
