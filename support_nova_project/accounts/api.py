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


def _create_user(data: RegisterIn, role):
    """Shared by public registration and admin user creation."""
    if User.objects.filter(username=data.username).exists():
        raise HttpError(409, "Username is already taken.")
    try:
        validate_password(data.password)
    except ValidationError as e:
        raise HttpError(400, " ".join(e.messages))

    return User.objects.create_user(
        username=data.username,
        email=data.email,
        password=data.password,
        first_name=data.first_name,
        last_name=data.last_name,
        phone=data.phone,
        customer_type=data.customer_type,
        role=role,
    )


def _tokens_for(user):
    return {"access": create_token(user, ACCESS), "refresh": create_token(user, REFRESH)}


@router.post("/register", auth=None, response={201: UserOut, 400: ErrorOut, 409: ErrorOut})
def register(request, data: RegisterIn):
    return 201, _create_user(data, User.Role.CUSTOMER)


@router.post("/login", auth=None, response={200: TokenOut, 401: ErrorOut})
def login(request, data: LoginIn):
    user = authenticate(username=data.username, password=data.password)
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
