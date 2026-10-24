"""
Placing, cancelling and fulfilling shop orders.

The server decides everything that costs money or promises a date: the price comes from the product, the
express fee and the delivery estimate from settings. The browser only says what it wants.
No payment is taken: Lumora arranges payment on delivery.
"""

import re
from datetime import date, timedelta

import numpy as np
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from catalog.models import Product

from .models import Order

REF = re.compile(r"^ORD-(\d{5})$")
FIRST_REF = 10001
SIMULATED_REFS_FROM = 60000  # the dataset's orders (ORD-6xxxx and up) are not part of the shop's own numbering
DUPLICATE_WINDOW = timedelta(seconds=60)
ADDRESS_MIN, ADDRESS_MAX = 10, 500


class OrderError(Exception):
    def __init__(self, message, status=400, existing=None):
        super().__init__(message)
        self.status = status
        self.existing = existing  # the order a duplicate click would have repeated


def business_day(start, days):
    return date.fromisoformat(str(np.busday_offset(start, days, roll="forward")))


def delivery_estimate(order_date, express):
    """Dispatch is the next business day; the policy then counts 3-5 (standard) or 1-2 (express) business days from dispatch."""
    days = settings.EXPRESS_DELIVERY_DAYS if express else settings.STANDARD_DELIVERY_DAYS
    return business_day(order_date, days)


def express_fee():
    return settings.EXPRESS_SHIPPING_FEE


def _next_ref():
    taken = [int(m.group(1)) for ref in Order.objects.filter(order_ref__regex=r"^ORD-[0-9]{5}$", order_ref__lt=f"ORD-{SIMULATED_REFS_FROM}").values_list("order_ref", flat=True) if (m := REF.match(ref))]
    return f"ORD-{max(taken, default=FIRST_REF - 1) + 1}"


def place_order(customer, product_code, quantity, express, address):
    """Create an order for a customer. Raises OrderError with a message that is fine to show them."""
    product = Product.objects.filter(code=product_code, is_active=True).first()
    if product is None:
        raise OrderError("That product is not available.", 404)
    if not 1 <= quantity <= settings.ORDER_MAX_QUANTITY:
        raise OrderError(f"You can order between 1 and {settings.ORDER_MAX_QUANTITY} at a time.")
    is_service = product.kind == Product.Kind.SERVICE
    address = re.sub(r"[ \t]+", " ", (address or "").strip())
    if is_service:
        quantity, express, address = 1, False, ""  # nothing is shipped
    elif not ADDRESS_MIN <= len(address) <= ADDRESS_MAX:
        raise OrderError(f"Please enter the full delivery address ({ADDRESS_MIN}-{ADDRESS_MAX} characters).")

    now = timezone.now()
    if Order.objects.filter(customer=customer, order_date=timezone.localdate()).count() >= settings.ORDER_MAX_PER_DAY:
        raise OrderError("You have placed a lot of orders today. Please contact us if you need more.", 429)
    repeat = Order.objects.filter(customer=customer, product=product, quantity=quantity, express=express, delivery_address=address,
                                  status=Order.Status.PROCESSING, placed_at__gte=now - DUPLICATE_WINDOW).first() if not is_service else None
    if repeat:
        raise OrderError(f"You just placed this order ({repeat.order_ref}). Check My orders before ordering again.", 409, existing=repeat.order_ref)

    today = timezone.localdate()
    details = {"customer": customer, "product": product, "quantity": quantity, "amount": product.price * quantity, "order_date": today, "placed_at": now}
    if is_service:
        details.update(status=Order.Status.DELIVERED, delivery_date=today)  # active straight away
    else:
        details.update(status=Order.Status.PROCESSING, express=express, shipping_fee=express_fee() if express else 0,
                       estimated_delivery_date=delivery_estimate(today, express), delivery_address=address)
    for _ in range(5):  # two customers ordering at the same moment can pick the same number: take the next one
        try:
            with transaction.atomic():
                return Order.objects.create(order_ref=_next_ref(), **details)
        except IntegrityError:
            continue
    raise OrderError("We could not place your order just now. Please try again.", 503)


def cancel_order(order):
    """Customers can cancel until the order is dispatched (Cancellation Policy 2.1: refunded in full)."""
    if order.status != Order.Status.PROCESSING:
        raise OrderError("This order has already been dispatched, so it can no longer be cancelled. Once it arrives you can return it.", 409)
    order.status = Order.Status.CANCELLED
    order.save(update_fields=["status"])
    return order


NEXT_STATUS = {Order.Status.PROCESSING: Order.Status.SHIPPED, Order.Status.SHIPPED: Order.Status.DELIVERED}


def advance_order(order, status):
    """Staff move an order forward, one step at a time: processing -> shipped -> delivered."""
    if NEXT_STATUS.get(order.status) != status:
        raise OrderError(f"An order that is {order.get_status_display().lower()} cannot be marked {status}.", 409)
    order.status = status
    if status == Order.Status.DELIVERED:
        order.delivery_date = timezone.localdate()
    order.save(update_fields=["status", "delivery_date"])
    return order
