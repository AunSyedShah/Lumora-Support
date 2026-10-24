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
import random
from datetime import date, timedelta

from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from accounts.models import User
from catalog.models import Product
from complaints.models import Complaint, Order
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


def spread_dates(days, now=None):
    """
    Spread the loaded dataset over the last `days` days, so daily volumes, trends and SLA ages look
    like a working support desk instead of 500 complaints arriving in one afternoon.

    A family (an original and its repeats/duplicates) moves together: families are placed across the
    window in complaint-number order, members follow their original by about a day each, and every
    timestamp of a complaint (deadlines, audit, notes, analyses, validations) plus its order's dates
    move by the same amount - so facts such as "delivered 3 days before the complaint" stay true.
    Deterministic: the same `days` on the same day gives the same dates.
    """
    now = now or timezone.now()
    cases = {c.complaint_id: c for c in DatasetCase.objects.filter(complaint__isnull=False).select_related("complaint")}

    def root_of(pk):
        seen = set()
        while pk not in seen:
            seen.add(pk)
            complaint = cases[pk].complaint
            parent = complaint.related_complaint_id or complaint.previous_complaint_id
            if parent not in cases:
                return pk
            pk = parent
        return pk

    families = {}
    for pk in sorted(cases):
        families.setdefault(root_of(pk), []).append(cases[pk].complaint)
    roots = sorted(families)  # complaint pk order = submission order
    moved = 0
    for position, root_pk in enumerate(roots):
        members = families[root_pk]
        rng = random.Random(root_pk)
        days_back = days * (1 - (position + 1) / len(roots)) + rng.uniform(0, 1)
        start = timezone.localtime(now - timedelta(days=days_back)).replace(hour=rng.randint(8, 19), minute=rng.randint(0, 59))
        for i, complaint in enumerate(members):
            target = min(start + timedelta(hours=i * rng.randint(18, 40)), now - timedelta(minutes=5 * (len(members) - i)))
            delta = target - complaint.created_at
            if i == 0 and complaint.order_id:  # the family's shared order moves with its original
                _shift_order(complaint.order, timedelta(days=round(delta.total_seconds() / 86400)))
            _shift_complaint(complaint, delta)
            moved += 1
    return moved


def _shift_order(order, shift):
    for field in ("order_date", "estimated_delivery_date", "delivery_date"):
        if getattr(order, field) is not None:
            setattr(order, field, getattr(order, field) + shift)
    order.save(update_fields=["order_date", "estimated_delivery_date", "delivery_date"])


COMPLAINT_TIMES = ("created_at", "response_sent_at", "sla_response_due", "sla_resolution_due", "sla_clock_start",
                   "awaiting_since", "first_response_at", "resolved_at", "closed_at", "follow_up_due", "follow_up_done_at")


def _shift_complaint(complaint, delta):
    Complaint.objects.filter(pk=complaint.pk).update(**{
        f: F(f) + delta for f in COMPLAINT_TIMES if getattr(complaint, f) is not None
    })
    for related in (complaint.audit_log, complaint.notes, complaint.genai_analyses, complaint.validations):
        related.update(created_at=F("created_at") + delta)
    complaint.attachments.update(uploaded_at=F("uploaded_at") + delta)


def remove_dataset():
    """Delete everything the loader created: the ds_ customers (their complaints and orders go with them)."""
    DatasetCase.objects.all().delete()
    deleted, _ = User.objects.filter(username__startswith="ds_c", role=User.Role.CUSTOMER).delete()
    return deleted
