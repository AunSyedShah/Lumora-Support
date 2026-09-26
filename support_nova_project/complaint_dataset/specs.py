"""
Build the 500 complaint specs: WHAT each complaint is about and its expected labels, decided
before any text exists (approach C: Python decides the labels, an LLM only writes the words).

Groups (SRS minimums in brackets):
  core              2-4 complaints per resolution rule, with facts drawn so that exactly that rule applies
  escalation        one escalation trigger each (legal threat, regulator, chargeback, vulnerable customer...)
  calm_critical     a safety hazard mentioned calmly, in passing, inside another complaint
  multi_issue       two or three issues in one complaint                          [25 ambiguous/multi]
  ambiguous         no clear category -> the right outcome is a human review
  incomplete        no order, no dates: eligibility cannot be decided
  difficult_policy  facts exactly on a rule boundary, or the customer cites an outdated / wrong policy [20]
  contradictory     the customer's claims contradict the order records
  policy_exception  asks for an exception outside a policy window
  unsupported_refund asks for a refund / compensation that no rule allows
  prompt_injection  an attack on the AI inserted word for word                   [20]
  near_duplicate    the same complaint submitted again, lightly reworded          [25 repeated/near-dup]
  repeat            the same issue raised again later, in new words
Random choices use a fixed seed, so the same specs are produced on every run.
"""

import random
from dataclasses import asdict, dataclass, field

from catalog.models import Product
from rules.models import EscalationRule, ResolutionRule

from .expected import expected_labels, product_names
from .scenarios import (
    CHANNELS, CUSTOMER_TYPES, DEVICES, EMOTIONAL_STYLES, INJECTION_POSITIONS, INJECTIONS, LENGTHS,
    SAFETY_DETAILS, SCENARIOS, STYLE_WEIGHTS, SUBSCRIPTIONS,
)

TOTAL = 500
TEST_SIZE = 100
SEED = 2026
SHIPPING_DAYS = 7  # calendar days from order to (on-time) delivery, used by the order builder too

# Rules the core group cannot target: their condition is a previous-complaint count (covered by
# the repeat chains) or a days_late fact that order data cannot express for refunds/repairs.
NOT_TARGETED = {"RR-030", "RR-053"}
MARKED_DELIVERED = {"marked as delivered", "says delivered", "shows delivered"}


@dataclass
class Spec:
    case_id: str = ""
    group: str = "core"
    split: str = "dev"
    customer: str = ""
    customer_type: str = "standard"
    channel: str = "web"
    subcategories: list = field(default_factory=list)  # the TRUE issues, most important first
    product: str | None = None
    product_in_field: bool = False
    has_order: bool = False
    order_ref_in: str = ""  # "field" | "text" (placeholder {ORDER_REF} in the text) | ""
    order_status: str = ""
    express: bool = False
    quantity: int = 1
    amount: float | None = None
    days_late: int | None = None
    days_since_delivery: int | None = None
    days_since_purchase: int | None = None
    previous_complaints: int = 0
    related_to: str = ""  # case_id of the earlier complaint (near_duplicate / repeat)
    key_facts: list = field(default_factory=list)  # details in rule-matrix words (the writer paraphrases)
    claims: list = field(default_factory=list)  # things the customer says that are NOT true
    extra: str = ""  # extra instruction for the writer (policy citations, exceptions, ...)
    wants: str = ""
    style: str = "calm"
    length: str = "medium"
    injection: str = ""
    injection_position: str = ""
    target: str = ""  # the rule this spec was built to exercise
    expected: dict = field(default_factory=dict)
    case_types: list = field(default_factory=list)


def _weighted(rng, weights):
    return rng.choices(list(weights), list(weights.values()))[0]


class SpecBuilder:
    def __init__(self, seed=SEED):
        self.rng = random.Random(seed)
        self.names = product_names()
        self.prices = {p.code: float(p.price) for p in Product.objects.all()}
        self.rules = {r.rule_id: r for r in ResolutionRule.objects.filter(is_active=True).select_related("subcategory")}
        self.escalations = {r.rule_id: r for r in EscalationRule.objects.filter(is_active=True)}
        self.name_to_code = {name.lower(): code for code, name in self.names.items()}
        self.specs = []
        self.customer_count = 0
        self.problems = []  # specs that could not be built as intended (reported, never silent)
        self.reachable, self.unreachable = [], []

    # ---------------- basic spec ----------------

    def new_customer(self, spec):
        self.customer_count += 1
        spec.customer = f"ds_c{self.customer_count:04d}"

    def base(self, subcategory, group="core", product=None):
        rng, scenario = self.rng, SCENARIOS[subcategory]
        spec = Spec(group=group, subcategories=[subcategory])
        spec.customer_type = _weighted(rng, CUSTOMER_TYPES)
        spec.channel = _weighted(rng, CHANNELS)
        spec.style = _weighted(rng, STYLE_WEIGHTS)
        spec.length = "short" if spec.style in ("terse", "casual_chat") else rng.choice(["short", "medium", "medium", "long"])
        spec.product = product or rng.choice(scenario.products)
        spec.wants = rng.choice(scenario.wants)
        self.set_order(spec, scenario)
        return spec

    def set_order(self, spec, scenario, days=None):
        """Order facts for the scenario's anchor. `days` overrides the random anchor value."""
        rng = self.rng
        spec.has_order = scenario.anchor != "none"
        spec.days_late = spec.days_since_delivery = spec.days_since_purchase = None
        if not spec.has_order:
            spec.order_ref_in, spec.amount = "", None
            spec.product_in_field = spec.product is not None and rng.random() < 0.7
            return
        if spec.product is None:
            spec.product = rng.choice(DEVICES)
        spec.order_ref_in = "field" if rng.random() < 0.6 else "text"
        spec.product_in_field = rng.random() < 0.3
        is_service = spec.product not in DEVICES
        spec.quantity = 1 if is_service else rng.choices([1, 2], [85, 15])[0]
        spec.amount = round(self.prices[spec.product] * spec.quantity, 2)
        value = days if days is not None else rng.randint(*scenario.days)
        # Express matters only while the order is on its way; the customer then mentions it.
        spec.key_facts = [k for k in spec.key_facts if k != "express delivery"]
        spec.express = scenario.anchor == "pending" and rng.random() < 0.15
        if spec.express:
            spec.key_facts.append("express delivery")

        if scenario.anchor == "pending":
            spec.order_status, spec.days_late = "shipped", value
        elif scenario.anchor == "delivery":
            spec.order_status, spec.days_late = "delivered", (None if is_service else 0)
            spec.days_since_delivery = value
            spec.days_since_purchase = value + (0 if is_service else SHIPPING_DAYS)
        else:  # purchase
            if not is_service:
                value = max(value, SHIPPING_DAYS + 1)
            spec.order_status, spec.days_late = "delivered", (None if is_service else 0)
            spec.days_since_purchase = value
            spec.days_since_delivery = value - (0 if is_service else SHIPPING_DAYS)

    def set_days(self, spec, fact, value):
        """Set one day fact and keep the others consistent with it."""
        scenario = SCENARIOS[spec.subcategories[0]]
        if fact == "days_late":
            spec.days_late = value
        elif fact == "days_since_delivery" and scenario.anchor == "delivery":
            self.set_order_keep(spec, scenario, value)
        elif fact == "days_since_purchase" and scenario.anchor == "purchase":
            self.set_order_keep(spec, scenario, value)

    def set_order_keep(self, spec, scenario, value):
        keep = (spec.order_ref_in, spec.product_in_field, spec.quantity, spec.amount, spec.express, list(spec.key_facts))
        self.set_order(spec, scenario, days=value)
        spec.order_ref_in, spec.product_in_field, spec.quantity, spec.amount, spec.express, spec.key_facts = keep

    @staticmethod
    def anchor_value(spec):
        anchor = SCENARIOS[spec.subcategories[0]].anchor
        return {"pending": spec.days_late, "delivery": spec.days_since_delivery,
                "purchase": spec.days_since_purchase}.get(anchor)

    def set_product(self, spec, code, quantity=1):
        """Change the ordered product (device <-> service changes the order dates too)."""
        spec.product = code
        if spec.has_order:
            self.set_order_keep(spec, SCENARIOS[spec.subcategories[0]], self.anchor_value(spec))
            spec.quantity = 1 if code not in DEVICES else quantity
            spec.amount = round(self.prices[code] * spec.quantity, 2)

    def plain_order(self, spec):
        """One unit, standard shipping: nothing else changes the rule being tested."""
        if spec.has_order and spec.quantity > 1:
            spec.quantity, spec.amount = 1, self.prices[spec.product]
        spec.express = False
        spec.key_facts = [k for k in spec.key_facts if k != "express delivery"]

    def set_amount(self, spec, minimum):
        """Choose a product and quantity whose total is at least `minimum`."""
        allowed = [p for p in SCENARIOS[spec.subcategories[0]].products if p in DEVICES] or DEVICES
        product = spec.product if spec.product in allowed else self.rng.choice(allowed)
        quantity = max(1, -int(-minimum // self.prices[product])) + self.rng.choice([0, 0, 1])
        self.set_product(spec, product, quantity)
        if spec.quantity > 4:
            spec.customer_type = "business"  # a home customer does not order 9 smart locks

    # ---------------- conditions -> facts ----------------

    def apply_conditions(self, spec, conditions):
        rng = self.rng
        for key, value in conditions.items():
            if key == "customer_types":
                spec.customer_type = rng.choice(value)
            elif key == "products":
                self.set_product(spec, self.name_to_code[rng.choice(value).lower()], spec.quantity)
                if not spec.has_order:
                    spec.product_in_field = True
            elif key == "keywords_any":
                phrase = rng.choice(value)
                spec.key_facts.append(phrase)
                if phrase in MARKED_DELIVERED and spec.has_order:
                    spec.order_status, spec.days_late = "delivered", 0
                    spec.days_since_delivery = rng.randint(1, 5)
                    spec.days_since_purchase = spec.days_since_delivery + SHIPPING_DAYS
            elif key == "min_amount":
                if not spec.has_order:
                    return False
                self.set_amount(spec, value)
            elif key == "min_days_late":
                self.set_days(spec, "days_late", rng.randint(int(value), int(value) + 4))
            elif key.startswith(("min_days", "max_days")):
                fact = key[4:]
                low = conditions.get(f"min_{fact}")
                high = conditions.get(f"max_{fact}")
                low = int(low) if low is not None else max(1, int(high) - max(6, int(high) // 2))
                high = int(high) if high is not None else low + max(6, low // 2)
                self.set_days(spec, fact, rng.randint(low, high))
            elif key in ("min_previous_complaints",):
                return False
        return True

    def build_for_rule(self, rule, group="core", tries=80, prepare=None, report=True):
        """Draw random facts that satisfy the rule; keep the draw only if the matrix picks that rule."""
        for _ in range(tries):
            spec = self.base(rule.subcategory.code, group)
            if prepare:
                prepare(spec)
            if not self.apply_conditions(spec, rule.conditions):
                return None
            spec.expected = expected_labels(spec, self.names)
            if spec.expected["rule"] == rule.rule_id:
                spec.target = rule.rule_id
                return spec
        if report:
            self.problems.append(f"{group}: could not build a spec where {rule.rule_id} applies")
        return None

    def add(self, spec):
        if not spec.expected:
            spec.expected = expected_labels(spec, self.names)
        if not spec.customer:
            self.new_customer(spec)
        spec.case_id = f"DS-{len(self.specs) + 1:04d}"
        self.specs.append(spec)
        return spec

    # ---------------- groups ----------------

    def core(self, per_rule=3):
        targets = [r for r in self.rules.values()
                   if "min_previous_complaints" not in r.conditions and r.rule_id not in NOT_TARGETED]
        for rule in sorted(targets, key=lambda r: r.rule_id):
            spec = self.build_for_rule(rule, report=False)
            if spec is None:
                # e.g. RR-107: a no-condition fallback that only applies when the order facts are unknown
                self.unreachable.append(rule.rule_id)
                continue
            self.reachable.append(rule)
            self.add(spec)
            for _ in range(per_rule - 1):
                spec = self.build_for_rule(rule)
                if spec:
                    self.add(spec)

    ESCALATION_TARGETS = {
        "ESC-005": ["ELECTRIC_SHOCK", "OVERHEATING"],
        "ESC-006": ["OVERHEATING", "SMOKE_FIRE", "ELECTRIC_SHOCK"],
        "ESC-008": ["FOOTAGE_EXPOSURE", "UNAUTHORIZED_ACCESS"],
        "ESC-010": ["ACCOUNT_LOCKED", "UNAUTHORIZED_ORDER"],
        "ESC-011": ["HARDWARE_MALFUNCTION", "APP_CONNECTIVITY"],
        "ESC-013": ["REFUND_DENIED", "CLAIM_REJECTED", "INCORRECT_CHARGE", "DAMAGED_IN_TRANSIT"],
        "ESC-014": ["REFUND_DELAY", "DATA_DELETION_REQUEST", "UNEXPECTED_RENEWAL"],
        "ESC-015": ["POOR_COMMUNICATION", "DELAYED_DELIVERY", "STAFF_BEHAVIOUR"],
        "ESC-018": ["UNRESOLVED_PREVIOUS", "REPAIR_DELAY"],
        "ESC-019": ["LOST_PARCEL", "INCORRECT_CHARGE", "REFUND_DELAY"],
        "ESC-020": ["DUPLICATE_CHARGE", "WRONG_ITEM"],
        "ESC-023": ["DUPLICATE_CHARGE", "REFUND_DELAY"],
        "ESC-024": ["MISSED_APPOINTMENT", "HARDWARE_MALFUNCTION", "DELAYED_DELIVERY"],
        "ESC-025": ["HARDWARE_MALFUNCTION", "APP_CONNECTIVITY", "FIRMWARE_UPDATE_FAILURE"],
        "ESC-026": ["HARDWARE_MALFUNCTION", "APP_CONNECTIVITY"],
        "ESC-027": ["STAFF_BEHAVIOUR"],
        "ESC-028": ["FAULTY_INSTALLATION", "STAFF_BEHAVIOUR"],
        "ESC-031": ["UNAUTHORIZED_ORDER", "INCORRECT_CHARGE"],
        "ESC-034": ["DATA_DELETION_REQUEST", "UNWANTED_MARKETING"],
        "ESC-035": ["OVERHEATING", "HARDWARE_MALFUNCTION"],
    }
    DEVICE_FOR_ESCALATION = {"ESC-011": "LOCK", "ESC-025": "THERMO", "ESC-026": "LOCK"}

    def escalation(self, per_rule=2):
        for rule_id, subcategories in self.ESCALATION_TARGETS.items():
            rule = self.escalations[rule_id]
            for i in range(per_rule):
                spec = self._escalation_spec(rule, subcategories[i % len(subcategories)])
                if spec:
                    self.add(spec)

    def _escalation_spec(self, rule, subcategory, tries=40):
        for _ in range(tries):
            spec = self.base(subcategory, "escalation", product=self.DEVICE_FOR_ESCALATION.get(rule.rule_id))
            if spec.product and not spec.has_order:
                spec.product_in_field = True
            conditions = {k: v for k, v in rule.conditions.items() if k not in ("categories", "subcategories")}
            if not self.apply_conditions(spec, conditions):
                return None
            spec.expected = expected_labels(spec, self.names)
            if rule.rule_id in spec.expected["escalation_rules"]:
                spec.target = rule.rule_id
                return spec
        self.problems.append(f"escalation: could not trigger {rule.rule_id} with {subcategory}")
        return None

    CALM_CRITICAL = [
        ("HARDWARE_MALFUNCTION", "burning smell"), ("FIRMWARE_UPDATE_FAILURE", "too hot to touch"),
        ("APP_CONNECTIVITY", "sparks"), ("DEAD_ON_ARRIVAL", "burning plastic"),
        ("DAMAGED_IN_TRANSIT", "exposed wires"), ("REPLACEMENT_REQUEST", "melted"),
        ("HARDWARE_MALFUNCTION", "smoke"), ("FAULTY_INSTALLATION", "tingling"),
        ("DEVICE_PAIRING", "hot to the touch"), ("CLAIM_REJECTED", "scorch marks"),
        ("REFUND_DENIED", "burning smell"), ("MISSING_PARTS", "gave me a shock"),
    ]

    def calm_critical(self):
        for subcategory, detail in self.CALM_CRITICAL:
            product = self.rng.choice(["PLUG", "HUB", "THERMO", "DOORBELL", "BULB"])
            spec = self.base(subcategory, "calm_critical", product=None if subcategory == "FAULTY_INSTALLATION" else product)
            spec.subcategories.append(SAFETY_DETAILS[detail])  # the hazard is the real, most serious issue
            spec.key_facts.append(detail)
            spec.style = "calm"
            spec.extra = (f"Mention the safety detail ({detail}) only briefly and calmly, in passing, "
                          "as if it were not important. The main topic of the complaint is the other problem.")
            self.add(spec)

    MULTI_ISSUE = [
        ["DELAYED_DELIVERY", "POOR_COMMUNICATION"], ["DAMAGED_IN_TRANSIT", "REFUND_DENIED"],
        ["DUPLICATE_CHARGE", "CANCELLATION_ISSUE"], ["WRONG_ITEM", "STAFF_BEHAVIOUR"],
        ["APP_CONNECTIVITY", "FEATURE_UNAVAILABLE"], ["FIRMWARE_UPDATE_FAILURE", "REPLACEMENT_REQUEST"],
        ["MISSED_APPOINTMENT", "POOR_COMMUNICATION"], ["FAULTY_INSTALLATION", "STAFF_BEHAVIOUR"],
        ["UNAUTHORIZED_ACCESS", "ACCOUNT_LOCKED"], ["UNAUTHORIZED_ORDER", "INCORRECT_CHARGE"],
        ["REFUND_DELAY", "POOR_COMMUNICATION"], ["DEAD_ON_ARRIVAL", "MISSING_PARTS"],
        ["UNEXPECTED_RENEWAL", "CANCELLATION_ISSUE"], ["HARDWARE_MALFUNCTION", "CLAIM_REJECTED"],
        ["REPAIR_DELAY", "POOR_COMMUNICATION"], ["INVOICE_ERROR", "INCORRECT_CHARGE"],
        ["DATA_DELETION_REQUEST", "UNWANTED_MARKETING"], ["FOOTAGE_EXPOSURE", "APP_CONNECTIVITY"],
        ["DEVICE_PAIRING", "APP_CONNECTIVITY"], ["PARTIAL_REFUND", "POOR_COMMUNICATION"],
        ["OVERHEATING", "REFUND_DENIED"], ["ELECTRIC_SHOCK", "FAULTY_INSTALLATION"],
        ["REFUND_DENIED", "STAFF_BEHAVIOUR"], ["PLAN_CHANGE", "INCORRECT_CHARGE"],
        ["DELAYED_DELIVERY", "INCORRECT_CHARGE", "POOR_COMMUNICATION"],
        ["ACCOUNT_LOCKED", "POOR_COMMUNICATION", "UNRESOLVED_PREVIOUS"],
    ]

    def multi_issue(self):
        for subcategories in self.MULTI_ISSUE:
            shared = [p for p in SCENARIOS[subcategories[0]].products
                      if all(p in SCENARIOS[s].products or SCENARIOS[s].anchor == "none" for s in subcategories[1:])]
            spec = self.base(subcategories[0], "multi_issue", product=self.rng.choice(shared) if shared else None)
            spec.subcategories = list(subcategories)
            spec.extra = "The complaint is about ALL of these problems; give each one a clear part of the text."
            self.add(spec)

    AMBIGUOUS = [
        ("HUB", "Lumora's products do not do what the advert promised and the customer is disappointed, without saying what exactly is wrong."),
        (None, "Something is wrong with the customer's bill or maybe their subscription, they are not sure which, and they are confused."),
        ("CAM_OUT", "The camera 'isn't right lately' - vague, no clear symptom."),
        (None, "The customer is unhappy with 'the whole experience' with Lumora and wants someone to call them."),
        ("THERMO", "The thermostat 'behaves strangely sometimes' - the customer cannot describe how."),
        (None, "The customer received a letter from Lumora they do not understand and asks what it means."),
        ("DOORBELL", "The doorbell 'is not as good as the old one' - a general disappointment."),
        (None, "The customer wants to 'sort things out' with their account, without saying what the problem is."),
        ("PLUG", "The plugs 'don't seem to save any energy' - not a fault, not a billing issue, just unmet expectations."),
        (None, "The customer asks a general question about which Lumora products work together and complains that the website is confusing."),
        ("LOCK", "The lock 'feels unreliable' - the customer cannot say what happened."),
        (None, "The customer says 'you know what the problem is, I've told you before' and gives no details."),
    ]

    def ambiguous(self):
        for product, situation in self.AMBIGUOUS:
            spec = self.base("POOR_COMMUNICATION", "ambiguous", product=product)
            spec.subcategories = []
            spec.has_order, spec.order_ref_in, spec.amount = False, "", None
            spec.days_late = spec.days_since_delivery = spec.days_since_purchase = None
            spec.product_in_field = product is not None and self.rng.random() < 0.5
            spec.extra = f"Situation: {situation} Do not make it clearer than this."
            spec.wants = "someone to help"
            self.add(spec)

    INCOMPLETE = ["DAMAGED_IN_TRANSIT", "WRONG_ITEM", "REFUND_DENIED", "DEAD_ON_ARRIVAL", "HARDWARE_MALFUNCTION",
                  "MISSING_PARTS", "UNEXPECTED_RENEWAL", "DELAYED_DELIVERY", "LOST_PARCEL", "REPLACEMENT_REQUEST",
                  "INCORRECT_CHARGE", "REFUND_DELAY", "CLAIM_REJECTED", "DUPLICATE_CHARGE", "MISSED_APPOINTMENT"]

    def incomplete(self):
        for subcategory in self.INCOMPLETE:
            spec = self.base(subcategory, "incomplete")
            spec.has_order, spec.order_ref_in, spec.amount = False, "", None
            spec.days_late = spec.days_since_delivery = spec.days_since_purchase = None
            spec.product_in_field = self.rng.random() < 0.4
            spec.length = "short"
            spec.extra = "Leave out important details: no order number, no dates and no amounts."
            self.add(spec)

    # (subcategory, fact, value, customer_type, what the customer writes about the policy)
    DIFFICULT = [
        ("DELAYED_DELIVERY", "days_late", 5, None, ""), ("DELAYED_DELIVERY", "days_late", 6, None, ""),
        ("DELAYED_DELIVERY", "days_late", 10, None, ""), ("DELAYED_DELIVERY", "days_late", 11, None, ""),
        ("DAMAGED_IN_TRANSIT", "days_since_delivery", 7, None, ""), ("DAMAGED_IN_TRANSIT", "days_since_delivery", 8, None, ""),
        ("REFUND_DENIED", "days_since_delivery", 30, None, ""), ("REFUND_DENIED", "days_since_delivery", 31, None, ""),
        ("HARDWARE_MALFUNCTION", "days_since_purchase", 365, "standard", ""), ("HARDWARE_MALFUNCTION", "days_since_purchase", 366, "standard", ""),
        ("HARDWARE_MALFUNCTION", "days_since_purchase", 1095, "premium", ""), ("HARDWARE_MALFUNCTION", "days_since_purchase", 1096, "premium", ""),
        ("UNEXPECTED_RENEWAL", "days_since_purchase", 14, None, ""), ("UNEXPECTED_RENEWAL", "days_since_purchase", 15, None, ""),
        ("WRONG_ITEM", "days_since_delivery", 14, None, ""), ("WRONG_ITEM", "days_since_delivery", 15, None, ""),
        # the customer relies on a document that is outdated or wrong
        ("DELAYED_DELIVERY", "days_late", 2, None, "Your FAQ says every late delivery gets a 10 USD voucher, so I expect my voucher."),
        ("DELAYED_DELIVERY", "days_late", 3, None, "The FAQ on your website promises a 10 USD voucher for late deliveries."),
        ("REFUND_DENIED", "days_since_delivery", 20, None, "The agent said refunds are only possible within 14 days, but I am not sure that is right."),
        ("REFUND_DENIED", "days_since_delivery", 22, None, "I read in your refund policy (version 1.0) that I only have 14 days, is that still true?"),
        ("REFUND_DENIED", "days_since_delivery", 45, None, "I am sure your policy gives customers 60 days for refunds."),
        ("HARDWARE_MALFUNCTION", "days_since_purchase", 500, "premium", "As a LumoraCare+ member I believe my warranty is longer than one year."),
        ("DEAD_ON_ARRIVAL", "days_since_delivery", 10, None, "I read that dead devices are always refunded in full, no matter when."),
        ("MISSING_PARTS", "days_since_delivery", 20, None, "I think missing parts are always sent for free."),
        ("UNEXPECTED_RENEWAL", "days_since_purchase", 30, None, "I thought renewals could be refunded at any time."),
    ]

    def difficult_policy(self):
        for subcategory, fact, value, customer_type, citation in self.DIFFICULT:
            spec = self.base(subcategory, "difficult_policy")
            self.plain_order(spec)
            if customer_type:
                spec.customer_type = customer_type
            self.set_days(spec, fact, value)
            if citation:
                spec.extra = f"The customer writes this about the policy, in their own words: \"{citation}\""
            self.add(spec)

    # (subcategory, fact, true value, customer_type, what the customer claims)
    CONTRADICTORY = [
        ("DAMAGED_IN_TRANSIT", "days_since_delivery", 20, None, "The parcel arrived yesterday."),
        ("REFUND_DENIED", "days_since_delivery", 45, None, "I asked for the refund well within 30 days of delivery."),
        ("HARDWARE_MALFUNCTION", "days_since_purchase", 500, "standard", "I bought it only three months ago."),
        ("HARDWARE_MALFUNCTION", "days_since_purchase", 420, "standard", "I am a LumoraCare+ premium member."),
        ("DUPLICATE_CHARGE", None, None, None, "I was charged 900 USD twice."),
        ("DELAYED_DELIVERY", "days_late", 3, None, "I paid for express next-day delivery."),
        ("WRONG_ITEM", "days_since_delivery", 25, None, "It was delivered two days ago."),
        ("DEAD_ON_ARRIVAL", "days_since_delivery", 15, None, "I opened it the day it arrived, this week."),
        ("MISSING_PARTS", "days_since_delivery", 22, None, "I only just received it."),
        ("UNEXPECTED_RENEWAL", "days_since_purchase", 35, None, "The renewal charge was taken a few days ago."),
        ("LOST_PARCEL", "days_late", 3, None, "It has been missing for over a month."),
        ("REPLACEMENT_REQUEST", "days_since_purchase", 400, None, "It is still under the one-year warranty."),
    ]

    def contradictory(self):
        for subcategory, fact, value, customer_type, claim in self.CONTRADICTORY:
            spec = self.base(subcategory, "contradictory")
            self.plain_order(spec)
            if customer_type:
                spec.customer_type = customer_type
            if fact:
                self.set_days(spec, fact, value)
            if subcategory == "DUPLICATE_CHARGE":
                self.set_product(spec, "PLUG")
            if "express" in claim:  # the order was NOT express
                spec.express = False
                spec.key_facts = [k for k in spec.key_facts if k != "express delivery"]
            spec.claims = [claim]
            self.add(spec)

    EXCEPTIONS = [
        ("REFUND_DENIED", "days_since_delivery", 40), ("REFUND_DENIED", "days_since_delivery", 55),
        ("HARDWARE_MALFUNCTION", "days_since_purchase", 450), ("HARDWARE_MALFUNCTION", "days_since_purchase", 600),
        ("WRONG_ITEM", "days_since_delivery", 20), ("DAMAGED_IN_TRANSIT", "days_since_delivery", 15),
        ("MISSING_PARTS", "days_since_delivery", 25), ("UNEXPECTED_RENEWAL", "days_since_purchase", 25),
        ("REPLACEMENT_REQUEST", "days_since_purchase", 420), ("DEAD_ON_ARRIVAL", "days_since_delivery", 18),
        ("CLAIM_REJECTED", "days_since_purchase", 200), ("PARTIAL_REFUND", "days_since_delivery", 30),
    ]
    EXCEPTION_WORDS = ["make an exception", "goodwill", "outside the return window", "bend the rules", "exception"]

    def policy_exception(self):
        for i, (subcategory, fact, value) in enumerate(self.EXCEPTIONS):
            spec = self.base(subcategory, "policy_exception")
            self.plain_order(spec)
            spec.customer_type = "standard"
            self.set_days(spec, fact, value)
            spec.key_facts.append(self.EXCEPTION_WORDS[i % len(self.EXCEPTION_WORDS)])
            spec.extra = "The customer knows they are outside the policy and asks Lumora to make an exception as a goodwill gesture."
            self.add(spec)

    UNSUPPORTED = [
        ("DELAYED_DELIVERY", "days_late", 2), ("DEVICE_PAIRING", None, None), ("APP_CONNECTIVITY", None, None),
        ("PLAN_CHANGE", None, None), ("INVOICE_ERROR", None, None), ("HARDWARE_MALFUNCTION", "days_since_purchase", 700),
        ("WRONG_ITEM", "days_since_delivery", 18), ("MISSING_PARTS", "days_since_delivery", 30),
        ("PARTIAL_REFUND", None, None), ("POOR_COMMUNICATION", None, None), ("DELAYED_DELIVERY", "days_late", 4),
        ("REPAIR_DELAY", None, None),
    ]

    def unsupported_refund(self):
        for subcategory, fact, value in self.UNSUPPORTED:
            spec = self.base(subcategory, "unsupported_refund")
            self.plain_order(spec)
            spec.customer_type = "standard"
            if fact:
                self.set_days(spec, fact, value)
            spec.wants = "a full refund plus extra compensation for the trouble"
            spec.extra = "The customer insists on a full refund AND extra compensation (money or a voucher)."
            self.add(spec)

    def prompt_injection(self, count=24):
        pool = [s for s in SCENARIOS if s not in ("UNRESOLVED_PREVIOUS",)]
        safety_first = ["OVERHEATING", "SMOKE_FIRE", "ELECTRIC_SHOCK", "FOOTAGE_EXPOSURE", "UNAUTHORIZED_ACCESS"]
        for i in range(count):
            subcategory = safety_first[i] if i < len(safety_first) else self.rng.choice(pool)
            spec = self.base(subcategory, "prompt_injection")
            spec.injection = INJECTIONS[i % len(INJECTIONS)]
            spec.injection_position = INJECTION_POSITIONS[i % len(INJECTION_POSITIONS)]
            self.add(spec)

    # ---------------- repeated complaints ----------------

    def _copy_as(self, original, group, previous):
        spec = Spec(**{k: (list(v) if isinstance(v, list) else v) for k, v in asdict(original).items()})
        spec.case_id, spec.group, spec.split, spec.expected, spec.case_types = "", group, "dev", {}, []
        spec.related_to, spec.previous_complaints = original.case_id, previous
        spec.target, spec.injection, spec.injection_position = "", "", ""
        spec.style = _weighted(self.rng, STYLE_WEIGHTS)
        if spec.style in ("terse", "casual_chat"):
            spec.length = "short"
        return spec

    def near_duplicates(self, count=12):
        originals = self.rng.sample([s for s in self.specs if s.group == "core" and not s.related_to], count)
        for original in originals:
            spec = self._copy_as(original, "near_duplicate", 1)
            spec.style = original.style
            spec.extra = "near-duplicate"  # the generator rewords the original text lightly
            self.add(spec)

    REPEAT_CHAINS = [  # (subcategory, number of follow-up complaints)
        ("DELAYED_DELIVERY", 2), ("WRONG_ITEM", 2), ("DUPLICATE_CHARGE", 2), ("HARDWARE_MALFUNCTION", 2),
        ("APP_CONNECTIVITY", 2), ("CANCELLATION_ISSUE", 2), ("POOR_COMMUNICATION", 2), ("FEATURE_UNAVAILABLE", 2),
        ("DATA_DELETION_REQUEST", 1), ("MISSED_APPOINTMENT", 1), ("UNWANTED_MARKETING", 1),
    ]

    def repeats(self):
        used = {s.customer for s in self.specs if s.related_to}
        for subcategory, follow_ups in self.REPEAT_CHAINS:
            candidates = [s for s in self.specs if s.group == "core" and s.subcategories == [subcategory]
                          and s.customer not in used]
            previous = self.rng.choice(candidates)
            used.add(previous.customer)
            for n in range(1, follow_ups + 1):
                spec = self._copy_as(previous, "repeat", n)
                spec.key_facts = [k for k in spec.key_facts]
                spec.extra = (f"This is follow-up number {n}: the customer already complained about this "
                              f"{'once' if n == 1 else f'{n} times'} and nothing has been fixed. Write it in "
                              "completely new words, not a copy of an earlier complaint.")
                previous = self.add(spec)

    def shared_customers(self, pairs=20):
        """Give some customers a second, UNRELATED complaint: these must NOT be linked as repeats."""
        singles = [s for s in self.specs if s.group == "core" and not s.related_to
                   and not any(o.related_to == s.case_id for o in self.specs)]
        self.rng.shuffle(singles)
        made, used = 0, set()
        for a in singles:
            if made == pairs:
                break
            for b in singles:
                if (b is not a and a.case_id not in used and b.case_id not in used
                        and b.customer_type == a.customer_type
                        and b.expected["category"] != a.expected["category"]):
                    b.customer = a.customer
                    used |= {a.case_id, b.case_id}
                    made += 1
                    break
        return made

    # ---------------- finishing ----------------

    def top_up(self, total=TOTAL):
        """More core complaints (round-robin over the rules) until the dataset has `total` complaints."""
        order = self.rng.sample(self.reachable, len(self.reachable))
        i = 0
        while len(self.specs) < total:
            spec = self.build_for_rule(order[i % len(order)])
            if spec:
                self.add(spec)
            i += 1

    def tag(self, spec):
        e = spec.expected
        tags = {spec.group}
        if spec.group == "core" and not spec.key_facts:
            tags.add("simple")
        if len(spec.subcategories) > 1:
            tags.add("multi_issue")
        if spec.style in EMOTIONAL_STYLES:
            tags.add("emotional")
        if e["priority"] in ("P0", "P1"):
            tags.add("high_priority")
        if e["priority"] == "P3":
            tags.add("low_priority")
        if spec.group in ("near_duplicate", "repeat"):
            tags.add("repeated")
        if e["category"] == "ACCOUNT_SECURITY" or "ACCOUNT_SECURITY" in e["supporting"]:
            tags.add("security")
        if e["category"] == "PRIVACY" or "PRIVACY" in e["supporting"]:
            tags.add("privacy")
        if e["category"] == "SAFETY" or "PRODUCT_SAFETY" in [e["department"]] + e["supporting"]:
            tags.add("safety")
        if spec.style == "calm" and e["priority"] == "P0":
            tags.add("calm_critical")
        spec.case_types = sorted(tags)

    def assign_split(self, test_size=TEST_SIZE):
        """Hold out ~20% of every group as the unseen test set. Linked complaints stay together."""
        chains = {}
        for spec in self.specs:
            root = spec
            while root.related_to:
                root = next(s for s in self.specs if s.case_id == root.related_to)
            chains.setdefault(root.case_id, []).append(spec)
        by_group = {}
        for chain in chains.values():
            by_group.setdefault(chain[-1].group, []).append(chain)
        share = test_size / len(self.specs)
        chosen = []
        for group, group_chains in sorted(by_group.items()):
            self.rng.shuffle(group_chains)
            want = round(sum(len(c) for c in group_chains) * share)
            taken = 0
            for chain in group_chains:
                if taken >= want:
                    break
                chosen.append(chain)
                taken += len(chain)
        for chain in chosen:
            for spec in chain:
                spec.split = "test"
        singles = [chain[0] for group_chains in by_group.values() for chain in group_chains
                   if len(chain) == 1 and chain[0].split == "dev" and chain[0].group == "core"]
        self.rng.shuffle(singles)
        missing = test_size - sum(s.split == "test" for s in self.specs)
        for spec in singles[:max(0, missing)]:
            spec.split = "test"

    def build(self):
        self.core()
        self.escalation()
        self.calm_critical()
        self.multi_issue()
        self.ambiguous()
        self.incomplete()
        self.difficult_policy()
        self.contradictory()
        self.policy_exception()
        self.unsupported_refund()
        self.prompt_injection()
        self.near_duplicates()
        self.repeats()
        self.top_up()
        self.shared_customers()
        for spec in self.specs:
            spec.expected = expected_labels(spec, self.names)  # after all facts are final
            self.tag(spec)
        self.assign_split()
        return self.specs


def build_specs(seed=SEED):
    builder = SpecBuilder(seed)
    specs = builder.build()
    return specs, builder.problems
