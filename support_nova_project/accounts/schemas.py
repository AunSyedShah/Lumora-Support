from ninja import ModelSchema, Schema
from pydantic import EmailStr, Field

from .models import User


class RegisterIn(Schema):
    """Public self-registration. Always creates a standard customer account (premium/business is set by staff)."""

    username: str | None = Field(None, min_length=3, max_length=150, description="Optional: made from the email if left out")
    email: EmailStr
    password: str = Field(min_length=8)
    first_name: str = ""
    last_name: str = ""
    phone: str = ""


class UserCreateIn(RegisterIn):
    """Used by administrators to create accounts (agents, reviewers, ... or customers with a type)."""

    role: User.Role = User.Role.AGENT
    customer_type: User.CustomerType = User.CustomerType.STANDARD


class LoginIn(Schema):
    username: str = Field(description="Username or email address")
    password: str


class RefreshIn(Schema):
    refresh: str


class TokenOut(Schema):
    access: str
    refresh: str
    token_type: str = "Bearer"


class UserOut(ModelSchema):
    department: str | None = Field(None, alias="department.code")  # staff: the team they work in

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
