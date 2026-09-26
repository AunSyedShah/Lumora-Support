"""
Duplicate and repeat-complaint detection (SRS Steps 52-54, challenge 1.8.13).

  exact duplicate  same customer, same cleaned text, original still open, within the window
                   -> the new submission is rejected (points to the existing complaint)
  near-duplicate   same customer, similarity >= NEAR_DUPLICATE_THRESHOLD, original still open
                   -> accepted but linked, so staff can merge it
  repeat           same customer and the same issue raised again, possibly in completely different
                   words, or an explicit reference to the earlier complaint
                   -> accepted, linked, and counted in `previous_complaints` for the rule engine

"Same issue" = embedding similarity >= REPEAT_CERTAIN_THRESHOLD, or >= REPEAT_COMPLAINT_THRESHOLD
when the keyword classifier does not put the two complaints into different subcategories.
Embedding similarity alone overlaps between "reworded" and "same topic, different problem";
the classifier check separates most of those cases (see the calibration notes in settings.py).
"""

from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from rules.engine import classify
from vector_search.embeddings import from_bytes
from vector_search.index import VectorIndex

from .models import Complaint

complaint_index = VectorIndex(lambda: Complaint.objects.all()).watch(Complaint)


def find_exact_duplicate(customer, text_hash):
    since = timezone.now() - timedelta(days=settings.DUPLICATE_WINDOW_DAYS)
    return Complaint.objects.filter(
        customer=customer, text_hash=text_hash, status__in=Complaint.OPEN_STATUSES, created_at__gte=since
    ).first()


@dataclass
class RelatedResult:
    match_type: str = Complaint.MatchType.NONE
    related: Complaint | None = None
    similarity: float | None = None
    related_ids: set = field(default_factory=set)


def _subcategory(normalized_text):
    issues = classify(normalized_text)
    return issues[0].subcategory.code if issues else None


def _same_issue(score, new_subcategory, earlier):
    if score >= settings.REPEAT_CERTAIN_THRESHOLD:
        return True
    if score < settings.REPEAT_COMPLAINT_THRESHOLD:
        return False
    earlier_subcategory = _subcategory(earlier.normalized_text)
    conflict = new_subcategory and earlier_subcategory and new_subcategory != earlier_subcategory
    return not conflict


def _with_earlier_links(complaints):
    """
    Follow related/previous links backwards: if B repeats A and the new complaint repeats B,
    then A is part of the same history too (the new one is the THIRD complaint, not the second).
    """
    ids, stack = set(), list(complaints)
    while stack:
        complaint = stack.pop()
        if complaint is None or complaint.pk in ids:
            continue
        ids.add(complaint.pk)
        stack += [complaint.related_complaint, complaint.previous_complaint]
    return ids


def find_related(customer, embedding, normalized_text, previous_complaint=None):
    """Compare with this customer's earlier complaints only."""
    result = RelatedResult()
    customer_ids = list(customer.complaints.values_list("pk", flat=True))
    hits = complaint_index.search(embedding, k=10, only_ids=customer_ids) if customer_ids else []
    candidates = Complaint.objects.in_bulk([pk for pk, _ in hits])
    new_subcategory = _subcategory(normalized_text)
    similar = [
        (pk, score) for pk, score in hits
        if pk in candidates and _same_issue(score, new_subcategory, candidates[pk])
    ]

    result.related_ids = _with_earlier_links([candidates[pk] for pk, _ in similar] + [previous_complaint])
    if not result.related_ids:
        return result

    if similar:
        best_pk, best_score = similar[0]
        result.related, result.similarity = candidates[best_pk], round(best_score, 3)
    else:
        result.related = previous_complaint

    is_near_duplicate = (
        result.similarity is not None
        and result.similarity >= settings.NEAR_DUPLICATE_THRESHOLD
        and result.related.is_open
    )
    result.match_type = Complaint.MatchType.NEAR_DUPLICATE if is_near_duplicate else Complaint.MatchType.REPEAT
    return result


def similar_complaints(complaint, k=5):
    """Most similar complaints from ANY customer (useful for spotting trends / known issues)."""
    if complaint.embedding is None:
        return []
    hits = complaint_index.search(from_bytes(complaint.embedding), k=k, exclude_ids=(complaint.pk,))
    by_pk = Complaint.objects.in_bulk([pk for pk, _ in hits])
    return [(by_pk[pk], score) for pk, score in hits if pk in by_pk]
