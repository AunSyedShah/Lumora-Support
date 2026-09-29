"""
Report export (SRS Step 68): CSV, Excel (.xlsx) and PDF.

  CSV   the csv module; opens directly in Excel (UTF-8 with BOM so accents display correctly)
  XLSX  pandas + openpyxl: a "Report" sheet (the table) and a "Summary" sheet
  PDF   PyMuPDF (already used for the knowledge base): landscape A4, title, filters, summary, table
"""

import csv
import html
import io
import json

import pandas as pd
import pymupdf
from django.utils import timezone

from accounts.models import User
from catalog.models import Category, Department, Subcategory


def _cell(value):
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return "" if value is None else value


# ---------- readable labels (PDF and summaries; CSV/Excel rows keep the raw codes for analysis) ----------

WORDS = {"id": "ID", "genai": "GenAI", "sla": "SLA", "pdf": "PDF", "csv": "CSV", "p0": "P0", "p1": "P1", "p2": "P2", "p3": "P3"}
# Columns holding a code (optionally prefixed genai_ / python_ / expected_) that has a readable name.
CODE_COLUMNS = {"category", "subcategory", "department", "escalation", "escalation_level", "status", "review_status",
                "verification_status", "sla_response", "sla_resolution", "match", "customer_type", "channel",
                "deadline_state", "reason_types", "mismatched_fields"}
PERSON_COLUMNS = {"owner", "assigned_to", "reviewer", "actor"}


def humanize(text):
    """"escalation_level" -> "Escalation level", "genai_category" -> "GenAI category"."""
    words = str(text).replace("_", " ").split()
    words = [WORDS.get(w.lower(), w) for w in words]
    if words and words[0] == words[0].lower():
        words[0] = words[0].capitalize()
    return " ".join(words)


def _catalog_names():
    names = {}
    for model in (Department, Category, Subcategory):
        names.update(dict(model.objects.values_list("code", "name")))
    people = {u.username: u.display_name for u in User.objects.exclude(role=User.Role.CUSTOMER)}
    return names, people


def _readable_cell(column, value, names, people):
    if value is None or value == "":
        return ""
    base = column
    for prefix in ("genai_", "python_", "expected_"):
        base = base.removeprefix(prefix)
    if column in PERSON_COLUMNS:
        return people.get(value, value)
    if base in CODE_COLUMNS and isinstance(value, str):
        return ", ".join(names.get(part.strip(), humanize(part.strip())) for part in value.split(","))
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return _cell(value)


def _readable_summary(value):
    """A summary value in words: {"specialist_team": 15} -> "Specialist team: 15"."""
    if isinstance(value, dict):
        return "; ".join(f"{humanize(k)}: {_readable_summary(v)}" for k, v in value.items()) or "none"
    if isinstance(value, list):
        return ", ".join(_readable_summary(v) for v in value) or "none"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return "—" if value is None else str(value)


def _readable_filters(filters):
    return "; ".join(f"{humanize(k)}: {v}" for k, v in filters.items()) if filters else "none"


def to_csv(report):
    buffer = io.StringIO()
    buffer.write("﻿")  # BOM: Excel then reads the file as UTF-8
    writer = csv.DictWriter(buffer, fieldnames=report.columns, extrasaction="ignore")
    writer.writeheader()
    for row in report.rows:
        writer.writerow({k: _cell(row.get(k)) for k in report.columns})
    return buffer.getvalue().encode("utf-8")


def to_xlsx(report, filters):
    buffer = io.BytesIO()
    table = pd.DataFrame([{k: _cell(r.get(k)) for k in report.columns} for r in report.rows], columns=report.columns)
    summary = pd.DataFrame(
        [("Report", report.title), ("Generated", timezone.localtime().strftime("%Y-%m-%d %H:%M")),
         ("Filters", _readable_filters(filters))]
        + [(humanize(key), _readable_summary(value)) for key, value in report.summary.items()],
        columns=["Item", "Value"],
    )
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        table.to_excel(writer, sheet_name="Report", index=False)
        summary.to_excel(writer, sheet_name="Summary", index=False)
    return buffer.getvalue()


PDF_MAX_COLUMNS = 11  # more columns do not fit on a landscape A4 page


def to_pdf(report, filters, max_rows=500):
    e = html.escape
    columns = report.pdf_columns or report.columns[:PDF_MAX_COLUMNS]
    hidden = [c for c in report.columns if c not in columns]
    names, people = _catalog_names()
    summary = "".join(
        f"<tr><td><b>{e(humanize(k))}</b></td><td>{e(_readable_summary(v))}</td></tr>"
        for k, v in report.summary.items()
    )
    head = "".join(f"<th>{e(humanize(c))}</th>" for c in columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{e(str(_readable_cell(c, r.get(c), names, people)))[:250]}</td>" for c in columns) + "</tr>"
        for r in report.rows[:max_rows]
    )
    notes = []
    if len(report.rows) > max_rows:
        notes.append(f"Showing the first {max_rows} of {len(report.rows)} rows.")
    if hidden:
        notes.append(f"Columns not shown here: {', '.join(humanize(c) for c in hidden)}.")
    note = f"<p><i>{e(' '.join(notes))} The CSV and Excel exports contain all rows and columns.</i></p>" if notes else ""
    document = f"""
        <h1>{e(report.title)}</h1>
        <p>{e(report.description)}<br/>Lumora Home Technologies - SupportNova -
           generated {timezone.localtime().strftime('%Y-%m-%d %H:%M')} - filters: {e(_readable_filters(filters))}</p>
        <h2>Summary</h2><table>{summary}</table>
        <h2>Details ({len(report.rows)} rows)</h2>{note}
        <table><tr>{head}</tr>{body}</table>"""
    css = """body {font-family: sans-serif; font-size: 7pt;}
             h1 {font-size: 14pt;} h2 {font-size: 10pt;}
             table {border-collapse: collapse;} th, td {border: 1px solid #999; padding: 2px;}
             th {background-color: #dde;}"""

    buffer = io.BytesIO()
    story = pymupdf.Story(html=document, user_css=css)
    writer = pymupdf.DocumentWriter(buffer)
    page = pymupdf.paper_rect("a4-l")  # landscape: reports have many columns
    content = page + (30, 30, -30, -30)
    more = True
    while more:
        device = writer.begin_page(page)
        more, _ = story.place(content)
        story.draw(device)
        writer.end_page()
    writer.close()
    return buffer.getvalue()


FORMATS = {
    "csv": ("text/csv", "csv"),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
    "pdf": ("application/pdf", "pdf"),
}


def export(report, fmt, filters):
    if fmt == "csv":
        return to_csv(report)
    if fmt == "xlsx":
        return to_xlsx(report, filters)
    return to_pdf(report, filters)
