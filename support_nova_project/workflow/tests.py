import json
import shutil
import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.auth import ACCESS, create_token
from accounts.models import User
from catalog.models import Department
from complaints.models import Complaint
from complaints.services import submit_complaint
from genai_pipeline.client import LLMResult
from genai_pipeline.models import GenAIAnalysis, PromptTemplate
from knowledge_base.services import ingest_document
from python_validation.services import validate_analysis
from python_validation.tests import GOOD_OUTPUT, NOTES, output

from .lifecycle import TransitionError, apply_status, set_sla_due_dates, sla_status
from .services import apply_validation

S = Complaint.Status


class LifecycleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_catalog", verbosity=0)
        cls.customer = User.objects.create_user("alice", password="x")

    def make(self, priority="P2"):
        c = Complaint.objects.create(customer=self.customer, title="t", description="d", customer_type="standard",
                                     normalized_text="t", text_hash="h", priority=priority)
        set_sla_due_dates(c)
        return c

    def test_invalid_transition_refused(self):
        c = self.make()
        with self.assertRaises(TransitionError):
            apply_status(c, S.REOPENED)  # new -> reopened is not allowed
        apply_status(c, S.ANALYZED)
        apply_status(c, S.RESOLVED)
        self.assertIsNotNone(c.resolved_at)

    def test_sla_due_dates_follow_priority(self):
        c = self.make("P0")  # 1h response, 24h resolution
        self.assertEqual(c.sla_resolution_due - c.created_at, timedelta(hours=24))
        c.priority = "P3"
        set_sla_due_dates(c)
        self.assertEqual(c.sla_resolution_due - c.created_at, timedelta(hours=120))

    def test_sla_states(self):
        c = self.make("P2")  # 72h resolution, at risk after 75%
        start = c.created_at
        self.assertEqual(sla_status(c, start + timedelta(hours=10))["resolution"], "on_track")
        self.assertEqual(sla_status(c, start + timedelta(hours=60))["resolution"], "at_risk")
        self.assertEqual(sla_status(c, start + timedelta(hours=80))["resolution"], "breached")
        self.assertEqual(sla_status(c, start + timedelta(hours=10))["response"], "breached")  # 8h, no reply yet

    def test_waiting_for_customer_pauses_the_sla(self):
        c = self.make("P2")
        due = c.sla_resolution_due
        apply_status(c, S.ANALYZED)
        now = timezone.now()
        apply_status(c, S.AWAITING_CUSTOMER, now=now)
        apply_status(c, S.IN_PROGRESS, now=now + timedelta(hours=5))
        self.assertEqual(c.sla_resolution_due - due, timedelta(hours=5))


@override_settings(GENAI_RETRY_BACKOFF_SECONDS=0)
class WorkflowBase(TestCase):
    counter = 0
    """Shared set-up and helpers (no tests of its own). Each subclass gets its own media folder."""

    @classmethod
    def setUpClass(cls):
        cls.media_dir = tempfile.mkdtemp()
        cls.media_override = override_settings(MEDIA_ROOT=cls.media_dir)
        cls.media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.media_override.disable()
        shutil.rmtree(cls.media_dir, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        call_command("seed_catalog", verbosity=0)
        call_command("load_rules", verbosity=0)
        call_command("load_prompts", verbosity=0)
        samples = settings.BASE_DIR / "sample_documents"
        for name in ("delivery_policy.docx", "safety_policy.pdf"):
            ingest_document(name, (samples / name).read_bytes(), {}, None)
        cls.alice = User.objects.create_user("alice", password="x")
        cls.bob = User.objects.create_user("bob", password="x")
        cls.reviewer = User.objects.create_user("rev", password="x", role=User.Role.REVIEWER)
        cls.logistics_agent = User.objects.create_user(
            "agent_log", password="x", role=User.Role.AGENT, department=Department.objects.get(code="LOGISTICS"))
        cls.safety_agent = User.objects.create_user(
            "agent_safe", password="x", role=User.Role.AGENT, department=Department.objects.get(code="PRODUCT_SAFETY"))
        cls.prompt = PromptTemplate.objects.get(is_active=True)

    def headers(self, user):
        return {"HTTP_AUTHORIZATION": f"Bearer {create_token(user, ACCESS)}"}

    def post(self, url, body, user):
        return self.client.post(f"/api/workflow{url}", body, content_type="application/json", **self.headers(user))

    def processed(self, out=None, text="My order is delayed and has not arrived yet, please help.", customer=None):
        """Submit a complaint and run Pipeline 2 + workflow on a hand-written GenAI output."""
        WorkflowBase.counter += 1
        complaint, _ = submit_complaint({"title": f"Complaint {WorkflowBase.counter}", "description": text},
                                        customer or self.alice, customer or self.alice)
        analysis = GenAIAnalysis.objects.create(complaint=complaint, prompt_template=self.prompt, provider="deepseek",
                                                model="test", status="success", output=out or GOOD_OUTPUT,
                                                policy_versions={"DEL-POL": "1.0"})
        apply_validation(complaint, validate_analysis(analysis))
        complaint.refresh_from_db()
        return complaint

    def needs_review(self):
        """A complaint that validation sends to manual review (disallowed compensation)."""
        return self.processed(output(compensation={"type": "full_refund", "justification": "x", "policy_id": None, "section": None}))


class WorkflowTests(WorkflowBase):
    # ---- routing after processing ----

    def test_verified_complaint_is_auto_assigned(self):
        c = self.processed()
        self.assertEqual((c.verification_status, c.status), ("verified", S.ASSIGNED))
        self.assertEqual(c.assigned_to, self.logistics_agent)
        self.assertEqual((c.priority, c.department.code), ("P2", "LOGISTICS"))
        self.assertIsNotNone(c.sla_resolution_due)
        self.assertIsNotNone(c.follow_up_due)

    def test_manual_review_goes_to_queue_not_to_an_agent(self):
        c = self.needs_review()
        self.assertEqual((c.review_status, c.status, c.assigned_to), ("pending", S.ANALYZED, None))
        queue = self.client.get("/api/workflow/review-queue", **self.headers(self.reviewer)).json()
        self.assertIn(c.complaint_id, [i["complaint_id"] for i in queue])
        self.assertTrue(queue[0]["review_reasons"])

    def test_escalation_sets_status(self):
        safety = output(primary_issue={"category": "SAFETY", "subcategory": "OVERHEATING", "description": "x"},
                        department="PRODUCT_SAFETY", urgency="Critical", priority="P0", escalation_required=True,
                        escalation_level="specialist_team", escalation_notes=NOTES,
                        policy_references=[{"policy_id": "SAF-POL", "section": "2.1", "chunk_id": None, "relevance": "x"}])
        c = self.processed(safety, text="My plug smells like burning plastic.")
        self.assertEqual((c.status, c.assigned_to), (S.ESCALATED, self.safety_agent))

    def test_escalated_complaint_gets_owner_even_while_under_review(self):
        # The GenAI missed the safety issue -> critical finding -> manual review, but escalation is enforced
        # and the Product Safety agent owns it at once.
        c = self.processed(text="Order is late. Also the old hub was sparking when I unplugged it.")
        self.assertEqual((c.review_status, c.status), ("pending", S.ESCALATED))
        self.assertEqual(c.assigned_to, self.safety_agent)

    # ---- reviewer actions ----

    def test_approve_and_audit_trail_keeps_original(self):
        c = self.needs_review()
        self.assertEqual(self.post(f"/complaints/{c.complaint_id}/approve", {}, self.logistics_agent).status_code, 403)
        res = self.post(f"/complaints/{c.complaint_id}/approve", {"comment": "Checked, fine"}, self.reviewer)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual((res.json()["review_status"], res.json()["status"]), ("approved", "assigned"))
        self.assertEqual(self.post(f"/complaints/{c.complaint_id}/approve", {}, self.reviewer).status_code, 409)

        audit = self.client.get(f"/api/workflow/complaints/{c.complaint_id}/audit", **self.headers(self.reviewer)).json()
        self.assertEqual([a["action"] for a in audit], ["submitted", "processed", "approved"])
        self.assertEqual(audit[2]["before"]["review_status"], "pending")
        self.assertEqual(audit[2]["after"]["review_status"], "approved")
        self.assertEqual(c.validations.count(), 1)  # the original validation result is untouched

    def test_reject_requires_comment(self):
        c = self.needs_review()
        self.assertEqual(self.post(f"/complaints/{c.complaint_id}/reject", {"comment": ""}, self.reviewer).status_code, 422)
        res = self.post(f"/complaints/{c.complaint_id}/reject", {"comment": "Refund not allowed"}, self.reviewer)
        self.assertEqual(res.json()["review_status"], "rejected")

    def test_modify_priority_recomputes_sla(self):
        c = self.processed()
        res = self.post(f"/complaints/{c.complaint_id}/modify", {"priority": "P0", "comment": "VIP outage"}, self.reviewer)
        self.assertEqual(res.json()["priority"], "P0")
        c.refresh_from_db()
        self.assertEqual(c.sla_resolution_due - c.created_at, timedelta(hours=24))

    def test_reclassify_applies_rules_for_new_subcategory(self):
        c = self.processed()
        res = self.post(f"/complaints/{c.complaint_id}/reclassify", {"subcategory": "OVERHEATING"}, self.reviewer)
        body = res.json()
        self.assertEqual((body["category"], body["department"], body["priority"]), ("SAFETY", "PRODUCT_SAFETY", "P0"))
        self.assertEqual((body["assigned_to"], body["status"]), ("agent_safe", "escalated"))

    def test_assign_and_escalate(self):
        c = self.processed()
        res = self.post(f"/complaints/{c.complaint_id}/assign", {"assignee": "agent_safe"}, self.reviewer)
        self.assertEqual(res.json()["assigned_to"], "agent_safe")
        res = self.post(f"/complaints/{c.complaint_id}/escalate", {"level": "supervisor", "comment": "Customer is upset"}, self.reviewer)
        self.assertEqual((res.json()["status"], res.json()["escalation_level"]), ("escalated", "supervisor"))

    def test_regenerate_runs_pipeline_again(self):
        c = self.processed()
        llm = LLMResult(json.dumps(GOOD_OUTPUT), 100, 50, 0, 0, 10, "stop")
        with patch("genai_pipeline.pipeline.chat_json", return_value=llm):
            res = self.post(f"/complaints/{c.complaint_id}/regenerate", {"tone": "formal"}, self.reviewer)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(c.validations.count(), 2)

    # ---- agent actions ----

    def test_send_response_rules(self):
        pending = self.needs_review()
        self.assertEqual(self.post(f"/complaints/{pending.complaint_id}/send-response", {}, self.reviewer).status_code, 409)

        unsafe = self.processed(output(customer_response={"tone": "empathetic", "text": "We will refund you in full, sorry!"}))
        self.post(f"/complaints/{unsafe.complaint_id}/approve", {}, self.reviewer)
        self.assertEqual(self.post(f"/complaints/{unsafe.complaint_id}/send-response", {}, self.logistics_agent).status_code, 409)
        res = self.post(f"/complaints/{unsafe.complaint_id}/send-response",
                        {"text": "We are checking your order and will update you within 1 business day."}, self.logistics_agent)
        self.assertEqual((res.status_code, res.json()["status"]), (200, "in_progress"))

        mine = self.client.get(f"/api/complaints/my/{unsafe.complaint_id}", **self.headers(self.alice)).json()
        self.assertIn("within 1 business day", mine["latest_update"]["text"])
        self.assertEqual(mine["resolution_status"], "Being handled")

    def test_status_changes(self):
        c = self.processed()
        self.assertEqual(self.post(f"/complaints/{c.complaint_id}/status", {"status": "reopened"}, self.logistics_agent).status_code, 409)
        res = self.post(f"/complaints/{c.complaint_id}/status", {"status": "resolved"}, self.logistics_agent)
        self.assertEqual(res.json()["status"], "resolved")

    def test_follow_ups_and_sla_lists(self):
        c = self.processed()
        Complaint.objects.filter(pk=c.pk).update(sla_resolution_due=timezone.now() - timedelta(hours=1),
                                                 follow_up_due=timezone.now() - timedelta(hours=1))
        breached = self.client.get("/api/workflow/sla", {"state": "breached"}, **self.headers(self.logistics_agent)).json()
        self.assertIn(c.complaint_id, [i["complaint_id"] for i in breached])
        due = self.client.get("/api/workflow/follow-ups", {"overdue_only": True}, **self.headers(self.logistics_agent)).json()
        self.assertIn(c.complaint_id, [i["complaint_id"] for i in due])
        self.post(f"/complaints/{c.complaint_id}/follow-up-done", {}, self.logistics_agent)
        due = self.client.get("/api/workflow/follow-ups", **self.headers(self.logistics_agent)).json()
        self.assertNotIn(c.complaint_id, [i["complaint_id"] for i in due])

    def test_my_queue(self):
        c = self.processed()
        queue = self.client.get("/api/workflow/my-queue", **self.headers(self.logistics_agent)).json()
        self.assertEqual([i["complaint_id"] for i in queue], [c.complaint_id])

    # ---- customer actions ----

    def test_customer_reply_and_reopen(self):
        c = self.processed()
        self.post(f"/complaints/{c.complaint_id}/status", {"status": "awaiting_customer"}, self.logistics_agent)
        self.assertEqual(self.post(f"/my/complaints/{c.complaint_id}/reply", {"text": "Here is my order number."}, self.bob).status_code, 404)
        self.assertEqual(self.post(f"/my/complaints/{c.complaint_id}/reply", {"text": "Here is my order number."}, self.alice).status_code, 200)
        c.refresh_from_db()
        self.assertEqual(c.status, S.IN_PROGRESS)

        self.post(f"/complaints/{c.complaint_id}/status", {"status": "resolved"}, self.logistics_agent)
        self.assertEqual(self.post(f"/my/complaints/{c.complaint_id}/reply", {"text": "One more thing"}, self.alice).status_code, 409)
        self.assertEqual(self.post(f"/my/complaints/{c.complaint_id}/reopen", {"text": "Still not delivered!"}, self.alice).status_code, 200)
        c.refresh_from_db()
        self.assertEqual(c.status, S.REOPENED)

    def test_customer_sees_the_conversation(self):
        c = self.processed()
        self.logistics_agent.first_name = "Sara"
        self.logistics_agent.save()
        self.post(f"/complaints/{c.complaint_id}/send-response", {"text": "We have asked the courier for an update."},
                  self.logistics_agent)
        self.post(f"/complaints/{c.complaint_id}/notes", {"text": "internal: check stock"}, self.logistics_agent)
        self.post(f"/my/complaints/{c.complaint_id}/reply", {"text": "Thank you, I will wait."}, self.alice)
        detail = self.client.get(f"/api/complaints/my/{c.complaint_id}", **self.headers(self.alice)).json()
        self.assertEqual([(m["sender"], m["name"], m["text"]) for m in detail["messages"]], [
            ("lumora", "Sara from Logistics & Delivery", "We have asked the courier for an update."),
            ("customer", "You", "Thank you, I will wait."),
        ])  # the internal note is not shown

    def test_reopen_window(self):
        c = self.processed()
        self.post(f"/complaints/{c.complaint_id}/status", {"status": "resolved"}, self.logistics_agent)
        Complaint.objects.filter(pk=c.pk).update(resolved_at=timezone.now() - timedelta(days=8))
        self.assertEqual(self.post(f"/my/complaints/{c.complaint_id}/reopen", {"text": "Still broken"}, self.alice).status_code, 409)

    def test_staff_list_filters_on_working_state(self):
        self.processed()
        self.needs_review()
        res = self.client.get("/api/complaints", {"verification": "manual_review"}, **self.headers(self.reviewer)).json()
        self.assertEqual(res["count"], 1)
        res = self.client.get("/api/complaints", {"department": "LOGISTICS", "priority": "P2"}, **self.headers(self.reviewer)).json()
        self.assertEqual(res["count"], 2)


class Step7BugRegressionTests(WorkflowBase):
    """Bugs found by code review of Step 7 (B1-B11). Each test failed before its fix."""

    def failed_analysis(self, text):
        WorkflowBase.counter += 1
        complaint, _ = submit_complaint({"title": f"Complaint {WorkflowBase.counter}", "description": text}, self.alice, self.alice)
        analysis = GenAIAnalysis.objects.create(complaint=complaint, prompt_template=self.prompt, provider="deepseek",
                                                model="test", status="failed", error="API down")
        apply_validation(complaint, validate_analysis(analysis))
        complaint.refresh_from_db()
        return complaint

    def test_b1_genai_failure_still_enforces_rule_escalation_and_routing(self):
        c = self.failed_analysis("No rush, but my smart plug smells like burning plastic.")
        self.assertEqual((c.review_status, c.status), ("pending", S.ESCALATED))
        self.assertEqual((c.department.code, c.priority, c.assigned_to), ("PRODUCT_SAFETY", "P0", self.safety_agent))

    def test_b2_unclassifiable_failed_complaint_still_has_sla(self):
        c = self.failed_analysis("Hello, I would like someone to call me about my experience please.")
        self.assertIsNotNone(c.sla_resolution_due)

    def test_b3_approving_an_escalated_complaint_assigns_an_owner(self):
        c = self.needs_review()
        self.post(f"/complaints/{c.complaint_id}/modify", {"escalation_level": "supervisor", "comment": "x"}, self.reviewer)
        c.refresh_from_db()
        Complaint.objects.filter(pk=c.pk).update(assigned_to=None)
        res = self.post(f"/complaints/{c.complaint_id}/approve", {}, self.reviewer)
        self.assertEqual((res.json()["status"], res.json()["assigned_to"]), ("escalated", "agent_log"))

    def test_b4_de_escalation_updates_status_and_resolution(self):
        c = self.processed()
        self.post(f"/complaints/{c.complaint_id}/escalate", {"level": "supervisor", "comment": "Upset customer"}, self.reviewer)
        res = self.post(f"/complaints/{c.complaint_id}/modify", {"escalation_level": "none", "comment": "Resolved by phone"}, self.reviewer)
        self.assertNotEqual(res.json()["status"], "escalated")
        c.refresh_from_db()
        self.assertFalse(c.resolution["escalation_required"])

    def test_b5_reclassify_into_new_subcategory_without_rules(self):
        from catalog.models import Category
        category = Category.objects.create(code="ENERGY", name="Energy", default_department=Department.objects.get(code="LOGISTICS"))
        category.subcategories.create(code="WRONG_READING", name="Wrong reading", keywords=["energy reading"])
        c = self.processed()
        res = self.post(f"/complaints/{c.complaint_id}/reclassify", {"subcategory": "WRONG_READING"}, self.reviewer)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual((res.json()["category"], res.json()["priority"]), ("ENERGY", "P2"))

    def test_b6_no_agent_available_means_not_assigned(self):
        c = self.needs_review()
        res = self.post(f"/complaints/{c.complaint_id}/assign", {"department": "BILLING"}, self.reviewer)
        self.assertEqual((res.json()["assigned_to"], res.json()["status"]), (None, "analyzed"))

    def test_b7_generic_status_endpoint_cannot_bypass_actions(self):
        c = self.processed()
        self.assertEqual(self.post(f"/complaints/{c.complaint_id}/status", {"status": "escalated"}, self.logistics_agent).status_code, 400)
        pending = self.needs_review()
        self.assertEqual(self.post(f"/complaints/{pending.complaint_id}/status", {"status": "closed"}, self.reviewer).status_code, 409)

    def test_b8_every_outgoing_response_is_checked_for_promises(self):
        unsafe = self.processed(output(customer_response={"tone": "empathetic", "text": "We will refund you in full, sorry!"}))
        self.post(f"/complaints/{unsafe.complaint_id}/approve", {}, self.reviewer)
        url = f"/complaints/{unsafe.complaint_id}/send-response"
        # trivially edited AI text and a human-written promise are both blocked
        self.assertEqual(self.post(url, {"text": "We will refund you in full, sorry!!"}, self.logistics_agent).status_code, 409)
        self.assertEqual(self.post(url, {"text": "Good news: we will send you a 50 USD voucher today."}, self.logistics_agent).status_code, 409)
        # a reviewer may override with a reason (audited)
        res = self.post(url, {"text": "We will refund you in full.", "override_reason": "Manager-approved goodwill refund"}, self.reviewer)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(self.post(url, {"text": "We will refund you in full.", "override_reason": "Agent wants to"}, self.logistics_agent).status_code, 403)

    def test_b9_closed_without_resolving_is_not_breached(self):
        c = self.processed()
        self.post(f"/complaints/{c.complaint_id}/status", {"status": "awaiting_customer"}, self.logistics_agent)
        self.post(f"/complaints/{c.complaint_id}/status", {"status": "closed"}, self.logistics_agent)
        c.refresh_from_db()
        self.assertEqual(sla_status(c, now=c.created_at + timedelta(days=30))["resolution"], "met")

    def test_b10_reopened_complaint_gets_a_fresh_sla(self):
        c = self.processed()
        self.post(f"/complaints/{c.complaint_id}/status", {"status": "resolved"}, self.logistics_agent)
        Complaint.objects.filter(pk=c.pk).update(created_at=timezone.now() - timedelta(days=10))
        self.post(f"/my/complaints/{c.complaint_id}/reopen", {"text": "Still not delivered"}, self.alice)
        c.refresh_from_db()
        self.assertEqual(sla_status(c)["resolution"], "on_track")

    def test_b11_processing_a_closed_complaint_is_refused(self):
        c = self.processed()
        self.post(f"/complaints/{c.complaint_id}/status", {"status": "resolved"}, self.logistics_agent)
        res = self.client.post(f"/api/validation/process/{c.complaint_id}?reuse_analysis=true", **self.headers(self.reviewer))
        self.assertEqual(res.status_code, 409)


class AgentScopeTests(WorkflowBase):
    """Unauthorized-access tests: agents may only see and act on complaints assigned to them."""

    def setUp(self):
        self.mine = self.processed()  # auto-assigned to agent_log (LOGISTICS)
        self.other_agent = User.objects.create_user(
            "agent_log2", password="x", role=User.Role.AGENT, department=Department.objects.get(code="LOGISTICS"))
        self.theirs = self.processed()  # least-loaded logistics agent -> agent_log2
        self.assertEqual(self.theirs.assigned_to, self.other_agent)

    def get(self, url, user, **params):
        return self.client.get(url, params, **self.headers(user))

    def test_agent_list_contains_only_own_assignments(self):
        ids = [c["complaint_id"] for c in self.get("/api/complaints", self.logistics_agent).json()["items"]]
        self.assertEqual(ids, [self.mine.complaint_id])
        ids = [c["complaint_id"] for c in self.get("/api/complaints", self.reviewer).json()["items"]]
        self.assertEqual(set(ids), {self.mine.complaint_id, self.theirs.complaint_id})

    def test_other_agents_complaint_is_invisible_everywhere(self):
        cid = self.theirs.complaint_id
        analysis = self.theirs.genai_analyses.first()
        for url in (f"/api/complaints/{cid}", f"/api/complaints/{cid}/rule-preview", f"/api/complaints/{cid}/history",
                    f"/api/complaints/{cid}/similar", f"/api/genai/complaints/{cid}/analyses",
                    f"/api/genai/analyses/{analysis.pk}", f"/api/validation/complaints/{cid}/latest",
                    f"/api/workflow/complaints/{cid}", f"/api/workflow/complaints/{cid}/audit",
                    f"/api/workflow/complaints/{cid}/notes"):
            self.assertEqual(self.get(url, self.logistics_agent).status_code, 404, url)
        for action, body in (("notes", {"text": "hi"}), ("status", {"status": "resolved"}), ("send-response", {}),
                             ("follow-up-done", {})):
            self.assertEqual(self.post(f"/complaints/{cid}/{action}", body, self.logistics_agent).status_code, 404, action)

    def test_access_follows_reassignment(self):
        cid = self.mine.complaint_id
        self.assertEqual(self.get(f"/api/complaints/{cid}", self.logistics_agent).status_code, 200)
        self.post(f"/complaints/{cid}/assign", {"assignee": "agent_log2"}, self.reviewer)
        self.assertEqual(self.get(f"/api/complaints/{cid}", self.logistics_agent).status_code, 404)
        self.assertEqual(self.get(f"/api/complaints/{cid}", self.other_agent).status_code, 200)

    def test_agent_lists_and_reports_are_scoped(self):
        Complaint.objects.update(sla_resolution_due=timezone.now() - timedelta(hours=1))
        breached = self.get("/api/workflow/sla", self.logistics_agent, state="breached").json()
        self.assertEqual([c["complaint_id"] for c in breached], [self.mine.complaint_id])
        self.assertEqual(self.get("/api/validation/comparison", self.logistics_agent).status_code, 403)
        self.assertEqual(self.get("/api/workflow/review-queue", self.logistics_agent).status_code, 403)

    def test_agent_cannot_process_or_analyse_unassigned_complaints(self):
        cid = self.theirs.complaint_id
        self.assertEqual(self.client.post(f"/api/validation/process/{cid}", **self.headers(self.logistics_agent)).status_code, 404)
        self.assertEqual(self.client.post(f"/api/genai/analyze/{cid}", **self.headers(self.logistics_agent)).status_code, 404)


class AutoProcessTests(WorkflowBase):
    """Every submitted complaint is processed automatically, so agents receive it without manual steps."""

    def submit(self, text, user=None):
        WorkflowBase.counter += 1
        return self.client.post("/api/complaints", {"title": f"Complaint {WorkflowBase.counter}", "description": text},
                                content_type="application/json", **self.headers(user or self.alice))

    def llm(self, out):
        return LLMResult(json.dumps(out), 100, 50, 0, 0, 10, "stop")

    @override_settings(AUTO_PROCESS_ON_SUBMIT=True)
    def test_submission_is_processed_and_reaches_the_agent(self):
        with patch("genai_pipeline.pipeline.chat_json", return_value=self.llm(GOOD_OUTPUT)):
            res = self.submit("My order is delayed and has not arrived yet, please help.")
        self.assertEqual((res.status_code, res.json()["status"]), (201, "assigned"))
        cid = res.json()["complaint_id"]
        # the consequence that was fixed: the agent can now see and work on it without anyone processing it
        self.assertEqual(self.client.get(f"/api/complaints/{cid}", **self.headers(self.logistics_agent)).status_code, 200)
        actions = list(Complaint.objects.get(complaint_id=cid).audit_log.values_list("action", flat=True))
        self.assertEqual(actions, ["submitted", "processed"])

    @override_settings(AUTO_PROCESS_ON_SUBMIT=True)
    def test_genai_outage_still_routes_a_safety_complaint(self):
        from genai_pipeline.client import LLMError
        with patch("genai_pipeline.pipeline.chat_json", side_effect=LLMError("API down", retryable=False)):
            res = self.submit("No rush, but my smart plug smells like burning plastic.")
        self.assertEqual(res.status_code, 201)
        c = Complaint.objects.get(complaint_id=res.json()["complaint_id"])
        self.assertEqual((c.status, c.assigned_to, c.review_status), (S.ESCALATED, self.safety_agent, "pending"))

    @override_settings(AUTO_PROCESS_ON_SUBMIT=True)
    def test_unexpected_failure_never_loses_the_complaint(self):
        PromptTemplate.objects.update(is_active=False)  # e.g. someone deactivated every prompt
        res = self.submit("My order is delayed and has not arrived yet, please help.")
        self.assertEqual((res.status_code, res.json()["status"]), (201, "new"))
        c = Complaint.objects.get(complaint_id=res.json()["complaint_id"])
        self.assertEqual(c.review_status, "pending")
        self.assertIsNotNone(c.sla_resolution_due)
        queue = self.client.get("/api/workflow/review-queue", **self.headers(self.reviewer)).json()
        self.assertIn(c.complaint_id, [i["complaint_id"] for i in queue])
        self.assertIn("Automatic processing failed", c.audit_log.last().comment)

    def test_auto_processing_can_be_switched_off(self):
        with patch("genai_pipeline.pipeline.chat_json") as mock:
            res = self.submit("My order is delayed and has not arrived yet, please help.")
        self.assertEqual(res.json()["status"], "new")
        mock.assert_not_called()

    def test_process_pending_command_catches_up(self):
        res = self.submit("My order is delayed and has not arrived yet, please help.")  # auto-processing is off
        with patch("genai_pipeline.pipeline.chat_json", return_value=self.llm(GOOD_OUTPUT)):
            call_command("process_pending", stdout=__import__("io").StringIO())
        c = Complaint.objects.get(complaint_id=res.json()["complaint_id"])
        self.assertEqual((c.status, c.assigned_to), (S.ASSIGNED, self.logistics_agent))
