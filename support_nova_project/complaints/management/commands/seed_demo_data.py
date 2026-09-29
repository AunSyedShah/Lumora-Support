"""
Create demo accounts and simulated orders (fictional data only - no real customers).

  - one account per staff role (admin, manager, reviewer, 2 agents)
  - N customers (standard / premium / business) with 1-4 orders each
  - orders are spread over the last ~14 months (30% in the last 20 days): on time, late,
    in transit, cancelled
All accounts use the DEMO_PASSWORD from .env (default below). Deterministic: same data every run.

Usage:  python manage.py seed_demo_data [--customers 60]
"""

import os
import random
from datetime import date, timedelta

import numpy as np
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import User
from catalog.models import Department, Product
from complaints.models import Order

FIRST_NAMES = ["Ayesha", "Bilal", "Chen", "Daniela", "Emeka", "Fatima", "George", "Hina", "Ivan", "Julia",
               "Kofi", "Layla", "Mateo", "Nadia", "Omar", "Priya", "Quinn", "Rosa", "Sami", "Tara"]
LAST_NAMES = ["Khan", "Smith", "Garcia", "Okafor", "Lee", "Rossi", "Ahmed", "Novak", "Silva", "Brown"]

# A named person per team (customers see "Lena from Logistics & Delivery", not a username).
TEAM_AGENTS = {
    "ACCOUNT_SECURITY": ("Omar", "Haddad"), "BILLING": ("Priya", "Nair"), "CUSTOMER_RELATIONS": ("Grace", "Mensah"),
    "INSTALLATION": ("Tom", "Becker"), "LOGISTICS": ("Leo", "Martins"), "MANAGEMENT": ("David", "Kim"),
    "PRIVACY": ("Aisha", "Rahman"), "PRODUCT_SAFETY": ("Marco", "Rossi"), "RETURNS": ("Hannah", "Clarke"),
    "TECH_SUPPORT": ("Sam", "Okoro"), "WARRANTY": ("Nina", "Petrova"),
}

STAFF = [
    ("admin", User.Role.ADMIN, "Lumora", "Admin"),
    ("manager1", User.Role.MANAGER, "Maya", "Manager"),
    ("reviewer1", User.Role.REVIEWER, "Rehan", "Reviewer"),
    ("agent1", User.Role.AGENT, "Alice", "Agent"),
    ("agent2", User.Role.AGENT, "Arif", "Agent"),
]


def business_day(start, days):
    return date.fromisoformat(str(np.busday_offset(start, days, roll="forward")))


class Command(BaseCommand):
    help = "Create demo staff accounts, customers and simulated orders."

    def add_arguments(self, parser):
        parser.add_argument("--customers", type=int, default=60)

    @transaction.atomic
    def handle(self, *args, **options):
        password = os.getenv("DEMO_PASSWORD", "Lumora@2026")
        rng = random.Random(2026)
        today = date.today()

        for username, role, first, last in STAFF:
            self._staff(username, password, role, first_name=first, last_name=last)
        # One agent per department so automatic assignment always finds someone.
        for department in Department.objects.all():
            first, last = TEAM_AGENTS.get(department.code, (department.name.split()[0], "Agent"))
            agent = self._staff(f"agent_{department.code.lower()}", password, User.Role.AGENT,
                                first_name=first, last_name=last)
            if agent.department_id is None:
                agent.department = department
                agent.save(update_fields=["department"])
            if agent.last_name == "Agent" and (first, last) != (agent.first_name, agent.last_name):
                agent.first_name, agent.last_name = first, last  # older demo data used the team name as a name
                agent.save(update_fields=["first_name", "last_name"])

        devices = list(Product.objects.filter(kind=Product.Kind.DEVICE))
        services = list(Product.objects.filter(kind=Product.Kind.SERVICE))
        next_ref = 10001 + Order.objects.count()
        orders_created = 0

        for i in range(1, options["customers"] + 1):
            customer_type = rng.choices(
                [User.CustomerType.STANDARD, User.CustomerType.PREMIUM, User.CustomerType.BUSINESS], [70, 20, 10]
            )[0]
            customer = self._user(
                f"cust{i:03d}", password, role=User.Role.CUSTOMER, customer_type=customer_type,
                first_name=rng.choice(FIRST_NAMES), last_name=rng.choice(LAST_NAMES),
            )
            if customer.orders.exists():
                continue
            for _ in range(rng.randint(1, 4)):
                product = rng.choice(devices) if rng.random() < 0.8 else rng.choice(services)
                Order.objects.create(order_ref=f"ORD-{next_ref}", customer=customer, product=product,
                                     **self._order_details(rng, product, today))
                next_ref += 1
                orders_created += 1

        self.stdout.write(self.style.SUCCESS(
            f"Staff: {', '.join(s[0] for s in STAFF)} + agent_<department> | customers: cust001-cust{options['customers']:03d} | "
            f"new orders: {orders_created} | password: DEMO_PASSWORD (.env) or the default in this command"
        ))

    def _user(self, username, password, **fields):
        user, created = User.objects.get_or_create(username=username, defaults={**fields, "email": f"{username}@example.com"})
        if created:
            user.set_password(password)
            user.save()
        return user

    def _staff(self, username, password, role, **fields):
        """Like _user, but also repairs the role of an existing account (e.g. an "admin" made earlier
        with createsuperuser gets the default role "customer"). Passwords are never changed."""
        is_admin = role == User.Role.ADMIN
        user = self._user(username, password, role=role, is_staff=is_admin, is_superuser=is_admin, **fields)
        if user.role != role or (is_admin and not (user.is_staff and user.is_superuser)):
            user.role = role
            user.is_staff = user.is_staff or is_admin
            user.is_superuser = user.is_superuser or is_admin
            user.save(update_fields=["role", "is_staff", "is_superuser"])
            self.stdout.write(f"Fixed the role of '{username}' -> {role}")
        return user

    def _order_details(self, rng, product, today):
        quantity = 1 if product.kind == Product.Kind.SERVICE else rng.choices([1, 2, 3], [80, 15, 5])[0]
        # ~30% recent orders (so some are still in transit / late), the rest over the last 14 months
        recent = rng.random() < 0.3
        order_date = today - timedelta(days=rng.randint(0, 20) if recent else rng.randint(21, 420))
        details = {"quantity": quantity, "amount": product.price * quantity, "order_date": order_date}

        if product.kind == Product.Kind.SERVICE:  # nothing is shipped
            return {**details, "status": Order.Status.DELIVERED, "delivery_date": order_date}

        express = rng.random() < 0.15
        estimated = business_day(order_date, 2 if express else 5)
        details.update(express=express, estimated_delivery_date=estimated)

        if rng.random() < 0.06:
            return {**details, "status": Order.Status.CANCELLED}
        # 75% on time, 20% a little late, 5% very late (business days)
        delay = rng.choices([0, rng.randint(1, 8), rng.randint(9, 15)], [75, 20, 5])[0]
        delivery = business_day(estimated, delay - rng.randint(0, 1) if delay == 0 else delay)
        if delivery > today:
            status = Order.Status.PROCESSING if order_date >= today - timedelta(days=1) else Order.Status.SHIPPED
            return {**details, "status": status}
        return {**details, "status": Order.Status.DELIVERED, "delivery_date": delivery}
