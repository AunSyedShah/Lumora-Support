from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """SupportNova user. The role decides what each user can do in the API."""

    class Role(models.TextChoices):
        CUSTOMER = "customer", "Customer"
        AGENT = "agent", "Agent"
        REVIEWER = "reviewer", "Reviewer"
        MANAGER = "manager", "Manager"
        ADMIN = "admin", "Administrator"

    class CustomerType(models.TextChoices):
        STANDARD = "standard", "Standard"
        PREMIUM = "premium", "Premium (LumoraCare+)"
        BUSINESS = "business", "Business"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CUSTOMER)
    # Only meaningful for customers; used later by priority and eligibility rules.
    customer_type = models.CharField(
        max_length=20, choices=CustomerType.choices, default=CustomerType.STANDARD
    )
    phone = models.CharField(max_length=30, blank=True)
    # Staff only: the department an agent works in (used for automatic assignment).
    department = models.ForeignKey(
        "catalog.Department", on_delete=models.SET_NULL, null=True, blank=True, related_name="staff"
    )

    @property
    def display_name(self):
        """The name people read in the app; the username when no name was given."""
        return self.get_full_name() or self.username

    def __str__(self):
        return f"{self.username} ({self.role})"
