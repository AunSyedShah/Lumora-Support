"""
Expected labels (the "answer key") for a dataset complaint.

The expected result is the Complaint Resolution Rule Matrix applied to the TRUE scenario of the
complaint - the subcategories, order facts and details we decided when writing the spec - never
to the generated text. The pipelines only see the text and the order records, so they are graded
on understanding the complaint, not on reproducing our own classification of it.

Note: this reuses the rule engine's combination logic (most specific rule wins, every escalation
rule applies). That logic has its own unit tests; the dataset tests classification, fact
extraction and trigger detection.
"""

from catalog.models import Product
from rules.conditions import Facts
from rules.engine import evaluate

# A human should look at these whatever the rules say: no clear category, an attack on the AI,
# or too little information to decide eligibility.
REVIEW_GROUPS = {"ambiguous", "prompt_injection", "incomplete"}


def product_names():
    return dict(Product.objects.values_list("code", "name"))


def spec_facts(spec, names):
    known_product = spec.product and (spec.has_order or spec.product_in_field)
    return Facts(
        text=". ".join(spec.key_facts),
        customer_type=spec.customer_type,
        product=names.get(spec.product) if known_product else None,
        amount=spec.amount if spec.has_order else None,
        days_since_purchase=spec.days_since_purchase,
        days_since_delivery=spec.days_since_delivery,
        days_late=spec.days_late,
        previous_complaints=spec.previous_complaints,
    )


def expected_labels(spec, names=None):
    if spec.group == "ambiguous":  # no single right category: the right outcome is a human review
        return {"category": "", "subcategory": "", "secondary": [], "department": "", "supporting": [],
                "urgency": "", "priority": "", "escalation": "", "escalation_rules": [], "rule": "",
                "compensation": [], "missing_facts": [], "review_required": True}

    view = evaluate(spec_facts(spec, names or product_names()), subcategory_code=spec.subcategories)
    return {
        "category": view["category"],
        "subcategory": view["subcategory"],
        "secondary": [s["subcategory"] for s in view["secondary_issues"]],
        "department": view["department"],
        "supporting": view["supporting_departments"],
        "urgency": view["urgency"],
        "priority": view["priority"],
        "escalation": view["escalation_level"],
        "escalation_rules": [e["rule_id"] for e in view["escalation_rules"]],
        "rule": view["resolution_rule"] or "",
        "compensation": view["allowed_compensation"],
        "missing_facts": view["missing_facts"],
        "review_required": view["needs_manual_review"] or spec.group in REVIEW_GROUPS,
    }
