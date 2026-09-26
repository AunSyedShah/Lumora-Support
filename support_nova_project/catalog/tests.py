from django.core.management import call_command
from django.test import TestCase

from accounts.auth import ACCESS, create_token
from accounts.models import User

from .models import Category, Department, Subcategory


class CatalogApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_catalog", verbosity=0)
        cls.admin = User.objects.create_user("admin1", password="x", role=User.Role.ADMIN)
        cls.agent = User.objects.create_user("agent1", password="x", role=User.Role.AGENT)

    def headers(self, user):
        return {"HTTP_AUTHORIZATION": f"Bearer {create_token(user, ACCESS)}"}

    def post(self, url, body, user):
        return self.client.post(url, body, content_type="application/json", **self.headers(user))

    def patch(self, url, body, user):
        return self.client.patch(url, body, content_type="application/json", **self.headers(user))

    def test_seed_meets_srs_minimums(self):
        self.assertGreaterEqual(Department.objects.count(), 8)
        self.assertGreaterEqual(Category.objects.count(), 10)
        self.assertGreaterEqual(Subcategory.objects.count(), 20)

    def test_subcategory_department_override(self):
        doa = Subcategory.objects.get(code="DEAD_ON_ARRIVAL")
        self.assertEqual(doa.routed_department.code, "RETURNS")  # override
        malfunction = Subcategory.objects.get(code="HARDWARE_MALFUNCTION")
        self.assertEqual(malfunction.routed_department.code, "WARRANTY")  # category default

    def test_read_requires_login(self):
        self.assertEqual(self.client.get("/api/catalog/categories").status_code, 401)

    def test_agent_can_read_but_not_write(self):
        self.assertEqual(self.client.get("/api/catalog/categories", **self.headers(self.agent)).status_code, 200)
        res = self.post("/api/catalog/departments", {"code": "NEW_DEPT", "name": "New"}, self.agent)
        self.assertEqual(res.status_code, 403)

    def test_live_modification_add_category_and_subcategory(self):
        """SRS 1.8.14: a new category must work through configuration, not code."""
        res = self.post("/api/catalog/departments", {"code": "ENERGY", "name": "Energy Advisory"}, self.admin)
        self.assertEqual(res.status_code, 201)
        res = self.post(
            "/api/catalog/categories",
            {"code": "ENERGY_BILLS", "name": "Energy Usage", "default_department": "ENERGY"},
            self.admin,
        )
        self.assertEqual(res.status_code, 201)
        res = self.post(
            "/api/catalog/subcategories",
            {"code": "WRONG_USAGE_READING", "name": "Wrong Usage Reading", "category": "ENERGY_BILLS"},
            self.admin,
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.json()["routed_department"], "ENERGY")

        taxonomy = self.client.get("/api/catalog/taxonomy", **self.headers(self.agent)).json()
        self.assertIn("ENERGY_BILLS", [c["code"] for c in taxonomy["categories"]])

    def test_duplicate_code_is_409(self):
        res = self.post("/api/catalog/departments", {"code": "BILLING", "name": "Dup"}, self.admin)
        self.assertEqual(res.status_code, 409)

    def test_invalid_code_format_is_422(self):
        res = self.post("/api/catalog/departments", {"code": "lower case", "name": "Bad"}, self.admin)
        self.assertEqual(res.status_code, 422)

    def test_unknown_department_reference_is_404(self):
        res = self.post(
            "/api/catalog/categories", {"code": "X_CAT", "name": "X Category", "default_department": "NOPE"}, self.admin
        )
        self.assertEqual(res.status_code, 404)

    def test_cannot_delete_department_in_use(self):
        res = self.client.delete("/api/catalog/departments/BILLING", **self.headers(self.admin))
        self.assertEqual(res.status_code, 409)

    def test_deactivated_category_hidden_from_taxonomy(self):
        self.patch("/api/catalog/categories/INSTALLATION", {"is_active": False}, self.admin)
        taxonomy = self.client.get("/api/catalog/taxonomy", **self.headers(self.agent)).json()
        self.assertNotIn("INSTALLATION", [c["code"] for c in taxonomy["categories"]])

    def test_modify_sla(self):
        res = self.patch("/api/catalog/sla-rules/P1", {"resolution_hours": 36}, self.admin)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["resolution_hours"], 36)

    def test_overlap_settings_via_api(self):
        res = self.patch("/api/catalog/subcategories/LOST_PARCEL", {"takes_precedence_over": ["delayed_delivery"]},
                         self.admin)
        self.assertEqual(res.json()["takes_precedence_over"], ["DELAYED_DELIVERY"])
        fallback = self.client.get("/api/catalog/subcategories/UNRESOLVED_PREVIOUS", **self.headers(self.agent)).json()
        self.assertTrue(fallback["is_fallback"])

    def test_clear_subcategory_department_override(self):
        res = self.patch("/api/catalog/subcategories/DEAD_ON_ARRIVAL", {"department": None}, self.admin)
        self.assertEqual(res.json()["department"], None)
        self.assertEqual(res.json()["routed_department"], "WARRANTY")
