import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.admin import setup_admin
from app.config import settings
from app.database import create_db_and_tables, engine
from app.models.academics import Department
from app.routers import auth, coming_soon, dashboards, hod, mentor, register

# Resolve paths relative to the app/ folder
APP_DIR = Path(__file__).resolve().parent


def ensure_default_departments() -> None:
    """Create the 5 B.Tech departments on first run if the table is empty."""
    defaults = [
        ("CSE", "Computer Science and Engineering"),
        ("ECE", "Electronics and Communication Engineering"),
        ("EEE", "Electrical and Electronics Engineering"),
        ("MECH", "Mechanical Engineering"),
        ("CIVIL", "Civil Engineering"),
    ]
    with Session(engine) as session:
        existing = session.exec(select(Department)).first()
        if not existing:
            for code, name in defaults:
                session.add(Department(code=code, name=name))
            session.commit()


def init_app_data() -> None:
    """Create tables and default data; seed demo data on an empty database if enabled."""
    create_db_and_tables()
    if settings.SEED_DEMO_DATA:
        from app.models.users import User

        with Session(engine) as session:
            has_users = session.exec(select(User)).first() is not None
        if not has_users:
            from scripts.seed import seed

            seed()
    ensure_default_departments()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup and shutdown tasks for the application."""
    init_app_data()
    yield


# Initialize the FastAPI application
app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

# Serve uploads from a writable directory when configured (e.g. /tmp on Vercel).
# Mounted before /static so it takes precedence for /static/uploads paths.
if settings.UPLOAD_DIR:
    Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
    # Demo applications reference bundled sample documents under /static/uploads/demo
    shutil.copytree(
        APP_DIR / "static" / "uploads" / "demo",
        Path(settings.UPLOAD_DIR) / "demo",
        dirs_exist_ok=True,
    )
    app.mount("/static/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")

# Serve CSS, JS, and images from /static
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")

# Configure Jinja2 to load HTML templates from app/templates
templates = Jinja2Templates(directory=APP_DIR / "templates")

# Register application routers
app.include_router(auth.router)
app.include_router(dashboards.router)
app.include_router(register.router)
app.include_router(hod.router)
app.include_router(coming_soon.router)
app.include_router(mentor.router)

# Mount SQLAdmin at /admin
setup_admin(app)


@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Show a friendly HTML page for 403 Forbidden and 404 Not Found errors."""
    if exc.status_code in (403, 404):
        title = "Access Denied" if exc.status_code == 403 else "Page Not Found"
        detail = exc.detail
        if exc.status_code == 404 and detail in (None, "Not Found"):
            detail = "The page you are looking for does not exist."
        return templates.TemplateResponse(
            request,
            "403.html",
            {"code": exc.status_code, "title": title, "detail": detail},
            status_code=exc.status_code,
        )
    from fastapi.exception_handlers import http_exception_handler

    return await http_exception_handler(request, exc)


@app.get("/health")
def health_check():
    """Simple health check endpoint to verify the server is running."""
    return {"status": "ok"}


@app.get("/")
def root():
    """Redirect the home URL to the login page."""
    return RedirectResponse(url="/login", status_code=302)
