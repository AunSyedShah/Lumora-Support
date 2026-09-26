"""
Calculate the rule-engine facts for a complaint from the linked order - not from the text.

Using real order data means a customer cannot talk their way into a refund window
("I only got it yesterday!") - the dates come from the order record.
"""

from datetime import date

import numpy as np

from rules.conditions import Facts

from .models import Order


def business_days_between(start, end):
    """Mon-Fri days from start (inclusive) to end (exclusive). Policies measure delays in business days."""
    if start is None or end is None or end <= start:
        return 0
    return int(np.busday_count(start, end))


def days_late(order, today):
    if order.status == Order.Status.CANCELLED or order.estimated_delivery_date is None:
        return None
    if order.delivery_date:
        return business_days_between(order.estimated_delivery_date, order.delivery_date)
    return business_days_between(order.estimated_delivery_date, today)


def compute_facts(customer, order, product, metadata, previous_related_count, today=None):
    today = today or date.today()
    facts = {
        "customer_type": customer.customer_type,
        "product": product.name if product else None,
        "amount": None,
        "amount_source": None,
        "days_since_purchase": None,
        "days_since_delivery": None,
        "days_late": None,
        "previous_complaints": previous_related_count,
    }
    if order:
        facts["amount"] = float(order.amount)
        facts["amount_source"] = "order"
        facts["days_since_purchase"] = (today - order.order_date).days
        if order.delivery_date:
            facts["days_since_delivery"] = (today - order.delivery_date).days
        facts["days_late"] = days_late(order, today)
    elif metadata.get("amounts"):
        # Only a claim by the customer: good enough to route a high-value case for review,
        # never used as proof of eligibility.
        facts["amount"] = max(metadata["amounts"])
        facts["amount_source"] = "complaint_text"
    return facts


def rule_facts(complaint):
    """The stored complaint facts as a rules.conditions.Facts object for the rule engine."""
    f = complaint.facts or {}
    return Facts(
        text=f"{complaint.title}. {complaint.description}",
        customer_type=f.get("customer_type"),
        product=f.get("product"),
        amount=f.get("amount"),
        days_since_purchase=f.get("days_since_purchase"),
        days_since_delivery=f.get("days_since_delivery"),
        days_late=f.get("days_late"),
        previous_complaints=f.get("previous_complaints", 0),
    )
