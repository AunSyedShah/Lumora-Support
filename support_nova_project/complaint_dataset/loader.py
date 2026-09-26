"""
Step 3 of the dataset: put the 500 complaints into the database the same way a customer would.

For every case (in case-id order, so an original is always submitted before its repeats):
  1. the dataset customer (ds_c0001 ...) with the spec's customer type
  2. the order, dated so the calculated facts equal the spec (orders.py); repeats reuse the original's order
  3. the {ORDER_REF} / {PREVIOUS_REF} placeholders are filled in
  4. complaints.services.submit_complaint - the normal intake: sanitising, injection flags,
     duplicate / repeat detection, fact calculation. No processing here (evaluate_dataset does that).
Then the facts the system calculated are compared with the spec, and differences are recorded.
"""

import os
from datetime import date

from django.contrib.auth.hashers import make_password
from django.db import transaction

from accounts.models import User
from catalog.models import Product
from complaints.models import Order
from complaints.services import ComplaintValidationError, submit_complaint

from .models import DatasetCase
from .orders import order_fields, order_ref

CHECKED_FACTS = ("customer_type", "amount", "days_late", "days_since_delivery", "days_since_purchase",
                 "previous_complaints")


def dataset_customer(spec, password_hash):
    # The password is hashed once for all ~460 customers: hashing is deliberately slow (about 1 s each).
    user, _ = User.objects.get_or_create(
        username=spec.customer,
        defaults={"role": User.Role.CUSTOMER, "customer_type": spec.customer_type, "password": password_hash,
                  "email": f"{spec.customer}@example.com", "first_name": "Dataset", "last_name": spec.customer},
    )
    return user


def root_case(spec, by_id):
    while spec.related_to:
        spec = by_id[spec.related_to]
    return spec


def fact_mismatches(spec, complaint):
    """Spec facts the system calculated differently (None in the spec = not part of the scenario)."""
    wanted = {"customer_type": spec.customer_type, "amount": spec.amount if spec.has_order else None,
              "days_late": spec.days_late, "days_since_delivery": spec.days_since_delivery,
              "days_since_purchase": spec.days_since_purchase, "previous_complaints": spec.previous_complaints}
    got = complaint.facts
    return [f"{name}: spec {wanted[name]}, system {got.get(name)}" for name in CHECKED_FACTS
            if wanted[name] is not None and got.get(name) != wanted[name]]


def fill(text, order, previous):
    text = text.replace("{ORDER_REF}", order.order_ref if order else "")
    return text.replace("{PREVIOUS_REF}", previous.complaint_id if previous else "my earlier complaint")


@transaction.atomic
def load_case(spec, text, by_id, today, password_hash):
    customer = dataset_customer(spec, password_hash)
    products = {p.code: p for p in Product.objects.all()}

    order = None
    if spec.has_order:
        root = root_case(spec, by_id)  # repeats and duplicates are about the original order
        order = Order.objects.filter(order_ref=order_ref(root.case_id)).first()
        if order is None:
            order = Order.objects.create(order_ref=order_ref(root.case_id), customer=customer,
                                         product=products[spec.product], **order_fields(spec, today))

    previous = None
    if spec.related_to:
        earlier = DatasetCase.objects.filter(case_id=spec.related_to).select_related("complaint").first()
        previous = earlier.complaint if earlier else None

    title, description = fill(text["title"], order, previous), fill(text["description"], order, previous)
    data = {
        "title": title[:200],
        "description": description,
        "product": spec.product if spec.product_in_field else None,
        # the order number goes in the form field, unless the customer wrote it in the text
        "order_ref": order.order_ref if order and "{ORDER_REF}" not in text["description"] else None,
        "channel": spec.channel,
        "requested_resolution": fill(text["requested_resolution"], order, previous)[:500],
        "supporting_information": fill(text["supporting_information"], order, previous),
        # a customer who quotes the earlier complaint number usually fills in the field too
        "previous_complaint_ref": previous.complaint_id if previous and "{PREVIOUS_REF}" in text["description"] else None,
    }
    case = DatasetCase(case_id=spec.case_id, split=spec.split, group=spec.group)
    try:
        complaint, _ = submit_complaint(data, customer, submitted_by=customer)
    except ComplaintValidationError as e:
        case.load_note = f"Rejected at intake: {e}"[:300]
        case.save()
        return case
    case.complaint = complaint
    case.fact_mismatches = fact_mismatches(spec, complaint)
    case.save()
    return case


def load_dataset(specs, texts, today=None, password=None):
    """texts: {case_id: {title, description, requested_resolution, supporting_information}}."""
    today = today or date.today()
    password_hash = make_password(password or os.getenv("DEMO_PASSWORD", "Lumora@2026"))
    by_id = {s.case_id: s for s in specs}
    loaded = set(DatasetCase.objects.values_list("case_id", flat=True))
    results = []
    for spec in sorted(specs, key=lambda s: s.case_id):
        if spec.case_id in loaded or spec.case_id not in texts:
            continue
        results.append(load_case(spec, texts[spec.case_id], by_id, today, password_hash))
    return results


def remove_dataset():
    """Delete everything the loader created: the ds_ customers (their complaints and orders go with them)."""
    DatasetCase.objects.all().delete()
    deleted, _ = User.objects.filter(username__startswith="ds_c", role=User.Role.CUSTOMER).delete()
    return deleted
