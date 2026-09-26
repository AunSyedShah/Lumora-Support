from ninja import ModelSchema, Schema
from pydantic import EmailStr, Field

from .models import User


class RegisterIn(Schema):
    """Public self-registration. Always creates a customer account."""

    username: str = Field(min_length=3, max_length=150)
    email: EmailStr
    password: str = Field(min_length=8)
    first_name: str = ""
    last_name: str = ""
    phone: str = ""
    customer_type: User.CustomerType = User.CustomerType.STANDARD


class UserCreateIn(RegisterIn):
    """Used by administrators to create staff accounts (agents, reviewers, ...)."""

    role: User.Role = User.Role.AGENT


class LoginIn(Schema):
    username: str
    password: str


class RefreshIn(Schema):
    refresh: str


class TokenOut(Schema):
    access: str
    refresh: str
    token_type: str = "Bearer"


class UserOut(ModelSchema):
    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "phone",
            "role",
            "customer_type",
            "date_joined",
        ]


class ErrorOut(Schema):
    detail: str
