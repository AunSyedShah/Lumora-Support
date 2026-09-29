import re

from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from ninja import Router
from ninja.errors import HttpError

from .auth import ACCESS, REFRESH, create_token, get_user_from_token, require_role
from .models import User
from .schemas import (
    ErrorOut,
    LoginIn,
    RefreshIn,
    RegisterIn,
    TokenOut,
    UserCreateIn,
    UserOut,
)

router = Router(tags=["Auth & Users"])


def _username_from(email):
    """"sara.malik@example.com" -> "sara.malik" (or "sara.malik2", ... if that is taken)."""
    base = re.sub(r"[^a-z0-9._-]", "", email.split("@")[0].lower())[:140] or "customer"
    base = base if len(base) >= 3 else f"{base}user"
    name, n = base, 1
    while User.objects.filter(username=name).exists():
        n += 1
        name = f"{base}{n}"
    return name


def _create_user(data: RegisterIn, role):
    """Shared by public registration and admin user creation."""
    if data.username and User.objects.filter(username=data.username).exists():
        raise HttpError(409, "Username is already taken.")
    if User.objects.filter(email__iexact=data.email).exists():
        raise HttpError(409, "An account with this email already exists. Sign in instead.")
    try:
        validate_password(data.password)
    except ValidationError as e:
        raise HttpError(400, " ".join(e.messages))

    return User.objects.create_user(
        username=data.username or _username_from(data.email),
        email=data.email,
        password=data.password,
        first_name=data.first_name,
        last_name=data.last_name,
        phone=data.phone,
        # only staff choose premium / business; self-registration is always a standard customer
        customer_type=getattr(data, "customer_type", User.CustomerType.STANDARD),
        role=role,
    )


def _tokens_for(user):
    return {"access": create_token(user, ACCESS), "refresh": create_token(user, REFRESH)}


@router.post("/register", auth=None, response={201: UserOut, 400: ErrorOut, 409: ErrorOut})
def register(request, data: RegisterIn):
    return 201, _create_user(data, User.Role.CUSTOMER)


@router.post("/login", auth=None, response={200: TokenOut, 401: ErrorOut})
def login(request, data: LoginIn):
    username = data.username.strip()
    if "@" in username:  # signing in with the email address
        account = User.objects.filter(email__iexact=username).first()
        username = account.username if account else username
    user = authenticate(username=username, password=data.password)
    if user is None:
        raise HttpError(401, "Invalid username or password.")
    return _tokens_for(user)


@router.post("/refresh", auth=None, response={200: TokenOut, 401: ErrorOut})
def refresh(request, data: RefreshIn):
    user = get_user_from_token(data.refresh, REFRESH)
    if user is None:
        raise HttpError(401, "Invalid or expired refresh token.")
    return _tokens_for(user)


@router.get("/me", response=UserOut)
def me(request):
    return request.auth


@router.get("/users", response=list[UserOut])
def list_users(request, role: User.Role | None = None):
    require_role(request, User.Role.ADMIN, User.Role.MANAGER)
    users = User.objects.order_by("id")
    if role:
        users = users.filter(role=role)
    return users


@router.post("/users", response={201: UserOut, 400: ErrorOut, 409: ErrorOut})
def create_user(request, data: UserCreateIn):
    require_role(request, User.Role.ADMIN)
    return 201, _create_user(data, data.role)
