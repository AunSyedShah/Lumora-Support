"""
Dashboards, analytics, trends, reports and export. Complaints are created directly with a known
working state (no GenAI involved) so every expected number can be written down exactly.
"""

import io
from datetime import timedelta

import openpyxl
import pymupdf
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from accounts.auth import ACCESS, create_token
from accounts.models import User
from catalog.models import Category, Department, Product, Subcategory
from complaints.models import Complaint
from workflow.lifecycle import set_sla_due_dates

from .analytics import detect_trends
from .data import complaint_frame

NOW = timezone.now()


class ReportTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_catalog", verbosity=0)
        cls.customer = User.objects.create_user("alice", password="x")
        cls.reviewer = User.objects.create_user("rev", password="x", role=User.Role.REVIEWER)
        cls.agent = User.objects.create_user("agent_log", password="x", role=User.Role.AGENT,
                                             department=Department.objects.get(code="LOGISTICS"))
        cls.n = 0

    @classmethod
    def make(cls, sub="DELAYED_DELIVERY", days_ago=1, priority="P2", status="assigned", escalation="none",
             sentiment="Negative", product="PLUG", assigned=None, resolved_hours=None, match_type="", **extra):
        cls.n += 1
        subcategory = Subcategory.objects.select_related("category").get(code=sub)
        c = Complaint.objects.create(
            customer=cls.customer, title=f"c{cls.n}", description="d", customer_type="standard",
            normalized_text=f"t{cls.n}", text_hash=f"h{cls.n}", category=subcategory.category, subcategory=subcategory,
            department=subcategory.routed_department, product=Product.objects.get(code=product), priority=priority,
            urgency="Medium", sentiment=sentiment, escalation_level=escalation, status=status, assigned_to=assigned,
            verification_status="verified", verification_score=90, match_type=match_type,
            resolution={"policy_references": ["DEL-POL 2.1"], "resolution_rule": "RR-001"}, **extra,
        )
        created = NOW - timedelta(days=days_ago)
        Complaint.objects.filter(pk=c.pk).update(created_at=created)
        c.refresh_from_db()
        if resolved_hours is not None:
            c.resolved_at = created + timedelta(hours=resolved_hours)
        set_sla_due_dates(c)
        c.save()
        return c

    def headers(self, user):
        return {"HTTP_AUTHORIZATION": f"Bearer {create_token(user, ACCESS)}"}

    def get(self, url, user=None, **params):
        return self.client.get(url, params, **self.headers(user or self.reviewer))


class AnalyticsTests(ReportTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.make("DELAYED_DELIVERY", priority="P2", status="resolved", resolved_hours=10)
        cls.make("DELAYED_DELIVERY", priority="P2", status="resolved", resolved_hours=30)
        cls.make("OVERHEATING", priority="P0", status="escalated", escalation="specialist_team", sentiment="Neutral")
        cls.make("DUPLICATE_CHARGE", priority="P3", status="in_progress", match_type="repeat")

    def test_analytics_numbers(self):
        a = self.get("/api/analytics").json()
        self.assertEqual((a["total"], a["open"], a["resolved_or_closed"]), (4, 2, 2))
        self.assertEqual(a["by_category"][0], {"value": "DELIVERY", "count": 2, "percent": 50.0})
        self.assertEqual(a["escalations"]["total"], 1)
        self.assertEqual((a["resolution_time"]["resolved"], a["resolution_time"]["median_hours"]), (2, 20.0))
        self.assertEqual(a["repeat_complaints"]["count"], 1)

    def test_filters(self):
        a = self.get("/api/analytics", category="SAFETY").json()
        self.assertEqual(a["total"], 1)
        a = self.get("/api/analytics", date_from=str((NOW - timedelta(days=30)).date()), priority="P2").json()
        self.assertEqual(a["total"], 2)

    def test_admin_dashboard(self):
        d = self.get("/api/dashboard/admin").json()
        self.assertEqual(d["total_complaints"], 4)
        self.assertEqual(d["escalations"]["total"], 1)
        self.assertIn("genai_python_mismatches", d)
        self.assertIn("manual_review", d)

    def test_agent_cannot_see_organisation_wide_data(self):
        for url in ("/api/dashboard/admin", "/api/analytics", "/api/analytics/trends", "/api/reports",
                    "/api/reports/complaint_analysis"):
            self.assertEqual(self.get(url, self.agent).status_code, 403, url)
        self.assertEqual(self.get("/api/dashboard/admin", self.customer).status_code, 403)


class AgentDashboardTests(ReportTestBase):
    def test_agent_sees_only_own_open_assignments(self):
        mine = self.make(assigned=self.agent, escalation="supervisor", status="escalated")
        self.make(assigned=self.agent, status="resolved", resolved_hours=5)
        self.make(assigned=None)  # someone else's / unassigned
        d = self.get("/api/dashboard/agent", self.agent).json()
        self.assertEqual([c["complaint_id"] for c in d["complaints"]], [mine.complaint_id])
        self.assertEqual((d["open_assigned"], d["escalated"], d["resolved_total"]), (1, 1, 1))
        item = d["complaints"][0]
        for key in ("genai_recommendation", "validation", "suggested_response", "escalation_warning", "sla"):
            self.assertIn(key, item)


class TrendTests(ReportTestBase):
    def test_rising_category(self):
        for _ in range(4):
            self.make("DELAYED_DELIVERY", days_ago=2)
        self.make("DELAYED_DELIVERY", days_ago=10)
        self.make("DUPLICATE_CHARGE", days_ago=2)
        trends = detect_trends(complaint_frame(Complaint.objects.all()), now=NOW)
        rising = {(t["dimension"], t["value"]): t for t in trends["rising"]}
        self.assertEqual(rising[("category", "DELIVERY")]["current"], 4)
        self.assertEqual(rising[("category", "DELIVERY")]["change_percent"], 300.0)
        self.assertNotIn(("category", "BILLING"), rising)  # 1 complaint is below min_count

    def test_recurring_product_issue_and_repeated_failures(self):
        for _ in range(3):
            self.make("HARDWARE_MALFUNCTION", product="LOCK", days_ago=5, match_type="repeat")
        trends = detect_trends(complaint_frame(Complaint.objects.all()), now=NOW)
        self.assertEqual(trends["recurring_product_issues"][0]["product"], "Smart Lock")
        self.assertEqual(trends["repeated_service_failures"][0]["subcategory"], "HARDWARE_MALFUNCTION")

    def test_escalation_spike(self):
        for day in range(10, 25):  # one escalation a day on most days
            if day % 2:
                self.make("OVERHEATING", days_ago=day, escalation="specialist_team")
        for _ in range(5):  # then 5 in one day
            self.make("OVERHEATING", days_ago=1, escalation="specialist_team")
        spikes = detect_trends(complaint_frame(Complaint.objects.all()), now=NOW)["escalation_spikes"]
        self.assertEqual([s["escalations"] for s in spikes], [5])

    def test_trend_endpoint_parameters(self):
        for _ in range(2):
            self.make("DELAYED_DELIVERY", days_ago=1)
        self.assertEqual(self.get("/api/analytics/trends").json()["rising"], [])  # 2 < min_count 3
        rising = self.get("/api/analytics/trends", min_count=2).json()["rising"]
        self.assertIn("DELIVERY", [t["value"] for t in rising])


class ReportExportTests(ReportTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.make("DELAYED_DELIVERY", status="resolved", resolved_hours=12)
        cls.make("OVERHEATING", priority="P0", status="escalated", escalation="specialist_team")

    def test_every_report_in_every_format(self):
        names = [r["name"] for r in self.get("/api/reports").json()]
        self.assertEqual(len(names), 9)
        for name in names:
            data = self.get(f"/api/reports/{name}").json()
            self.assertIn("rows", data, name)
            csv = self.get(f"/api/reports/{name}", format="csv")
            self.assertTrue(csv["Content-Disposition"].endswith(f'.csv"'), name)
            self.assertIn(data["columns"][0], csv.content.decode("utf-8-sig").splitlines()[0])
            xlsx = self.get(f"/api/reports/{name}", format="xlsx")
            workbook = openpyxl.load_workbook(io.BytesIO(xlsx.content))
            self.assertEqual(workbook.sheetnames, ["Report", "Summary"])
            pdf = self.get(f"/api/reports/{name}", format="pdf")
            self.assertGreaterEqual(pymupdf.open(stream=pdf.content, filetype="pdf").page_count, 1)

    def test_report_content(self):
        rows = self.get("/api/reports/escalations").json()["rows"]
        self.assertEqual([r["escalation_level"] for r in rows], ["specialist_team"])
        usage = self.get("/api/reports/policy_usage").json()
        self.assertEqual(usage["rows"][0], {"policy_reference": "DEL-POL 2.1", "policy_id": "DEL-POL", "times_cited": 2})
        departments = {r["department"] for r in self.get("/api/reports/department_performance").json()["rows"]}
        self.assertEqual(departments, {"LOGISTICS", "PRODUCT_SAFETY"})

    def test_wide_report_pdf_lists_hidden_columns(self):
        pdf = self.get("/api/reports/complaint_analysis", format="pdf")
        text = pymupdf.open(stream=pdf.content, filetype="pdf")[0].get_text()
        self.assertIn("Columns not shown here", text)

    def test_bad_requests(self):
        self.assertEqual(self.get("/api/reports/nope").status_code, 404)
        self.assertEqual(self.get("/api/reports/escalations", format="docx").status_code, 400)
