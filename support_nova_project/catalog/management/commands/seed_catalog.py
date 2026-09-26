"""
Load departments, categories, subcategories and SLA rules from config/catalog.json.

Safe to run repeatedly: existing rows (matched by code / priority) are updated, new ones created.
Usage:  python manage.py seed_catalog [--file path/to/other.json]
"""

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.models import Category, Department, Product, SLARule, Subcategory


class Command(BaseCommand):
    help = "Seed the complaint catalog from a JSON config file."

    def add_arguments(self, parser):
        parser.add_argument("--file", default=str(settings.BASE_DIR / "config" / "catalog.json"))

    @transaction.atomic
    def handle(self, *args, **options):
        data = json.loads(Path(options["file"]).read_text(encoding="utf-8"))

        for d in data["departments"]:
            Department.objects.update_or_create(
                code=d["code"],
                defaults={"name": d["name"], "description": d.get("description", "")},
            )

        sub_count = 0
        for c in data["categories"]:
            category, _ = Category.objects.update_or_create(
                code=c["code"],
                defaults={
                    "name": c["name"],
                    "description": c.get("description", ""),
                    "default_department": Department.objects.get(code=c["default_department"]),
                },
            )
            for s in c["subcategories"]:
                department = s.get("department")
                Subcategory.objects.update_or_create(
                    code=s["code"],
                    defaults={
                        "category": category,
                        "name": s["name"],
                        "description": s.get("description", ""),
                        "department": Department.objects.get(code=department) if department else None,
                        "keywords": [k.lower() for k in s.get("keywords", [])],
                        "is_fallback": s.get("is_fallback", False),
                        "takes_precedence_over": s.get("takes_precedence_over", []),
                    },
                )
                sub_count += 1

        for product in data.get("products", []):
            Product.objects.update_or_create(code=product["code"], defaults={
                "name": product["name"], "kind": product["kind"], "price": product["price"],
            })

        for rule in data["sla_rules"]:
            SLARule.objects.update_or_create(priority=rule.pop("priority"), defaults=rule)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(data['departments'])} departments, {len(data['categories'])} "
                f"categories, {sub_count} subcategories, {len(data.get('products', []))} products, "
                f"{len(data['sla_rules'])} SLA rules."
            )
        )
