from datetime import timedelta
from decimal import Decimal

from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.auth import ACCESS, create_token
from accounts.models import User
from catalog.models import Product

from .facts import business_days_between
from .models import Order

ADDRESS = "12 Garden Road, Gulberg, Lahore 54000"


class ShopOrderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_catalog", verbosity=0)
        cls.alice = User.objects.create_user("alice", password="x", email="alice@example.com", first_name="Alice")
        cls.bob = User.objects.create_user("bob", password="x")
        cls.agent = User.objects.create_user("agent1", password="x", role=User.Role.AGENT)
        cls.manager = User.objects.create_user("manager1", password="x", role=User.Role.MANAGER)
        cls.plug = Product.objects.get(code="PLUG")
        cls.service = Product.objects.filter(kind="service").first()

    def headers(self, user):
        return {"HTTP_AUTHORIZATION": f"Bearer {create_token(user, ACCESS)}"}

    def order(self, user=None, **body):
        payload = {"product": "PLUG", "quantity": 1, "express": False, "delivery_address": ADDRESS, **body}
        return self.client.post("/api/orders", payload, content_type="application/json", **self.headers(user or self.alice))

    # ---- the shop ----

    def test_the_catalog_lists_active_products_with_server_prices_and_fees(self):
        Product.objects.filter(code="PLUG").update(is_active=False)
        body = self.client.get("/api/orders/catalog", **self.headers(self.alice)).json()
        self.assertNotIn("PLUG", [p["code"] for p in body["products"]])
        self.assertEqual((body["express_fee"], body["max_quantity"]), (9.0, 5))

    def test_placing_an_order_prices_it_on_the_server_and_promises_a_date(self):
        with self.captureOnCommitCallbacks(execute=True):
            res = self.order(quantity=2, express=True)
        self.assertEqual(res.status_code, 201, res.content)
        body = res.json()
        self.assertRegex(body["order_ref"], r"^ORD-\d{5}$")
        self.assertEqual((body["status"], body["quantity"], body["express"], body["can_cancel"]), ("processing", 2, True, True))
        self.assertEqual((body["amount"], body["shipping_fee"], body["total"]), (float(self.plug.price * 2), 9.0, float(self.plug.price * 2 + 9)))
        order = Order.objects.get(order_ref=body["order_ref"])
        self.assertEqual((order.customer, order.delivery_address), (self.alice, ADDRESS))
        self.assertEqual(business_days_between(order.order_date, order.estimated_delivery_date), 2)  # express
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(order.order_ref, mail.outbox[0].subject)

    def test_standard_delivery_is_five_business_days_and_free(self):
        body = self.order().json()
        order = Order.objects.get(order_ref=body["order_ref"])
        self.assertEqual((body["shipping_fee"], business_days_between(order.order_date, order.estimated_delivery_date)), (0.0, 5))

    def test_order_numbers_continue_from_the_last_shop_number_and_are_never_reused(self):
        Order.objects.create(order_ref="ORD-10040", customer=self.bob, product=self.plug, amount=1, status="delivered", order_date=timezone.localdate())
        Order.objects.create(order_ref="ORD-60500", customer=self.bob, product=self.plug, amount=1, status="delivered", order_date=timezone.localdate())  # dataset range
        self.assertEqual(self.order().json()["order_ref"], "ORD-10041")
        self.assertEqual(self.order(quantity=2).json()["order_ref"], "ORD-10042")

    def test_services_need_no_address_and_are_active_straight_away(self):
        body = self.order(product=self.service.code, quantity=3, express=True, delivery_address="").json()
        self.assertEqual((body["status"], body["quantity"], body["express"], body["shipping_fee"], body["estimated_delivery_date"]), ("delivered", 1, False, 0.0, None))
        self.assertFalse(body["can_cancel"])

    # ---- refusals ----

    def test_bad_orders_are_refused_with_a_clear_reason(self):
        self.assertEqual(self.order(product="NOPE").status_code, 404)
        self.assertEqual(self.order(quantity=6).status_code, 400)
        res = self.order(delivery_address="here")
        self.assertEqual(res.status_code, 400)
        self.assertIn("delivery address", res.json()["detail"])
        self.assertEqual(Order.objects.filter(customer=self.alice).count(), 0)

    def test_staff_cannot_order(self):
        self.assertEqual(self.order(user=self.agent).status_code, 403)

    def test_a_double_click_does_not_place_the_order_twice(self):
        first = self.order().json()["order_ref"]
        again = self.order()
        self.assertEqual(again.status_code, 409)
        self.assertIn(first, again.json()["detail"])
        self.assertEqual(Order.objects.filter(customer=self.alice).count(), 1)
        self.assertEqual(self.order(quantity=2).status_code, 201)  # a different order is fine

    @override_settings(ORDER_MAX_PER_DAY=2)
    def test_one_customer_cannot_flood_the_shop(self):
        self.assertEqual([self.order(quantity=q).status_code for q in (1, 2, 3)], [201, 201, 429])

    # ---- cancelling and fulfilling ----

    def test_a_customer_cancels_until_dispatch_and_only_their_own_order(self):
        ref = self.order().json()["order_ref"]
        self.assertEqual(self.client.post(f"/api/orders/{ref}/cancel", **self.headers(self.bob)).status_code, 404)
        res = self.client.post(f"/api/orders/{ref}/cancel", **self.headers(self.alice))
        self.assertEqual((res.status_code, res.json()["status"], res.json()["can_cancel"]), (200, "cancelled", False))
        self.assertEqual(self.client.post(f"/api/orders/{ref}/cancel", **self.headers(self.alice)).status_code, 409)

    def test_a_dispatched_order_cannot_be_cancelled(self):
        ref = self.order().json()["order_ref"]
        Order.objects.filter(order_ref=ref).update(status="shipped")
        res = self.client.post(f"/api/orders/{ref}/cancel", **self.headers(self.alice))
        self.assertEqual(res.status_code, 409)
        self.assertIn("dispatched", res.json()["detail"])

    def test_staff_move_an_order_forward_one_step_at_a_time(self):
        with self.captureOnCommitCallbacks(execute=True):
            ref = self.order().json()["order_ref"]
        patch = lambda user, status: self.client.patch(f"/api/orders/{ref}/status", {"status": status}, content_type="application/json", **self.headers(user))  # noqa: E731
        self.assertEqual(patch(self.agent, "shipped").status_code, 403)
        self.assertEqual(patch(self.alice, "shipped").status_code, 403)
        self.assertEqual(patch(self.manager, "delivered").status_code, 409)  # cannot skip a step
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(patch(self.manager, "shipped").json()["status"], "shipped")
        done = patch(self.manager, "delivered").json()
        self.assertEqual((done["status"], done["delivery_date"]), ("delivered", str(timezone.localdate())))
        self.assertEqual(patch(self.manager, "shipped").status_code, 409)  # and cannot go back
        self.assertEqual(len(mail.outbox), 2)  # confirmation + "on its way"

    def test_new_orders_appear_in_my_orders_and_are_hidden_from_others(self):
        ref = self.order().json()["order_ref"]
        mine = self.client.get("/api/orders/my", **self.headers(self.alice)).json()
        self.assertEqual([o["order_ref"] for o in mine], [ref])
        self.assertEqual(self.client.get("/api/orders/my", **self.headers(self.bob)).json(), [])
        self.assertEqual(self.client.get(f"/api/orders/{ref}", **self.headers(self.bob)).status_code, 404)

    def test_a_late_shop_order_is_judged_by_the_same_dates_as_any_other(self):
        ref = self.order().json()["order_ref"]
        Order.objects.filter(order_ref=ref).update(order_date=timezone.localdate() - timedelta(days=30), estimated_delivery_date=timezone.localdate() - timedelta(days=14), status="shipped")
        from .facts import days_late

        self.assertGreater(days_late(Order.objects.get(order_ref=ref), timezone.localdate()), 5)
        self.assertEqual(Decimal(Order.objects.get(order_ref=ref).amount), self.plug.price)
