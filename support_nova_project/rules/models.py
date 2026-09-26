"""
Complaint Resolution Rule Matrix (SRS Step 8, deliverable 5).

This is the ground truth for the Python validation pipeline. It is written by the team
(config/rules/*.csv), never generated at runtime by the GenAI model.

ResolutionRule  - what SHOULD happen for one subcategory under certain conditions
                  (department, urgency, priority, policy, required / prohibited actions ...)
EscalationRule  - independent triggers that force escalation (safety words, legal threats,
                  repeat complaints, high amounts ...). All matching rules apply; highest level wins.
"""

from django.db import models

from catalog.models import Category, Department, Priority, Subcategory, Urgency


class EscalationLevel(models.TextChoices):
    NONE = "none", "No Escalation"
    SUPERVISOR = "supervisor", "Supervisor Review"
    DEPARTMENT_MANAGER = "department_manager", "Department Manager"
    SPECIALIST_TEAM = "specialist_team", "Specialist Team"
    COMPLIANCE_REVIEW = "compliance_review", "Compliance Review"
    CRITICAL_MANAGEMENT = "critical_management", "Critical Management Escalation"


# Same order as the SRS list (Step 37): a higher number is a more serious escalation.
ESCALATION_RANK = {level: rank for rank, level in enumerate(EscalationLevel)}


class Compensation(models.TextChoices):
    """What a resolution is allowed to offer. Anything else in a GenAI answer is flagged."""

    NONE = "none", "No compensation"
    FULL_REFUND = "full_refund", "Full refund"
    PARTIAL_REFUND = "partial_refund", "Partial refund"
    SHIPPING_FEE_REFUND = "shipping_fee_refund", "Shipping fee refund"
    FEE_WAIVER = "fee_waiver", "Fee waiver"
    REPLACEMENT = "replacement", "Replacement"
    REPAIR = "repair", "Free repair"
    SUBSCRIPTION_CREDIT = "subscription_credit", "Subscription credit"


class ResolutionRule(models.Model):
    rule_id = models.CharField(max_length=20, unique=True)  # e.g. "RR-014"
    description = models.CharField(max_length=255, blank=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="resolution_rules")
    subcategory = models.ForeignKey(Subcategory, on_delete=models.PROTECT, related_name="resolution_rules")
    # See rules/conditions.py for the allowed keys, e.g. {"max_days_since_delivery": 30}
    conditions = models.JSONField(default=dict, blank=True)

    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="resolution_rules")
    supporting_departments = models.ManyToManyField(Department, blank=True, related_name="supporting_rules")
    urgency = models.CharField(max_length=10, choices=Urgency.choices)
    priority = models.CharField(max_length=2, choices=Priority.choices)
    escalation_level = models.CharField(
        max_length=30, choices=EscalationLevel.choices, default=EscalationLevel.NONE
    )

    # Soft reference to the knowledge base: the doc_id (not a specific version) + section number,
    # so a revised policy version is picked up automatically. Checked by /rules/policy-check.
    policy_id = models.CharField(max_length=50)
    policy_section = models.CharField(max_length=20, blank=True)

    required_actions = models.JSONField(default=list, blank=True)
    prohibited_actions = models.JSONField(default=list, blank=True)
    allowed_compensation = models.JSONField(default=list, blank=True)  # Compensation values
    follow_up_days = models.PositiveSmallIntegerField(default=0)  # 0 = no follow-up needed

    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["rule_id"]

    def __str__(self):
        return f"{self.rule_id} {self.subcategory.code}"

    @property
    def follow_up_required(self):
        return self.follow_up_days > 0


class EscalationRule(models.Model):
    rule_id = models.CharField(max_length=20, unique=True)  # e.g. "ESC-005"
    name = models.CharField(max_length=150)
    description = models.CharField(max_length=255, blank=True)
    conditions = models.JSONField(default=dict)

    escalation_level = models.CharField(max_length=30, choices=EscalationLevel.choices)
    target_department = models.ForeignKey(
        Department, on_delete=models.PROTECT, null=True, blank=True, related_name="escalation_rules"
    )
    # When the rule fires, urgency / priority are raised to at least these values.
    min_urgency = models.CharField(max_length=10, choices=Urgency.choices, blank=True)
    min_priority = models.CharField(max_length=2, choices=Priority.choices, blank=True)

    policy_id = models.CharField(max_length=50, blank=True)
    policy_section = models.CharField(max_length=20, blank=True)

    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["rule_id"]

    def __str__(self):
        return f"{self.rule_id} {self.name}"
