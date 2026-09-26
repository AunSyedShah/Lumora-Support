"""
Reading and writing the dataset files. CSV so the team can open, check and correct them in Excel.

  sample_complaints/complaint_specs.csv  the specs + expected labels (input of the text generator)
  sample_complaints/complaints.csv       the final dataset: specs + expected labels + complaint text
List values are written as "a | b | c".
"""

import csv
from dataclasses import fields
from pathlib import Path

from django.conf import settings

from .specs import Spec

DATASET_DIR = Path(settings.BASE_DIR) / "sample_complaints"
SPECS_FILE = DATASET_DIR / "complaint_specs.csv"
COMPLAINTS_FILE = DATASET_DIR / "complaints.csv"
GENERATED_FILE = DATASET_DIR / "generated_text.jsonl"

SEPARATOR = " | "
SPEC_FIELDS = [f.name for f in fields(Spec) if f.name not in ("expected", "case_types")]
EXPECTED_FIELDS = ["category", "subcategory", "secondary", "department", "supporting", "urgency", "priority",
                   "escalation", "escalation_rules", "rule", "compensation", "review_required"]
TEXT_FIELDS = ["title", "description", "requested_resolution", "supporting_information"]
LIST_FIELDS = {"subcategories", "key_facts", "claims", "case_types",
               "secondary", "supporting", "escalation_rules", "compensation"}
BOOL_FIELDS = {"product_in_field", "has_order", "express", "review_required"}
INT_FIELDS = {"quantity", "days_late", "days_since_delivery", "days_since_purchase", "previous_complaints"}
FLOAT_FIELDS = {"amount"}


def _out(name, value):
    if name in LIST_FIELDS:
        return SEPARATOR.join(value or [])
    if name in BOOL_FIELDS:
        return "yes" if value else "no"
    return "" if value is None else value


def _in(name, text):
    text = (text or "").strip()
    if name in LIST_FIELDS:
        return [v.strip() for v in text.split(SEPARATOR.strip()) if v.strip()]
    if name in BOOL_FIELDS:
        return text.lower() in ("yes", "true", "1")
    if name in INT_FIELDS:
        return int(text) if text else (0 if name in ("quantity", "previous_complaints") else None)
    if name in FLOAT_FIELDS:
        return float(text) if text else None
    return text


def header(with_text=False):
    columns = ["case_id", "split", "group", "case_types"] + [f for f in SPEC_FIELDS if f not in ("case_id", "split", "group")]
    columns += [f"expected_{f}" for f in EXPECTED_FIELDS]
    return columns + (TEXT_FIELDS if with_text else [])


def spec_row(spec, text=None):
    row = {name: _out(name, getattr(spec, name)) for name in SPEC_FIELDS}
    row["case_types"] = _out("case_types", spec.case_types)
    row.update({f"expected_{f}": _out(f, spec.expected.get(f)) for f in EXPECTED_FIELDS})
    if text is not None:
        row.update({f: text.get(f, "") for f in TEXT_FIELDS})
    return row


def write_rows(path, rows, with_text=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # BOM: Excel opens it as UTF-8
        writer = csv.DictWriter(f, fieldnames=header(with_text))
        writer.writeheader()
        writer.writerows(rows)


def write_specs(specs, path=SPECS_FILE):
    write_rows(path, [spec_row(s) for s in specs])


def read_rows(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def spec_from_row(row):
    spec = Spec(**{name: _in(name, row.get(name, "")) for name in SPEC_FIELDS})
    spec.product = spec.product or None
    spec.case_types = _in("case_types", row.get("case_types", ""))
    spec.expected = {f: _in(f, row.get(f"expected_{f}", "")) for f in EXPECTED_FIELDS}
    return spec


def read_specs(path=SPECS_FILE):
    return [spec_from_row(row) for row in read_rows(path)]


def text_from_row(row):
    return {f: row.get(f, "") for f in TEXT_FIELDS}
