import os
from dotenv import load_dotenv

# Load environment variables from the .env file in the project root
load_dotenv()


class Settings:
    """Application settings loaded from environment variables."""

    def __init__(self) -> None:
        self.APP_NAME: str = os.getenv("APP_NAME", "GIST SMS")
        # Vercel's filesystem is read-only except /tmp, so default there when deployed
        self.IS_VERCEL: bool = bool(os.getenv("VERCEL"))
        default_db = "sqlite:////tmp/sms.db" if self.IS_VERCEL else "sqlite:///./sms.db"
        self.DATABASE_URL: str = os.getenv("DATABASE_URL", default_db)
        # Where uploaded registration documents are written (served at /static/uploads)
        self.UPLOAD_DIR: str = os.getenv(
            "UPLOAD_DIR", "/tmp/uploads" if self.IS_VERCEL else ""
        )
        # Populate demo data on startup when the database has no users
        self.SEED_DEMO_DATA: bool = os.getenv(
            "SEED_DEMO_DATA", "1" if self.IS_VERCEL else "0"
        ) == "1"
        self.SECRET_KEY: str = os.getenv("SECRET_KEY", "")
        self.ACCESS_TOKEN_MINUTES: int = int(os.getenv("ACCESS_TOKEN_MINUTES", "480"))
        self.ADMISSION_YEAR: int = int(os.getenv("ADMISSION_YEAR", "2026"))

        # Stop immediately if SECRET_KEY is missing or too short for JWT security
        if len(self.SECRET_KEY) < 32:
            raise ValueError(
                "Invalid SECRET_KEY in .env: it must be at least 32 characters long."
            )


# Create a single shared settings instance for the whole app
settings = Settings()
