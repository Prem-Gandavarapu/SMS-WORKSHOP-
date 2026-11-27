from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlmodel import Session, select

from app.database import get_session
from app.deps import require_role
from app.models.registration import Registration, RegistrationStatus
from app.models.users import Role, User
from app.navigation import UPCOMING_FEATURES, build_nav, role_upcoming_slugs

router = APIRouter(tags=["coming-soon"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

DASHBOARD_URLS = {
    Role.MANAGEMENT: "/management",
    Role.HOD: "/hod",
    Role.MENTOR: "/mentor",
    Role.TRAINER: "/trainer",
    Role.STUDENT: "/student",
}


@router.get("/coming-soon/{slug}")
def coming_soon(
    slug: str,
    request: Request,
    current_user: User = Depends(require_role(*Role)),
    session: Session = Depends(get_session),
):
    """Placeholder page for a feature in the user's menu that is still being built."""
    if slug not in role_upcoming_slugs(current_user.role):
        raise HTTPException(status_code=404, detail="Page not found")

    pending_count = None
    if current_user.role == Role.HOD and current_user.department_id:
        pending_count = session.exec(
            select(func.count(Registration.id)).where(
                Registration.department_id == current_user.department_id,
                Registration.status == RegistrationStatus.PENDING,
            )
        ).one()

    feature = UPCOMING_FEATURES[slug]
    return templates.TemplateResponse(
        request,
        "coming_soon.html",
        {
            "current_user": current_user,
            "page_title": feature["label"],
            "nav_links": build_nav(current_user.role, slug, pending_count),
            "feature": feature,
            "dashboard_url": DASHBOARD_URLS.get(current_user.role, "/login"),
        },
    )
