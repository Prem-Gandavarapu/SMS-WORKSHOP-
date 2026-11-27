from fastapi import Depends, HTTPException, Request
from sqlmodel import Session

from app.database import get_session
from app.models.users import Role, User
from app.security import decode_access_token


def get_current_user(
    request: Request,
    session: Session = Depends(get_session),
) -> User:
    """Read the access_token cookie, verify it, and return the active User."""
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=303, headers={"Location": "/login"})

    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=303, headers={"Location": "/login"})

    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError):
        raise HTTPException(status_code=303, headers={"Location": "/login"})

    user = session.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=303, headers={"Location": "/login"})

    return user


def require_role(*roles: Role):
    """Dependency factory that restricts a route to specific user roles."""

    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        # Accounts with a temporary password must set a new one before using the app
        if current_user.must_change_password:
            raise HTTPException(status_code=303, headers={"Location": "/change-password"})
        if current_user.role not in roles:
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to access this page.",
            )
        return current_user

    return role_checker
