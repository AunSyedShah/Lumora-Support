"""
Configurable complaint taxonomy: departments, categories, subcategories and SLA targets.

Everything here is data, not code, so a new category / department / SLA can be added
through the API (or Django admin) without touching the source code (SRS Steps 14, 20, 55).
Codes (e.g. "BILLING", "DUPLICATE_CHARGE") are the stable IDs used by the GenAI prompt
and checked by the Python validation pipeline.
"""

from django.db import models


class Priority(models.TextChoices):
    P0 = "P0", "P0 - Critical"
    P1 = "P1", "P1 - High"
    P2 = "P2", "P2 - Medium"
    P3 = "P3", "P3 - Low"


class Urgency(models.TextChoices):
    LOW = "Low", "Low"
    MEDIUM = "Medium", "Medium"
    HIGH = "High", "High"
    CRITICAL = "Critical", "Critical"


# Severity order used when combining rules: a higher number is more serious.
URGENCY_RANK = {Urgency.LOW: 0, Urgency.MEDIUM: 1, Urgency.HIGH: 2, Urgency.CRITICAL: 3}
PRIORITY_RANK = {Priority.P3: 0, Priority.P2: 1, Priority.P1: 2, Priority.P0: 3}


class Department(models.Model):
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Category(models.Model):
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    default_department = models.ForeignKey(
        Department, on_delete=models.PROTECT, related_name="categories"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class Subcategory(models.Model):
    category = models.ForeignKey(
        Category, on_delete=models.CASCADE, related_name="subcategories"
    )
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    # Optional override; when empty the category's default department handles it.
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="subcategories",
        null=True,
        blank=True,
    )
    # Phrases the Python pipeline uses to recognise this issue in complaint text
    # (independent keyword classification, no GenAI involved).
    keywords = models.JSONField(default=list, blank=True)
    # How overlapping subcategories are resolved when a complaint matches several of them:
    #   is_fallback            only the primary issue when nothing more specific was found
    #                          (e.g. "unresolved previous complaint" vs the problem itself)
    #   takes_precedence_over  codes this subcategory beats when both match
    #                          (e.g. a firmware failure over a general hardware malfunction)
    is_fallback = models.BooleanField(default=False)
    takes_precedence_over = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["category__name", "name"]
        verbose_name_plural = "subcategories"

    def __str__(self):
        return f"{self.category.name} / {self.name}"

    @property
    def routed_department(self):
        return self.department or self.category.default_department


class Product(models.Model):
    """Devices and services Lumora sells. Rule conditions refer to products by name."""

    class Kind(models.TextChoices):
        DEVICE = "device", "Device"
        SERVICE = "service", "Service"

    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100, unique=True)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.DEVICE)
    price = models.DecimalField(max_digits=8, decimal_places=2)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class SLARule(models.Model):
    """Target response/resolution time for each priority (SRS Steps 55-56)."""

    priority = models.CharField(max_length=2, choices=Priority.choices, unique=True)
    response_hours = models.PositiveIntegerField()
    resolution_hours = models.PositiveIntegerField()
    # A complaint is flagged "at risk" once this % of the resolution time has passed.
    at_risk_percent = models.PositiveSmallIntegerField(default=75)

    class Meta:
        ordering = ["priority"]
        verbose_name = "SLA rule"

    def __str__(self):
        return f"{self.priority}: respond {self.response_hours}h / resolve {self.resolution_hours}h"
