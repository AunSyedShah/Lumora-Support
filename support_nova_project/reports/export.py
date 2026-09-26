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


def _cell(value):
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return "" if value is None else value


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
         ("Filters", json.dumps(filters) if filters else "none")]
        + [(key, json.dumps(value) if isinstance(value, (dict, list)) else value) for key, value in report.summary.items()],
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
    summary = "".join(
        f"<tr><td><b>{e(str(k))}</b></td><td>{e(json.dumps(v) if isinstance(v, (dict, list)) else str(v))}</td></tr>"
        for k, v in report.summary.items()
    )
    head = "".join(f"<th>{e(c)}</th>" for c in columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{e(str(_cell(r.get(c))))[:250]}</td>" for c in columns) + "</tr>"
        for r in report.rows[:max_rows]
    )
    notes = []
    if len(report.rows) > max_rows:
        notes.append(f"Showing the first {max_rows} of {len(report.rows)} rows.")
    if hidden:
        notes.append(f"Columns not shown here: {', '.join(hidden)}.")
    note = f"<p><i>{e(' '.join(notes))} The CSV and Excel exports contain all rows and columns.</i></p>" if notes else ""
    document = f"""
        <h1>{e(report.title)}</h1>
        <p>{e(report.description)}<br/>Lumora Home Technologies - SupportNova -
           generated {timezone.localtime().strftime('%Y-%m-%d %H:%M')} - filters: {e(json.dumps(filters) if filters else 'none')}</p>
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
