"""The second-look rules an administrator can set: what they change, what they can never change, versions and preview."""

import shutil
import tempfile
from types import SimpleNamespace

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from accounts.auth import ACCESS, create_token
from accounts.models import User
from catalog.models import Category
from complaint_dataset.csv_io import read_specs
from complaint_dataset.models import DatasetCase
from complaints.services import submit_complaint
from genai_pipeline.models import GenAIAnalysis, PromptTemplate
from knowledge_base.services import ingest_document

from . import checks as c
from . import review_admin, review_policy as rp
from .decision import review_reasons, score
from .models import ReviewPolicy, ValidationResult
from .services import validate_analysis
from .tests import SAMPLES, output

TEMP_MEDIA = tempfile.mkdtemp()


def finding(name, severity="critical", status=c.FAIL):
    return c.check(name, status, severity, "ai", "rules", f"{name} does not match")


COMPLAINT = SimpleNamespace(security_flags=[], category=None)
CLASSIFIED = {"category": "DELIVERY"}
DECIDED = {"rule_decided": True}


def reasons(checks, policy=None, *, independent=CLASSIFIED, view=DECIDED, escalation="none", complaint=COMPLAINT, out=None):
    policy = rp.merged(policy or {})
    return review_reasons(checks, score(checks, policy["penalty"]), independent, view, escalation, complaint, out or {}, policy)


class DecisionWithSettingsTests(SimpleTestCase):
    def test_the_defaults_behave_as_before(self):
        self.assertEqual(rp.defaults()["score_threshold"], 70)
        self.assertTrue(any("Critical finding (escalation)" in r for r in reasons([finding("escalation")])))
        self.assertEqual(reasons([]), [])
        self.assertTrue(any("score 60 is below 70" in r for r in reasons([finding("department", "major"), finding("urgency", "major"), finding("x", "major"),
                                                                       finding("y", "major")])))

    def test_the_cutoff_and_the_weights_change_the_score_rule(self):
        three_major = [finding(n, "major") for n in ("a", "b", "c")]  # 100 - 30 = 70
        self.assertFalse(reasons(three_major))
        self.assertTrue(reasons(three_major, {"score_threshold": 75}))
        self.assertFalse(reasons(three_major, {"penalty": {"major": 5}}))  # 100 - 15 = 85
        self.assertFalse(reasons(three_major, {"triggers": {"low_score": False}, "score_threshold": 95}))

    def test_a_critical_finding_the_rules_already_fixed_can_be_left_out(self):
        policy = {"ignore_corrected_criticals": True}
        for name in ("escalation", "compensation"):
            self.assertFalse(reasons([finding(name)], policy), name)
        self.assertTrue(reasons([finding("escalation")]))  # off by default
        # only when the rule was decided on facts is urgency / priority simply overridden
        self.assertFalse(reasons([finding("priority")], policy))
        self.assertTrue(reasons([finding("priority")], policy, view={"rule_decided": False}))

    def test_problems_the_rules_cannot_fix_always_count(self):
        policy = {"ignore_corrected_criticals": True, "triggers": {"low_score": False, "policy_contradiction": False}}
        for name in ("prohibited_action", "unsupported_promise", "hallucinated_fact", "hallucinated_reference", "category"):
            self.assertTrue(reasons([finding(name)], policy), name)

    def test_the_safety_net_cannot_be_switched_off(self):
        off = {"triggers": {"low_score": False, "policy_contradiction": False}, "ignore_corrected_criticals": True, "score_threshold": 50}
        self.assertTrue(reasons([], off, independent={"category": None}))  # cannot classify
        self.assertTrue(reasons([], off, view={"rule_decided": False, "missing_facts": ["days_since_delivery"]}))  # facts missing
        self.assertTrue(reasons([finding("policy_support", "major")], off))  # no policy supports it
        self.assertTrue(reasons([], off, escalation="critical_management"))  # sensitive
        self.assertTrue(reasons([], off, escalation="compliance_review"))
        self.assertTrue(reasons([], off, complaint=SimpleNamespace(security_flags=[{"flag": "x"}], category=None)))  # manipulation
        self.assertTrue(reasons([], off, out={"manipulation_detected": True}))

    def test_more_levels_can_count_as_sensitive(self):
        self.assertFalse(reasons([], escalation="supervisor"))
        self.assertTrue(reasons([], {"sensitive_levels": ["supervisor", "compliance_review", "critical_management"]}, escalation="supervisor"))

    def test_chosen_problem_types_always_go_to_a_person(self):
        safety = SimpleNamespace(security_flags=[], category=SimpleNamespace(code="SAFETY", name="Safety"))
        self.assertFalse(reasons([], complaint=safety))
        found = reasons([], {"always_review_categories": ["SAFETY"]}, complaint=safety)
        self.assertEqual(len(found), 1)
        self.assertIn("always checked by a person", found[0])
        self.assertFalse(reasons([], {"always_review_categories": ["BILLING"]}, complaint=safety))


class SettingsLimitTests(SimpleTestCase):
    def bad(self, data):
        with self.assertRaises(rp.ReviewPolicyError) as caught:
            rp.clean(data, {"SAFETY", "BILLING"})
        return " ".join(caught.exception.problems)

    def test_the_limits(self):
        self.assertIn("50 to 95", self.bad({"score_threshold": 20}))
        self.assertIn("50 to 95", self.bad({"score_threshold": 99}))
        self.assertIn("50 to 95", self.bad({"score_threshold": "high"}))
        self.assertIn("0 to 50", self.bad({"penalty": {"critical": 90}}))
        self.assertIn("at least as much", self.bad({"penalty": {"critical": 5, "major": 10}}))
        self.assertIn("Unknown settings", self.bad({"skip_everything": True}))
        self.assertIn("switched on or off", self.bad({"triggers": {"low_score": "no"}}))
        self.assertIn("always count as sensitive", self.bad({"sensitive_levels": ["supervisor"]}))
        self.assertIn("existing problem types", self.bad({"always_review_categories": ["NOPE"]}))

    def test_a_partial_change_keeps_everything_else_and_is_tidied(self):
        s = rp.clean({"score_threshold": 60, "always_review_categories": ["SAFETY", "BILLING", "SAFETY"]}, {"SAFETY", "BILLING"})
        self.assertEqual((s["score_threshold"], s["penalty"], s["always_review_categories"]), (60, rp.defaults()["penalty"], ["BILLING", "SAFETY"]))


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class ReviewPolicyApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_catalog", verbosity=0)
        call_command("load_rules", verbosity=0)
        call_command("load_prompts", verbosity=0)
        for name in ("delivery_policy.docx", "safety_policy.pdf"):
            ingest_document(name, (SAMPLES / name).read_bytes(), {}, None)
        cls.admin = User.objects.create_user("admin1", password="x", role=User.Role.ADMIN)
        cls.manager = User.objects.create_user("manager1", password="x", role=User.Role.MANAGER)
        cls.customer = User.objects.create_user("alice", password="x")
        cls.prompt = PromptTemplate.objects.get(is_active=True)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)

    counter = 0

    def complaint(self, text="My order is delayed and has not arrived yet, please help."):
        ReviewPolicyApiTests.counter += 1
        complaint, _ = submit_complaint({"title": f"Complaint number {self.counter}", "description": text}, self.customer, self.customer)
        return complaint

    def headers(self, user):
        return {"HTTP_AUTHORIZATION": f"Bearer {create_token(user, ACCESS)}"}

    def post(self, path, body, user=None):
        return self.client.post(f"/api/validation/review-policy{path}", body, content_type="application/json", **self.headers(user or self.admin))

    def result(self, complaint, checks, **fields):
        return ValidationResult.objects.create(
            complaint=complaint, checks=checks, score=score(checks), agreement_rate=1.0, decision="verified",
            independent_expected=fields.pop("independent", CLASSIFIED), genai_view_expected=DECIDED,
            final_resolution={"escalation_level": "none"}, **fields)

    # ---- who and how ----

    def test_only_an_administrator_sees_or_changes_the_rules(self):
        for user in (self.manager, self.customer):
            self.assertEqual(self.client.get("/api/validation/review-policy", **self.headers(user)).status_code, 403)
            self.assertEqual(self.post("", {"settings": {"score_threshold": 60}, "comment": "lower it"}, user).status_code, 403)
            self.assertEqual(self.post("/preview", {"settings": {}}, user).status_code, 403)

    def test_the_page_shows_the_defaults_the_limits_and_what_is_always_on(self):
        body = self.client.get("/api/validation/review-policy", **self.headers(self.admin)).json()
        self.assertEqual((body["active"]["version"], body["active"]["settings"]["score_threshold"], body["bounds"]["score_threshold"]), (0, 70, [50, 95]))
        self.assertTrue(any("manipulation" in line for line in body["always_on"]))
        self.assertIn("SAFETY", [x["code"] for x in body["categories"]])

    def test_saving_makes_a_new_version_with_a_reason_and_a_second_identical_save_is_refused(self):
        res = self.post("", {"settings": {"score_threshold": 60, "always_review_categories": ["SAFETY"]}, "comment": "Too many reviews"})
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertEqual((body["active"]["version"], body["active"]["comment"], body["active"]["created_by_name"]), (1, "Too many reviews", "admin1"))
        self.assertEqual(body["active"]["settings"]["score_threshold"], 60)
        self.assertEqual(rp.current()[0], 1)
        self.assertEqual(self.post("", {"settings": {"score_threshold": 60, "always_review_categories": ["SAFETY"]}, "comment": "again please"}).status_code, 400)
        self.assertEqual(self.post("", {"settings": {"score_threshold": 65}, "comment": ""}).status_code, 400)  # a reason is required
        self.assertEqual(self.post("", {"settings": {"score_threshold": 10}, "comment": "far too low"}).status_code, 400)
        self.assertEqual(self.post("", {"settings": {"triggers": {"manipulation": False}}, "comment": "turn it off"}).status_code, 400)
        self.assertEqual(ReviewPolicy.objects.count(), 1)

    def test_rolling_back_adds_a_version_and_keeps_the_history(self):
        self.post("", {"settings": {"score_threshold": 60}, "comment": "first change"})
        self.post("", {"settings": {"score_threshold": 80}, "comment": "second change"})
        body = self.post("/1/rollback", {"comment": "second was too strict"}).json()
        self.assertEqual((body["active"]["version"], body["active"]["settings"]["score_threshold"]), (3, 60))
        self.assertIn("Back to version 1", body["active"]["comment"])
        self.assertEqual([h["version"] for h in body["history"]], [3, 2, 1])
        self.assertEqual([h["is_active"] for h in body["history"]], [True, False, False])
        back = self.post("/0/rollback", {"comment": "go back to the built-in rules"}).json()
        self.assertEqual(back["active"]["settings"], rp.defaults())
        self.assertEqual(self.post("/9/rollback", {"comment": "no such version"}).status_code, 400)

    # ---- every decision records the version it used ----

    def test_a_validation_records_which_version_decided_it(self):
        def validate():
            analysis = GenAIAnalysis.objects.create(complaint=self.complaint(), prompt_template=self.prompt, provider="deepseek", model="t",
                                                    status="success", output=output(), policy_versions={"DEL-POL": "1.0"})
            return validate_analysis(analysis)

        self.assertEqual(validate().review_policy_version, 0)
        self.post("", {"settings": {"score_threshold": 60}, "comment": "version one"})
        self.assertEqual(validate().review_policy_version, 1)

    # ---- the preview ----

    def test_the_preview_shows_what_would_change_and_what_must_still_be_caught(self):
        fixed_by_rules, clean_one, unclassifiable = self.complaint(), self.complaint("The parcel is late again, please check."), self.complaint("Hello, a word please.")
        self.result(fixed_by_rules, [finding("escalation")])
        self.result(clean_one, [])
        self.result(unclassifiable, [], independent={"category": None})  # the rules cannot classify it: a person must look
        spec = next(s for s in read_specs() if s.expected.get("review_required"))
        DatasetCase.objects.create(case_id=spec.case_id, split="dev", group=spec.group, complaint=unclassifiable)

        body = self.post("/preview", {"settings": {"ignore_corrected_criticals": True, "triggers": {"low_score": False}, "score_threshold": 50}}).json()
        self.assertEqual((body["checked"], body["review_now"], body["review_after"]), (3, 2, 1))
        self.assertEqual((body["no_longer_review"], body["newly_review"]), (1, 0))
        self.assertEqual(body["dropped_examples"][0]["complaint_id"], fixed_by_rules.complaint_id)
        self.assertEqual((body["must_review"], body["must_review_caught_now"], body["must_review_caught_after"]), (1, 1, 1))  # the safety net holds
        self.assertEqual(rp.current()[0], 0)  # a preview saves nothing

        stricter = self.post("/preview", {"settings": {"always_review_categories": [Category.objects.first().code]}}).json()
        self.assertGreaterEqual(stricter["review_after"], stricter["review_now"])
        self.assertEqual(self.post("/preview", {"settings": {"score_threshold": 5}}).status_code, 400)
