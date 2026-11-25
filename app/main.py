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
from app.routers import auth, dashboards, hod, register

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup and shutdown tasks for the application."""
    # Create database tables when the server starts
    create_db_and_tables()
    ensure_default_departments()
    yield


# Initialize the FastAPI application
app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

# Serve CSS, JS, and images from /static
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")

# Configure Jinja2 to load HTML templates from app/templates
templates = Jinja2Templates(directory=APP_DIR / "templates")

# Register application routers
app.include_router(auth.router)
app.include_router(dashboards.router)
app.include_router(register.router)
app.include_router(hod.router)

# Mount SQLAdmin at /admin
setup_admin(app)


@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Show a friendly HTML page for 403 Forbidden errors."""
    if exc.status_code == 403:
        return templates.TemplateResponse(
            request,
            "403.html",
            {"detail": exc.detail},
            status_code=403,
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
