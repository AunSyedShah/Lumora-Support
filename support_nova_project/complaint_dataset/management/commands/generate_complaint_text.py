"""
Step 2 of the dataset: write the complaint text for every spec with the LLM.

Results are appended to sample_complaints/generated_text.jsonl as they arrive, so an interrupted
run continues where it stopped. When every spec has text, sample_complaints/complaints.csv
(specs + expected labels + text) is written.

Usage:
  python manage.py generate_complaint_text --limit 10          # pilot run: the first 10 missing
  python manage.py generate_complaint_text                     # everything that is missing
  python manage.py generate_complaint_text --only DS-0012,DS-0100 --regenerate
  python manage.py generate_complaint_text --export-only       # just rebuild complaints.csv
"""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed

import openai
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from complaint_dataset.csv_io import COMPLAINTS_FILE, GENERATED_FILE, SPECS_FILE, read_specs, spec_row, write_rows
from complaint_dataset.expected import product_names
from complaint_dataset.generator import WriterError, escalation_keywords, write_complaint


def load_generated():
    """Latest record per case_id (a regenerated complaint replaces the earlier one)."""
    records = {}
    if GENERATED_FILE.exists():
        with open(GENERATED_FILE, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    record = json.loads(line)
                    records[record["case_id"]] = record
    return records


def export_complaints(specs, records):
    rows = [spec_row(spec, records[spec.case_id]) for spec in specs if spec.case_id in records]
    write_rows(COMPLAINTS_FILE, rows, with_text=True)
    return len(rows)


class Command(BaseCommand):
    help = "Generate the complaint text for the dataset specs with the LLM."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, help="Generate at most this many complaints.")
        parser.add_argument("--only", help="Comma-separated case ids.")
        parser.add_argument("--regenerate", action="store_true", help="Also redo case ids that already have text.")
        parser.add_argument("--workers", type=int, default=6)
        parser.add_argument("--model", default=settings.DEEPSEEK_MODEL)
        parser.add_argument("--export-only", action="store_true")

    def handle(self, *args, **options):
        if not SPECS_FILE.exists():
            raise CommandError("No specs yet. Run build_dataset_specs first.")
        specs = read_specs()
        by_id = {s.case_id: s for s in specs}
        records = load_generated()
        if options["export_only"]:
            self.stdout.write(f"Wrote {export_complaints(specs, records)} complaints to {COMPLAINTS_FILE}")
            return

        wanted = specs
        if options["only"]:
            ids = {i.strip().upper() for i in options["only"].split(",")}
            wanted = [s for s in specs if s.case_id in ids]
        if not options["regenerate"]:
            wanted = [s for s in wanted if s.case_id not in records]
        if options["limit"]:
            wanted = wanted[: options["limit"]]

        names, keywords = product_names(), escalation_keywords()
        # Near-duplicates reword their original, so the originals are written first.
        first = [s for s in wanted if s.group != "near_duplicate"]
        second = [s for s in wanted if s.group == "near_duplicate"]
        done = failed = 0
        for batch in (first, second):
            jobs = {}
            with ThreadPoolExecutor(max_workers=options["workers"]) as pool:
                for spec in batch:
                    original = None
                    if spec.group == "near_duplicate":
                        original = records.get(spec.related_to)
                        if original is None:
                            self.stdout.write(self.style.WARNING(f"{spec.case_id}: original {spec.related_to} has no text yet"))
                            continue
                        original = {k: original[k] for k in ("title", "description", "requested_resolution")}
                    jobs[pool.submit(write_complaint, spec, names, keywords, options["model"], original)] = spec
                for future in as_completed(jobs):
                    spec = jobs[future]
                    try:
                        record = future.result()
                    except openai.APIStatusError as e:
                        if e.status_code in (401, 402):
                            pool.shutdown(cancel_futures=True)
                            raise CommandError(f"DeepSeek refused the request ({e.status_code}); stopping.")
                        failed += 1
                        self.stdout.write(self.style.ERROR(f"{spec.case_id}: {e}"))
                        continue
                    except (openai.OpenAIError, WriterError) as e:
                        failed += 1
                        self.stdout.write(self.style.ERROR(f"{spec.case_id}: {e}"))
                        continue
                    with open(GENERATED_FILE, "a", encoding="utf-8") as f:
                        f.write(json.dumps(record, ensure_ascii=False) + "\n")
                    records[spec.case_id] = record
                    done += 1
                    flag = f"  FLAGGED: {'; '.join(record['flags'])}" if record["flags"] else ""
                    self.stdout.write(f"{spec.case_id} {spec.group:<18} {record['seconds']:>5}s  {record['title'][:60]}{flag}")

        flagged = [cid for cid, r in records.items() if r["flags"] and cid in by_id]
        self.stdout.write(self.style.SUCCESS(f"Generated {done}, failed {failed}. "
                                             f"{len(records)}/{len(specs)} complaints have text."))
        if flagged:
            self.stdout.write(self.style.WARNING(f"{len(flagged)} flagged for review: {', '.join(sorted(flagged))}"))
        if len(records) >= len(specs):
            self.stdout.write(f"Wrote {export_complaints(specs, records)} complaints to {COMPLAINTS_FILE}")
