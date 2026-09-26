"""JWT helpers and the Ninja auth class used by every protected endpoint."""

from datetime import datetime, timedelta, timezone

import jwt
from django.conf import settings
from ninja.errors import HttpError
from ninja.security import HttpBearer

from .models import User

ACCESS = "access"
REFRESH = "refresh"


def create_token(user, token_type):
    """Build a signed JWT for the user. Access tokens are short-lived, refresh tokens longer."""
    now = datetime.now(timezone.utc)
    if token_type == ACCESS:
        expires = now + timedelta(minutes=settings.JWT_ACCESS_TOKEN_MINUTES)
    else:
        expires = now + timedelta(days=settings.JWT_REFRESH_TOKEN_DAYS)

    payload = {
        "sub": str(user.id),  # PyJWT requires "sub" to be a string
        "role": user.role,
        "type": token_type,
        "iat": now,
        "exp": expires,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def get_user_from_token(token, expected_type):
    """Return the active user for a valid token of the expected type, otherwise None."""
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except jwt.PyJWTError:  # bad signature, expired, malformed...
        return None

    if payload.get("type") != expected_type:
        return None
    return User.objects.filter(id=payload["sub"], is_active=True).first()


class JWTAuth(HttpBearer):
    """Reads 'Authorization: Bearer <token>'. The returned user becomes request.auth."""

    def authenticate(self, request, token):
        return get_user_from_token(token, ACCESS)


STAFF_ROLES = (User.Role.AGENT, User.Role.REVIEWER, User.Role.MANAGER, User.Role.ADMIN)


def require_role(request, *roles):
    """Raise 403 unless the logged-in user has one of the given roles (superusers always pass)."""
    user = request.auth
    if user.is_superuser or user.role in roles:
        return
    raise HttpError(403, "You do not have permission to perform this action.")
