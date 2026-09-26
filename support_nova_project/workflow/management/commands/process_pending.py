"""
Process complaints that were never processed (still 'new'), e.g. after a GenAI outage, with
automatic processing switched off, or after a bulk import. Safe to re-run.

Usage:  python manage.py process_pending [--limit 50] [--dry-run]
"""

import time

from django.core.management.base import BaseCommand

from complaints.models import Complaint
from workflow.services import process_and_apply


class Command(BaseCommand):
    help = "Run GenAI analysis + validation + routing for unprocessed complaints."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=50)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        pending = Complaint.objects.filter(
            status=Complaint.Status.NEW, verification_status=Complaint.Verification.PENDING
        ).order_by("created_at")[: options["limit"]]
        for complaint in pending:
            if options["dry_run"]:
                self.stdout.write(f"would process {complaint.complaint_id}")
                continue
            started = time.monotonic()
            try:
                result = process_and_apply(complaint)
            except Exception as exc:  # keep going with the rest of the batch
                self.stderr.write(f"FAILED  {complaint.complaint_id}: {exc}")
                continue
            complaint.refresh_from_db()
            self.stdout.write(
                f"{complaint.complaint_id}: {result.decision} (score {result.score}) -> {complaint.status}, "
                f"{complaint.assigned_to.username if complaint.assigned_to else 'unassigned'} "
                f"[{time.monotonic() - started:.1f}s]"
            )
