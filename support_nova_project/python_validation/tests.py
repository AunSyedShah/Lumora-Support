"""
Pipeline 2 tests. GenAI outputs are written by hand here (as test fixtures) so each check can be
triggered deterministically; no GenAI API is called.
"""

import copy
import json
import shutil
import tempfile
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase, override_settings

from accounts.auth import ACCESS, create_token
from accounts.models import User
from complaints.models import Complaint
from complaints.services import submit_complaint
from genai_pipeline.client import LLMResult
from genai_pipeline.models import GenAIAnalysis, PromptTemplate
from knowledge_base.models import PolicyDocument
from knowledge_base.services import ingest_document

from . import text_checks
from .services import validate_analysis

TEMP_MEDIA = tempfile.mkdtemp()
SAMPLES = settings.BASE_DIR / "sample_documents"

# Consistent with rule RR-001 (DELAYED_DELIVERY base rule) and DEL-POL 2.1.
GOOD_OUTPUT = {
    "complaint_summary": "Customer's order is late and tracking is stuck.",
    "primary_issue": {"category": "DELIVERY", "subcategory": "DELAYED_DELIVERY", "description": "Late order"},
    "secondary_issues": [],
    "entities": {"products": [], "order_ids": [], "transaction_ids": [], "complaint_refs": [], "dates": [],
                 "amounts": [], "locations": []},
    "sentiment": "Negative", "emotions": [], "urgency": "Medium", "urgency_reason": "Late delivery.",
    "priority": "P2", "department": "LOGISTICS", "supporting_departments": [],
    "policy_references": [{"policy_id": "DEL-POL", "section": "2.1", "chunk_id": None, "relevance": "Delays"}],
    "resolution_steps": ["Check courier tracking status",
                         "Give the customer an updated delivery estimate within 1 business day"],
    "compensation": {"type": "none", "justification": "Not eligible yet.", "policy_id": None, "section": None},
    "escalation_required": False, "escalation_level": "none", "escalation_reason": "", "escalation_notes": None,
    "missing_information": [], "clarification_questions": ["Could you share your order number?"],
    "customer_response": {"tone": "empathetic",
                          "text": "We are sorry your order is late. We are checking with the courier and will "
                                  "update you within 1 business day."},
    "follow_up": {"required": True, "type": "resolution_confirmation", "days": 2, "message": "Delivery update."},
    "agent_guidance": ["Do not promise a delivery date."], "manipulation_detected": False,
}
NOTES = {"summary": "s", "key_facts": ["f"], "reason": "r", "actions_taken": ["a"], "relevant_policy": "p", "next_action": "n"}


def output(**changes):
    data = copy.deepcopy(GOOD_OUTPUT)
    data.update(changes)
    return data


class TextCheckTests(TestCase):
    def test_promises(self):
        policy = ["Approved refunds are issued within 7 business days."]
        def kinds(text, allowed=("none",), decided=True):
            return [k for k, _, _ in text_checks.unsupported_promises(text, list(allowed), decided, policy)]
        self.assertEqual(kinds("We will refund you in full."), ["guaranteed_refund"])
        self.assertEqual(kinds("We will refund you in full.", allowed=["full_refund"]), [])
        self.assertEqual(kinds("We will refund you in full.", allowed=["full_refund"], decided=False), ["refund_before_verification"])
        self.assertEqual(kinds("I will check your eligibility for a refund."), [])
        self.assertEqual(kinds("If you are eligible, we will refund you."), [])  # conditional, not a promise
        self.assertEqual(kinds("I am unable to approve a refund at this point."), [])
        self.assertEqual(kinds("As a one-time courtesy we will waive the restocking fee."), ["policy_exception"])
        self.assertEqual(kinds("Your parcel will arrive tomorrow."), ["unsupported_deadline"])
        self.assertEqual(kinds("We will send you a 50 USD voucher."), ["guaranteed_compensation"])
        self.assertEqual(kinds("Refunds are issued within 7 business days."), [])  # supported by the policy
        self.assertEqual(kinds("You will hear from us within 2 days."), ["unsupported_timeline"])
        self.assertEqual(kinds("Your order was due 5 days ago."), [])  # a fact, not a promise

    def test_untraceable_facts(self):
        found = text_checks.untraceable_facts("Order ORD-10001 (29 USD) and ORD-99999 for $450", "ORD-10001", {"ORD-10001"}, {29.0})
        self.assertEqual(sorted(v for _, v, _ in found), ["450 USD", "ORD-99999"])

    def test_required_actions(self):
        missing = text_checks.missing_required_actions(
            ["Check courier tracking status", "Refund the shipping fee"], ["Check the courier tracking status today"]
        )
        self.assertEqual([a for a, _ in missing], ["Refund the shipping fee"])


@override_settings(MEDIA_ROOT=TEMP_MEDIA, GENAI_RETRY_BACKOFF_SECONDS=0)
class ValidationScenarioTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_catalog", verbosity=0)
        call_command("load_rules", verbosity=0)
        call_command("load_prompts", verbosity=0)
        for name in ("delivery_policy.docx", "safety_policy.pdf", "faq.pdf", "refund_policy_v2.pdf"):
            ingest_document(name, (SAMPLES / name).read_bytes(), {}, None)
        cls.customer = User.objects.create_user("alice", password="x")
        cls.agent = User.objects.create_user("agent1", password="x", role=User.Role.AGENT)
        cls.reviewer = User.objects.create_user("reviewer1", password="x", role=User.Role.REVIEWER)
        cls.prompt = PromptTemplate.objects.get(is_active=True)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)

    counter = 0

    def complaint(self, text="My order is delayed and has not arrived yet, please help."):
        # Each call gets a unique title, otherwise intake rejects it as a duplicate (correctly).
        ValidationScenarioTests.counter += 1
        title = f"Complaint number {self.counter}"
        complaint, _ = submit_complaint({"title": title, "description": text}, self.customer, self.customer)
        return complaint

    def analysis(self, complaint, out, policy_versions=None):
        return GenAIAnalysis.objects.create(
            complaint=complaint, prompt_template=self.prompt, provider="deepseek", model="test", status="success",
            output=out, policy_versions=policy_versions or {"DEL-POL": "1.0"},
        )

    def validate(self, out, text=None, **kw):
        return validate_analysis(self.analysis(self.complaint(text) if text else self.complaint(), out, **kw))

    def names(self, result, statuses=("fail", "warning")):
        return {c["name"] for c in result.checks if c["status"] in statuses}

    # ---- the happy path ----

    def test_consistent_output_is_verified(self):
        result = self.validate(output())
        self.assertEqual(result.decision, "verified", result.review_reasons)
        self.assertEqual(result.agreement_rate, 1.0)
        self.assertGreaterEqual(result.score, 90)

    # ---- SRS traps ----

    def test_missed_escalation_is_enforced(self):
        """Escalation trap: a calm safety complaint the GenAI treated as a delivery issue."""
        result = self.validate(output(), text="My order is late. Also the plug had a faint burning smell yesterday.")
        escalation = next(c for c in result.checks if c["name"] == "escalation")
        self.assertEqual((escalation["status"], escalation["severity"]), ("fail", "critical"))
        self.assertEqual(result.final_resolution["escalation_level"], "specialist_team")
        self.assertEqual(result.final_resolution["department"], "PRODUCT_SAFETY")  # critical routing enforced
        self.assertIn("LOGISTICS", result.final_resolution["supporting_departments"])
        self.assertEqual(result.decision, "manual_review")

    def test_angry_but_low_risk_final_priority_follows_rules(self):
        out = output(primary_issue={"category": "TECH_SUPPORT", "subcategory": "APP_CONNECTIVITY", "description": "App"},
                     department="TECH_SUPPORT", urgency="High", priority="P1", sentiment="Strongly Negative",
                     policy_references=[])
        result = self.validate(out, text="THIS IS RIDICULOUS!!! The app keeps crashing, I am FURIOUS!!!")
        self.assertEqual(result.final_resolution["priority"], "P3")  # tone cannot raise it
        self.assertIn("priority", self.names(result))

    def test_disallowed_compensation_removed(self):
        out = output(compensation={"type": "full_refund", "justification": "sorry", "policy_id": None, "section": None})
        result = self.validate(out)
        self.assertEqual(result.final_resolution["compensation"]["type"], "none")
        self.assertEqual(result.decision, "manual_review")

    def test_unsupported_promise_requires_rewrite(self):
        out = output(customer_response={"tone": "empathetic", "text": "We will refund you in full and it will arrive tomorrow."})
        result = self.validate(out)
        promises = [c["python"] for c in result.checks if c["name"] == "unsupported_promise"]
        self.assertIn("guaranteed_refund", promises)
        self.assertIn("unsupported_deadline", promises)
        self.assertTrue(result.final_resolution["response_requires_rewrite"])

    def test_hallucinated_policy_and_reference(self):
        out = output(policy_references=[{"policy_id": "FAKE-POL", "section": "1", "chunk_id": None, "relevance": "x"}],
                     customer_response={"tone": "concise", "text": "Your order ORD-55555 of 999 USD is being checked."})
        result = self.validate(out)
        self.assertIn("policy_support", self.names(result))
        self.assertEqual({c["genai"] for c in result.checks if c["name"] == "hallucinated_fact"}, {"ORD-55555", "999 USD"})

    def test_lower_precedence_document_instead_of_policy(self):
        out = output(policy_references=[{"policy_id": "FAQ-GEN", "section": "3", "chunk_id": None, "relevance": "voucher"}])
        result = self.validate(out)
        self.assertIn("policy_precedence", self.names(result))

    def test_category_mismatch(self):
        out = output(primary_issue={"category": "BILLING", "subcategory": "INVOICE_ERROR", "description": "x"})
        result = self.validate(out)
        category = next(c for c in result.checks if c["name"] == "category")
        self.assertEqual((category["genai"], category["python"], category["severity"]), ("BILLING", "DELIVERY", "critical"))

    def test_missing_required_action_added_to_final(self):
        out = output(resolution_steps=["Say sorry to the customer"])
        result = self.validate(out)
        self.assertIn("missing_required_action", self.names(result))
        self.assertTrue(any("[Required by RR-001]" in s for s in result.final_resolution["resolution_steps"]))

    def test_policy_revised_after_analysis(self):
        """Hidden policy update: the analysis used DEL-POL v0.9 but v1.0 is active now."""
        result = self.validate(output(), policy_versions={"DEL-POL": "0.9"})
        self.assertIn("policy_version", self.names(result))

    def test_unclassifiable_complaint_needs_review(self):
        result = self.validate(output(), text="Hello there, I would like to talk to someone about my experience.")
        self.assertIn("Complaint is ambiguous", " ".join(result.review_reasons))

    def test_failed_analysis_goes_to_manual_review(self):
        analysis = GenAIAnalysis.objects.create(complaint=self.complaint(), prompt_template=self.prompt, provider="deepseek",
                                                model="test", status="failed", error="invalid JSON x3")
        result = validate_analysis(analysis)
        self.assertEqual((result.decision, result.score), ("manual_review", 0))

    # ---- API ----

    def headers(self, user):
        return {"HTTP_AUTHORIZATION": f"Bearer {create_token(user, ACCESS)}"}

    def test_process_endpoint_end_to_end(self):
        complaint = self.complaint("No rush, but my plug smells like burning plastic.")
        safety = output(primary_issue={"category": "SAFETY", "subcategory": "OVERHEATING", "description": "Burning"},
                        department="PRODUCT_SAFETY", urgency="Critical", priority="P0", escalation_required=True,
                        escalation_level="specialist_team", escalation_notes=NOTES,
                        policy_references=[{"policy_id": "SAF-POL", "section": "2.1", "chunk_id": None, "relevance": "x"}])
        llm = LLMResult(json.dumps(safety), 100, 50, 0, 0, 10, "stop")
        with patch("genai_pipeline.pipeline.chat_json", return_value=llm):
            res = self.client.post(f"/api/validation/process/{complaint.complaint_id}", **self.headers(self.reviewer))
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["final_resolution"]["priority"], "P0")
        complaint.refresh_from_db()
        self.assertEqual(complaint.status, Complaint.Status.ESCALATED)
        self.assertEqual(self.client.post(f"/api/validation/process/{complaint.complaint_id}",
                                          **self.headers(self.customer)).status_code, 403)

    def test_comparison_report_csv(self):
        self.validate(output())
        self.validate(output(department="BILLING"))
        res = self.client.get("/api/validation/comparison", {"format": "csv"}, **self.headers(self.reviewer))
        lines = res.content.decode().strip().splitlines()
        self.assertTrue(lines[0].startswith("complaint_id,genai_category,python_category"))
        self.assertEqual(len(lines), 3)
        rows = self.client.get("/api/validation/comparison", **self.headers(self.reviewer)).json()
        self.assertEqual(self.client.get("/api/validation/comparison", **self.headers(self.agent)).status_code, 403)
        self.assertEqual(sorted(r["match"] for r in rows), ["match", "mismatch"])

    def test_over_prioritisation_counts_as_mismatch_in_report(self):
        from .api import comparison_row
        row = comparison_row(self.validate(output(priority="P1", urgency="High")))
        self.assertEqual((row["match"], row["python_priority"]), ("mismatch", "P2"))
