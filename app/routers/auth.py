from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.config import settings
from app.database import get_session
from app.deps import get_current_user
from app.models.users import Role, User
from app.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

router = APIRouter()

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Map each role to its dashboard URL
ROLE_HOME = {
    Role.MANAGEMENT: "/management",
    Role.HOD: "/hod",
    Role.MENTOR: "/mentor",
    Role.TRAINER: "/trainer",
    Role.STUDENT: "/student",
    Role.ADMIN: "/admin/",
}


def _home_for(user: User) -> str:
    """Where a signed-in user should land."""
    if user.must_change_password:
        return "/change-password"
    return ROLE_HOME.get(user.role, "/login")


@router.get("/login")
def login_page(request: Request, session: Session = Depends(get_session)):
    """Render the login page, or send an already signed-in user to their dashboard."""
    payload = decode_access_token(request.cookies.get("access_token") or "")
    if payload and str(payload.get("sub", "")).isdigit():
        user = session.get(User, int(payload["sub"]))
        if user and user.is_active:
            return RedirectResponse(url=_home_for(user), status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": None, "username": ""},
    )


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_session),
):
    """Verify credentials, set the HTTP-only JWT cookie, and redirect by role."""
    clean_username = username.strip()
    user = session.exec(
        select(User).where(User.username == clean_username)
    ).first()

    if not user or not user.is_active or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Wrong username or password", "username": clean_username},
            status_code=400,
        )

    # The admin panel has its own sign-in; admin accounts do not use the portal
    if user.role == Role.ADMIN:
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "error": "Admin accounts sign in at the admin panel: /admin",
                "username": clean_username,
            },
            status_code=400,
        )

    token = create_access_token(user_id=user.id, role=user.role.value)
    target_url = _home_for(user)

    response = RedirectResponse(url=target_url, status_code=303)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=settings.ACCESS_TOKEN_MINUTES * 60,
    )
    return response


@router.get("/change-password")
def change_password_page(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Render the force/voluntary password change form."""
    return templates.TemplateResponse(
        request,
        "change_password.html",
        {
            "error": None,
            "current_user": current_user,
            "home_url": ROLE_HOME.get(current_user.role, "/login"),
        },
    )


@router.post("/change-password")
def change_password_submit(
    request: Request,
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    current_password: str = Form(""),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Validate and save the new password, then clear must_change_password."""

    def form_error(message: str):
        return templates.TemplateResponse(
            request,
            "change_password.html",
            {
                "error": message,
                "current_user": current_user,
                "home_url": ROLE_HOME.get(current_user.role, "/login"),
            },
            status_code=400,
        )

    # A voluntary change must prove the user knows the current password
    if not current_user.must_change_password and not verify_password(
        current_password, current_user.password_hash
    ):
        return form_error("Current password is incorrect.")

    if verify_password(new_password, current_user.password_hash):
        return form_error("New password must be different from your current password.")

    if len(new_password) < 8:
        return form_error("Password must be at least 8 characters long.")

    if new_password != confirm_password:
        return form_error("Passwords do not match.")

    current_user.password_hash = hash_password(new_password)
    current_user.must_change_password = False
    session.add(current_user)
    session.commit()

    target_url = ROLE_HOME.get(current_user.role, "/")
    return RedirectResponse(url=target_url, status_code=303)


@router.get("/logout")
def logout():
    """Clear the access_token cookie and redirect to the login page."""
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(key="access_token")
    return response
