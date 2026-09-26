"""
Build the order record for a dataset complaint so that the facts the system CALCULATES from it
(days late, days since delivery / purchase, amount) are exactly the facts in the spec.

Dates are relative to the day the dataset is loaded, so the facts stay right whenever it is loaded.
"""

from datetime import timedelta

from complaints.facts import business_days_between

from .scenarios import DEVICES
from .specs import SHIPPING_DAYS

EXPRESS_SHIPPING_DAYS = 3


def date_business_days_before(end, days):
    """The latest date d with business_days_between(d, end) == days."""
    d = end
    while business_days_between(d, end) < days:
        d -= timedelta(days=1)
    return d


def order_fields(spec, today):
    """Keyword arguments for Order.objects.create (without order_ref, customer and product)."""
    fields = {"quantity": spec.quantity, "amount": spec.amount, "express": spec.express}
    if spec.order_status == "shipped":  # still on its way: only days_late matters
        estimated = date_business_days_before(today, spec.days_late)
        shipping = EXPRESS_SHIPPING_DAYS if spec.express else SHIPPING_DAYS
        return {**fields, "status": "shipped", "order_date": estimated - timedelta(days=shipping),
                "estimated_delivery_date": estimated, "delivery_date": None}

    delivery = today - timedelta(days=spec.days_since_delivery)
    if spec.product not in DEVICES:  # a service starts on the day it is bought
        return {**fields, "status": "delivered", "order_date": delivery,
                "estimated_delivery_date": None, "delivery_date": delivery}
    estimated = date_business_days_before(delivery, spec.days_late or 0)
    return {**fields, "status": "delivered", "order_date": estimated - timedelta(days=SHIPPING_DAYS),
            "estimated_delivery_date": estimated, "delivery_date": delivery}


def order_ref(case_id):
    """DS-0042 -> ORD-60042 (the intake recognises ORD- + 5 digits in complaint text)."""
    return f"ORD-{60000 + int(case_id.split('-')[1])}"
