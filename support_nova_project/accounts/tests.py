from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase

from .auth import ACCESS, REFRESH, create_token
from .models import User


class AuthApiTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("admin1", password="Str0ng!Pass", role=User.Role.ADMIN)
        self.customer = User.objects.create_user("cust1", password="Str0ng!Pass")

    def auth_header(self, user):
        return {"HTTP_AUTHORIZATION": f"Bearer {create_token(user, ACCESS)}"}

    def test_register_always_creates_customer(self):
        res = self.client.post(
            "/api/auth/register",
            {"username": "newbie", "email": "n@example.com", "password": "Str0ng!Pass", "role": "admin"},
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.json()["role"], "customer")  # "role" in the body is ignored

    def test_register_is_always_standard_and_username_is_optional(self):
        res = self.client.post(
            "/api/auth/register",
            {"email": "Sara.Malik@example.com", "password": "Str0ng!Pass", "customer_type": "premium"},
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual((res.json()["username"], res.json()["customer_type"]), ("sara.malik", "standard"))
        again = self.client.post(
            "/api/auth/register", {"email": "sara.malik@EXAMPLE.com", "password": "Str0ng!Pass"},
            content_type="application/json",
        )
        self.assertEqual(again.status_code, 409)  # one account per email address

    def test_login_with_email(self):
        self.customer.email = "cust1@example.com"
        self.customer.save()
        res = self.client.post(
            "/api/auth/login", {"username": "CUST1@example.com", "password": "Str0ng!Pass"}, content_type="application/json"
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("access", res.json())

    def test_register_rejects_weak_password(self):
        res = self.client.post(
            "/api/auth/register",
            {"username": "weak", "email": "w@example.com", "password": "12345678"},
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 400)

    def test_register_duplicate_username(self):
        res = self.client.post(
            "/api/auth/register",
            {"username": "cust1", "email": "c@example.com", "password": "Str0ng!Pass"},
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 409)

    def test_login_and_me(self):
        res = self.client.post(
            "/api/auth/login", {"username": "cust1", "password": "Str0ng!Pass"}, content_type="application/json"
        )
        self.assertEqual(res.status_code, 200)
        access = res.json()["access"]
        me = self.client.get("/api/auth/me", HTTP_AUTHORIZATION=f"Bearer {access}")
        self.assertEqual(me.json()["username"], "cust1")

    def test_login_wrong_password(self):
        res = self.client.post(
            "/api/auth/login", {"username": "cust1", "password": "nope"}, content_type="application/json"
        )
        self.assertEqual(res.status_code, 401)

    def test_missing_or_bad_token_is_401(self):
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        res = self.client.get("/api/auth/me", HTTP_AUTHORIZATION="Bearer not-a-jwt")
        self.assertEqual(res.status_code, 401)

    def test_refresh_token_cannot_be_used_as_access_token(self):
        refresh = create_token(self.customer, REFRESH)
        res = self.client.get("/api/auth/me", HTTP_AUTHORIZATION=f"Bearer {refresh}")
        self.assertEqual(res.status_code, 401)

    def test_refresh_returns_new_tokens(self):
        refresh = create_token(self.customer, REFRESH)
        res = self.client.post("/api/auth/refresh", {"refresh": refresh}, content_type="application/json")
        self.assertEqual(res.status_code, 200)
        self.assertIn("access", res.json())

    def test_expired_token_is_rejected(self):
        with self.settings(JWT_ACCESS_TOKEN_MINUTES=-1):
            expired = create_token(self.customer, ACCESS)
        res = self.client.get("/api/auth/me", HTTP_AUTHORIZATION=f"Bearer {expired}")
        self.assertEqual(res.status_code, 401)

    def test_deactivated_user_token_is_rejected(self):
        headers = self.auth_header(self.customer)
        self.customer.is_active = False
        self.customer.save()
        self.assertEqual(self.client.get("/api/auth/me", **headers).status_code, 401)

    def test_only_admin_can_create_staff(self):
        body = {"username": "agent1", "email": "a@example.com", "password": "Str0ng!Pass", "role": "agent"}
        res = self.client.post("/api/auth/users", body, content_type="application/json", **self.auth_header(self.customer))
        self.assertEqual(res.status_code, 403)
        res = self.client.post("/api/auth/users", body, content_type="application/json", **self.auth_header(self.admin))
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.json()["role"], "agent")
