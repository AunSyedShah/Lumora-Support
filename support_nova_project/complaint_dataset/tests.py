"""
The synthetic dataset: specs, expected labels, order facts, text checks and the loader.
The LLM is never called - generated text is written by hand here.
"""

import copy
import tempfile
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from complaints.facts import compute_facts
from complaints.models import Complaint, Order
from catalog.models import Product

from . import csv_io, generator
from .evaluation import evaluate_case, summarize
from .expected import expected_labels, product_names
from .loader import load_dataset, spread_dates
from .models import DatasetCase
from .orders import order_fields
from .scenarios import INJECTIONS
from .specs import Spec, SpecBuilder, build_specs
from .summary import coverage


class RulesLoaded(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_catalog", verbosity=0)
        call_command("load_rules", verbosity=0)


class SpecTests(RulesLoaded):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.specs, cls.problems = build_specs()
        cls.by_id = {s.case_id: s for s in cls.specs}

    def test_srs_minimums_and_split(self):
        self.assertEqual(self.problems, [])
        c = coverage(self.specs)
        for label, count, minimum in c["minimums"]:
            self.assertGreaterEqual(count, minimum, label)
        self.assertEqual(c["splits"]["test"], 100)
        self.assertGreaterEqual(c["categories"], 10)
        self.assertGreaterEqual(c["subcategories"], 20)
        self.assertEqual(len({s.case_id for s in self.specs}), 500)

    def test_same_seed_same_specs(self):
        again, _ = build_specs()
        self.assertEqual([asdict(s) for s in again], [asdict(s) for s in self.specs])

    def test_core_specs_hit_their_target_rule(self):
        core = [s for s in self.specs if s.group == "core"]
        self.assertTrue(core)
        for spec in core:
            self.assertEqual(spec.expected["rule"], spec.target, spec.case_id)

    def test_escalation_specs_fire_their_rule(self):
        for spec in (s for s in self.specs if s.group == "escalation"):
            self.assertIn(spec.target, spec.expected["escalation_rules"], spec.case_id)

    def test_calm_critical_is_a_safety_case(self):
        for spec in (s for s in self.specs if s.group == "calm_critical"):
            self.assertEqual((spec.expected["priority"], spec.style), ("P0", "calm"), spec.case_id)

    def test_repeats_and_duplicates(self):
        linked = [s for s in self.specs if s.related_to]
        self.assertTrue(linked)
        for spec in linked:
            earlier = self.by_id[spec.related_to]
            self.assertLess(earlier.case_id, spec.case_id)  # the original is loaded first
            self.assertEqual((earlier.customer, earlier.split), (spec.customer, spec.split))
        third = [s for s in linked if s.previous_complaints == 2]
        self.assertTrue(all("ESC-016" in s.expected["escalation_rules"] for s in third))

    def test_shared_customers_have_unrelated_complaints(self):
        by_customer = {}
        for spec in (s for s in self.specs if not s.related_to and s.group == "core"):
            by_customer.setdefault(spec.customer, []).append(spec)
        pairs = [v for v in by_customer.values() if len(v) == 2]
        self.assertEqual(len(pairs), 20)
        for a, b in pairs:
            self.assertEqual(a.customer_type, b.customer_type)
            self.assertNotEqual(a.expected["category"], b.expected["category"])

    def test_labels_come_from_the_scenario_not_from_text(self):
        spec = next(s for s in self.specs if s.group == "contradictory" and s.subcategories == ["DAMAGED_IN_TRANSIT"])
        # the customer claims it arrived yesterday; the order says 20 days -> the late-report rule
        self.assertEqual((spec.days_since_delivery, spec.expected["rule"]), (20, "RR-011"))

    def test_ambiguous_cases_expect_review(self):
        for spec in (s for s in self.specs if s.group == "ambiguous"):
            self.assertEqual(spec.expected["subcategory"], "")
            self.assertTrue(spec.expected["review_required"])

    def test_csv_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "specs.csv"
            csv_io.write_specs(self.specs, path)
            back = csv_io.read_specs(path)
        for original, read in zip(self.specs, back):
            expected = {k: v for k, v in original.expected.items() if k in csv_io.EXPECTED_FIELDS}
            self.assertEqual(asdict(read) | {"expected": {}}, asdict(original) | {"expected": {}})
            self.assertEqual(read.expected, expected)


class OrderFactTests(RulesLoaded):
    """Orders built at load time give exactly the spec's facts, whatever weekday it is."""

    def check(self, spec, today):
        customer = User.objects.create_user(f"c{Order.objects.count()}", password="x", customer_type="standard")
        product = Product.objects.get(code=spec.product)
        order = Order.objects.create(order_ref=f"ORD-{70000 + Order.objects.count()}", customer=customer,
                                     product=product, **order_fields(spec, today))
        facts = compute_facts(customer, order, product, {}, 0, today=today)
        for name in ("days_late", "days_since_delivery", "days_since_purchase"):
            if getattr(spec, name) is not None:
                self.assertEqual(facts[name], getattr(spec, name), f"{name} on {today:%A}")
        self.assertEqual(facts["amount"], spec.amount)

    def test_every_anchor_on_every_weekday(self):
        builder = SpecBuilder(seed=1)
        specs = [builder.base(code) for code in ("DELAYED_DELIVERY", "DAMAGED_IN_TRANSIT", "HARDWARE_MALFUNCTION",
                                                   "UNEXPECTED_RENEWAL")]
        builder.set_days(specs[0], "days_late", 11)
        for offset in range(7):
            today = date(2026, 9, 21) + timedelta(days=offset)
            for spec in specs:
                self.check(spec, today)


class TextCheckTests(RulesLoaded):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.names = product_names()
        cls.keywords = generator.escalation_keywords()

    def spec(self, subcategory, **fields):
        builder = SpecBuilder(seed=3)
        spec = builder.base(subcategory)
        for key, value in fields.items():
            setattr(spec, key, value)
        spec.expected = expected_labels(spec, self.names)
        return spec

    def text(self, description, title="A clear complaint title"):
        return {"title": title, "description": description, "requested_resolution": ""}

    def test_extra_trigger_is_flagged_only_if_it_changes_labels(self):
        changer = generator.labels_changer(self.names)
        refund = self.spec("REFUND_DENIED", order_ref_in="field")
        words = "The refund was refused and I think that is wrong, it arrived broken and I sent it back straight away. "
        problems = generator.check_text(refund, self.text(words + "I will call my lawyer."), self.keywords, changer)
        self.assertTrue(any("lawyer" in p for p in problems))
        shock = self.spec("ELECTRIC_SHOCK", order_ref_in="field")
        harmless = generator.check_text(shock, self.text(words + "It gave me a shock when I touched it."),
                                        self.keywords, changer)
        self.assertEqual(harmless, [])

    def test_placeholders_and_length(self):
        spec = self.spec("DELAYED_DELIVERY", order_ref_in="text")
        problems = generator.check_text(spec, self.text("Too short."), self.keywords)
        self.assertEqual(len(problems), 2)  # too short + missing {ORDER_REF}
        invented = generator.check_text(spec, self.text("Order {ORDER_REF} " + "late " * 30 + "see ORD-12345"),
                                        self.keywords)
        self.assertTrue(any("invents" in p for p in invented))

    def test_near_duplicate_must_differ(self):
        spec = self.spec("DELAYED_DELIVERY", order_ref_in="field")
        body = "My parcel is late and nobody tells me anything about it, I have waited for more than a week now. " * 2
        problems = generator.check_text(spec, self.text(body), self.keywords, original={"description": body})
        self.assertTrue(any("identical" in p for p in problems))

    def test_injection_is_inserted_word_for_word(self):
        base = {"title": "t", "description": "First sentence. Second sentence. Third one.", "requested_resolution": ""}
        for position in ("start", "middle", "end"):
            spec = Spec(injection=INJECTIONS[0], injection_position=position)
            self.assertIn(INJECTIONS[0], generator.insert_injection(spec, base)["description"])
        spec = Spec(injection=INJECTIONS[1], injection_position="supporting_information")
        self.assertEqual(generator.insert_injection(spec, base)["supporting_information"], INJECTIONS[1])

    def test_false_claims_hide_the_true_dates(self):
        spec = self.spec("DAMAGED_IN_TRANSIT", claims=["It arrived yesterday."])
        brief = generator.brief(spec, self.names)
        self.assertNotIn("delivered", brief.split("It arrived yesterday.")[0].lower())
        self.assertEqual(generator.roughly(400), "about a year and 1 months ago")

    def test_retry_once_then_flag(self):
        spec = self.spec("DELAYED_DELIVERY", order_ref_in="text")
        bad = self.text("No placeholder here, just a long enough complaint about a parcel that is late. " * 2)
        good = self.text("Order {ORDER_REF} is late. " + "It has not arrived and nobody answers my messages. " * 3)
        with mock.patch.object(generator, "call_writer", side_effect=[(bad, 10, 10), (good, 10, 10)]) as call:
            record = generator.write_complaint(spec, self.names, self.keywords, "test-model")
        self.assertEqual((call.call_count, record["attempts"], record["flags"]), (2, 2, []))
        self.assertIn("previous answer had these problems", call.call_args_list[1].args[0][-1]["content"])


class LoaderTests(RulesLoaded):
    def make_specs(self):
        builder = SpecBuilder(seed=5)
        original = builder.add(builder.build_for_rule(builder.rules["RR-010"]))  # damaged, reported in time
        original.order_ref_in = "text"
        repeat = builder._copy_as(original, "repeat", 1)
        builder.add(repeat)
        other = builder.add(builder.build_for_rule(builder.rules["RR-092"]))  # marketing emails, no order
        other.customer, other.customer_type = original.customer, original.customer_type
        for spec in builder.specs:
            spec.expected = expected_labels(spec, builder.names)
        return builder.specs

    def test_load_fills_placeholders_links_repeats_and_matches_facts(self):
        specs = self.make_specs()
        original, repeat, other = specs
        texts = {
            original.case_id: {"title": "Camera arrived broken", "supporting_information": "", "requested_resolution": "",
                               "description": "Order {ORDER_REF} arrived with a crushed box and the camera is broken inside."},
            repeat.case_id: {"title": "Camera arrived broken", "supporting_information": "", "requested_resolution": "",
                             "description": "Order {ORDER_REF} arrived with a crushed box and the camera is broken inside. "
                                            "See {PREVIOUS_REF}."},
            other.case_id: {"title": "Too many newsletters", "supporting_information": "", "requested_resolution": "",
                            "description": "I keep getting marketing emails every single day, please stop sending them."},
        }
        cases = load_dataset(specs, texts, password="x")
        self.assertEqual(len(cases), 3)
        first, second, third = (DatasetCase.objects.get(case_id=s.case_id).complaint for s in specs)
        self.assertIn(first.order.order_ref, first.description)
        self.assertEqual(second.previous_complaint, first)  # {PREVIOUS_REF} -> the form field too
        self.assertIn(first.complaint_id, second.description)
        self.assertEqual(second.order, first.order)  # a repeat is about the same order
        self.assertEqual(third.match_type, "")  # the same customer's unrelated complaint is not linked
        self.assertEqual([c.fact_mismatches for c in cases], [[], [], []])
        self.assertEqual(load_dataset(specs, texts, password="x"), [])  # already loaded: nothing twice

        rows = [evaluate_case(s, DatasetCase.objects.get(case_id=s.case_id), {x.case_id: x for x in specs},
                              {c.case_id: c for c in DatasetCase.objects.all()}, ("python",)) for s in specs]
        self.assertTrue(rows[1]["link_correct"])
        self.assertTrue(rows[2]["link_correct"])
        summary = summarize(rows, ("python",))
        self.assertEqual(summary["intake"]["repeat_or_duplicate_cases"], 1)
        self.assertIn("python", summary["accuracy_percent"])

    def test_spread_dates_moves_families_together(self):
        specs = self.make_specs()
        texts = {s.case_id: {"title": "Camera arrived broken", "supporting_information": "", "requested_resolution": "",
                             "description": f"Order {{ORDER_REF}} arrived crushed and the camera is broken, case {s.case_id}. See {{PREVIOUS_REF}}."}
                 for s in specs}
        load_dataset(specs, texts, password="x")
        first, second, _ = (DatasetCase.objects.get(case_id=s.case_id).complaint for s in specs)
        gap_before = (first.created_at.date() - first.order.delivery_date).days
        now = timezone.now()

        self.assertEqual(spread_dates(30, now=now), 3)
        first.refresh_from_db()
        second.refresh_from_db()
        first.order.refresh_from_db()
        self.assertTrue(now - timedelta(days=31) <= first.created_at < second.created_at <= now)  # repeat after original
        self.assertLessEqual(abs((first.created_at.date() - first.order.delivery_date).days - gap_before), 1)  # facts stay true
        self.assertLess(abs(first.audit_log.first().created_at - first.created_at), timedelta(minutes=1))  # history moved too
        if first.sla_response_due:
            self.assertGreater(first.sla_response_due, first.created_at)

        before = [c.created_at for c in (first, second)]
        spread_dates(30, now=now)  # same day, same window: nothing moves
        self.assertEqual([c.created_at for c in Complaint.objects.filter(pk__in=[first.pk, second.pk]).order_by("pk")], before)
