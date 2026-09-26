"""
CSV import / export for the rule matrix.

Import is all-or-nothing: every row is validated first and all errors are reported with
their row numbers. Only if the whole file is valid are rules created or updated (by rule_id).
List columns use ';' between items, e.g.  required_actions = "Verify order;Refund duplicate".
"""

import csv
import io

from django.db import transaction

from catalog.models import Category, Department, Priority, Subcategory, Urgency

from .conditions import format_conditions, parse_conditions_text
from .models import Compensation, EscalationLevel, EscalationRule, ResolutionRule

RESOLUTION_COLUMNS = [
    "rule_id", "category", "subcategory", "conditions", "department", "supporting_departments",
    "urgency", "priority", "escalation_level", "policy_id", "policy_section",
    "allowed_compensation", "required_actions", "prohibited_actions", "follow_up_days", "description",
]
ESCALATION_COLUMNS = [
    "rule_id", "name", "conditions", "escalation_level", "target_department",
    "min_urgency", "min_priority", "policy_id", "policy_section", "description",
]


class RuleImportError(Exception):
    def __init__(self, errors):
        super().__init__(f"{len(errors)} error(s) in rule file")
        self.errors = errors


def _split(value):
    return [v.strip() for v in (value or "").split(";") if v.strip()]


def _choice(value, choices, field, allow_blank=False):
    value = (value or "").strip()
    if not value and allow_blank:
        return ""
    for c in choices:
        if value.lower() in (c.value.lower(), c.label.lower()):
            return c.value
    raise ValueError(f"{field} '{value}' is not one of {[c.value for c in choices]}")


def _read_rows(text, expected_columns):
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))  # strip Excel's BOM
    missing = set(expected_columns[:4]) - set(reader.fieldnames or [])
    if missing:
        raise RuleImportError([f"Missing column(s): {sorted(missing)}"])
    return [(i, {k: (v or "").strip() for k, v in row.items() if k}) for i, row in enumerate(reader, start=2)]


# ---------------- resolution rules ----------------


def _parse_resolution_row(row):
    subcategory = Subcategory.objects.select_related("category").filter(code=row["subcategory"].upper()).first()
    if subcategory is None:
        raise ValueError(f"unknown subcategory '{row['subcategory']}'")
    if row.get("category") and row["category"].upper() != subcategory.category.code:
        raise ValueError(f"subcategory {subcategory.code} belongs to {subcategory.category.code}, not {row['category']}")

    if row.get("department"):
        department = Department.objects.filter(code=row["department"].upper()).first()
        if department is None:
            raise ValueError(f"unknown department '{row['department']}'")
    else:
        department = subcategory.routed_department  # blank = the subcategory's normal department

    supporting = []
    for code in _split(row.get("supporting_departments")):
        dept = Department.objects.filter(code=code.upper()).first()
        if dept is None:
            raise ValueError(f"unknown supporting department '{code}'")
        supporting.append(dept)

    compensation = [_choice(c, Compensation, "allowed_compensation") for c in _split(row.get("allowed_compensation"))]
    if not row.get("policy_id"):
        raise ValueError("policy_id is required")

    return {
        "rule_id": row["rule_id"].upper(),
        "fields": {
            "description": row.get("description", ""),
            "category": subcategory.category,
            "subcategory": subcategory,
            "conditions": parse_conditions_text(row.get("conditions", "")),
            "department": department,
            "urgency": _choice(row["urgency"], Urgency, "urgency"),
            "priority": _choice(row["priority"], Priority, "priority"),
            "escalation_level": _choice(row.get("escalation_level") or "none", EscalationLevel, "escalation_level"),
            "policy_id": row["policy_id"].upper(),
            "policy_section": row.get("policy_section", ""),
            "required_actions": _split(row.get("required_actions")),
            "prohibited_actions": _split(row.get("prohibited_actions")),
            "allowed_compensation": compensation or [Compensation.NONE],
            "follow_up_days": int(row.get("follow_up_days") or 0),
        },
        "supporting": supporting,
    }


def import_resolution_rules(text):
    return _import(text, RESOLUTION_COLUMNS, _parse_resolution_row, _save_resolution)


def _save_resolution(parsed):
    rule, created = ResolutionRule.objects.update_or_create(rule_id=parsed["rule_id"], defaults=parsed["fields"])
    rule.supporting_departments.set(parsed["supporting"])
    return created


# ---------------- escalation rules ----------------


def _parse_escalation_row(row):
    conditions = parse_conditions_text(row.get("conditions", ""))
    if not conditions:
        raise ValueError("an escalation rule needs at least one condition")
    target = None
    if row.get("target_department"):
        target = Department.objects.filter(code=row["target_department"].upper()).first()
        if target is None:
            raise ValueError(f"unknown target_department '{row['target_department']}'")
    if not row.get("name"):
        raise ValueError("name is required")
    return {
        "rule_id": row["rule_id"].upper(),
        "fields": {
            "name": row["name"],
            "description": row.get("description", ""),
            "conditions": conditions,
            "escalation_level": _choice(row["escalation_level"], EscalationLevel, "escalation_level"),
            "target_department": target,
            "min_urgency": _choice(row.get("min_urgency"), Urgency, "min_urgency", allow_blank=True),
            "min_priority": _choice(row.get("min_priority"), Priority, "min_priority", allow_blank=True),
            "policy_id": row.get("policy_id", "").upper(),
            "policy_section": row.get("policy_section", ""),
        },
    }


def import_escalation_rules(text):
    return _import(text, ESCALATION_COLUMNS, _parse_escalation_row, _save_escalation)


def _save_escalation(parsed):
    _, created = EscalationRule.objects.update_or_create(rule_id=parsed["rule_id"], defaults=parsed["fields"])
    return created


# ---------------- shared ----------------


def _import(text, columns, parse_row, save):
    errors, parsed_rows, seen = [], [], set()
    for line, row in _read_rows(text, columns):
        if not any(row.values()):
            continue  # blank line
        if not row.get("rule_id"):
            errors.append(f"Row {line}: rule_id is required")
            continue
        if row["rule_id"].upper() in seen:
            errors.append(f"Row {line}: duplicate rule_id {row['rule_id']}")
            continue
        seen.add(row["rule_id"].upper())
        try:
            parsed_rows.append(parse_row(row))
        except (ValueError, KeyError) as e:
            errors.append(f"Row {line} ({row['rule_id']}): {e}")
    if errors:
        raise RuleImportError(errors)

    created = updated = 0
    with transaction.atomic():
        for parsed in parsed_rows:
            if save(parsed):
                created += 1
            else:
                updated += 1
    return {"created": created, "updated": updated, "total": len(parsed_rows)}


def export_resolution_rules(queryset):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=RESOLUTION_COLUMNS)
    writer.writeheader()
    for r in queryset.select_related("category", "subcategory", "department").prefetch_related("supporting_departments"):
        writer.writerow({
            "rule_id": r.rule_id, "category": r.category.code, "subcategory": r.subcategory.code,
            "conditions": format_conditions(r.conditions), "department": r.department.code,
            "supporting_departments": ";".join(d.code for d in r.supporting_departments.all()),
            "urgency": r.urgency, "priority": r.priority, "escalation_level": r.escalation_level,
            "policy_id": r.policy_id, "policy_section": r.policy_section,
            "allowed_compensation": ";".join(r.allowed_compensation),
            "required_actions": ";".join(r.required_actions),
            "prohibited_actions": ";".join(r.prohibited_actions),
            "follow_up_days": r.follow_up_days, "description": r.description,
        })
    return out.getvalue()


def export_escalation_rules(queryset):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=ESCALATION_COLUMNS)
    writer.writeheader()
    for r in queryset.select_related("target_department"):
        writer.writerow({
            "rule_id": r.rule_id, "name": r.name, "conditions": format_conditions(r.conditions),
            "escalation_level": r.escalation_level,
            "target_department": r.target_department.code if r.target_department else "",
            "min_urgency": r.min_urgency, "min_priority": r.min_priority,
            "policy_id": r.policy_id, "policy_section": r.policy_section, "description": r.description,
        })
    return out.getvalue()
