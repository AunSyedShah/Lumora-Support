"""
Build the information sent to the GenAI model for one complaint.

Independence rule: Pipeline 1 must reach its own conclusions, so NOTHING from the Python rule
engine (expected department, priority, matched rule, escalation) is included here. The model
gets the same raw material a human agent would have: the complaint, the customer's order data,
the live taxonomy, and policy excerpts found by its own hybrid search.
"""

import re
from dataclasses import dataclass, field

from django.conf import settings

from catalog.models import Category, Department, Priority, Urgency
from knowledge_base.retrieval import hybrid_search, usable_chunks
from rules.models import Compensation, EscalationLevel

from .output_schema import Emotion, FollowUpType, Sentiment, Tone

DELIMITER = re.compile(r"</?\s*complaint\s*>", re.IGNORECASE)


@dataclass
class PromptContext:
    values: dict  # placeholder -> text
    chunks: dict = field(default_factory=dict)  # chunk_id -> {"policy_id", "section", "version"}
    policy_versions: dict = field(default_factory=dict)  # doc_id -> version


def _taxonomy():
    lines = []
    categories = Category.objects.filter(is_active=True).select_related("default_department").prefetch_related(
        "subcategories__department"
    )
    for c in categories:
        lines.append(f"{c.code} ({c.name}) - default department {c.default_department.code}")
        for s in c.subcategories.all():
            if s.is_active:
                dept = f" -> {s.department.code}" if s.department else ""
                meaning = f". {s.description}" if s.description else ""  # how to tell overlapping ones apart
                lines.append(f"    {s.code}: {s.name}{dept}{meaning}")
    return "\n".join(lines)


def _departments():
    return "\n".join(f"{d.code}: {d.name} - {d.description}" for d in Department.objects.filter(is_active=True))


def _allowed_values():
    def values(enum):
        return ", ".join(e.value for e in enum)

    return "\n".join([
        f"sentiment: {values(Sentiment)}",
        f"emotions: {values(Emotion)}",
        f"urgency: {values(Urgency)}",
        f"priority: {values(Priority)} (P0 = most critical)",
        f"escalation_level: {values(EscalationLevel)}",
        f"compensation.type: {values(Compensation)}",
        f"follow_up.type: {values(FollowUpType)}",
        f"customer_response.tone: {values(Tone)}",
    ])


def _excerpt_blocks(policy_chunks, chunks, versions):
    """Format chunks for the prompt and record them (so citations can be checked against them)."""
    blocks = []
    for chunk in policy_chunks:
        doc = chunk.document
        chunks[chunk.chunk_id] = {"policy_id": doc.doc_id, "section": chunk.section, "version": doc.version}
        versions[doc.doc_id] = doc.version
        blocks.append(
            f"[chunk_id: {chunk.chunk_id}] {doc.doc_id} v{doc.version} \"{doc.title}\" "
            f"(type: {doc.doc_type}, precedence {doc.precedence}, effective {doc.effective_date})\n"
            f"Section {chunk.section or '-'} {chunk.heading}: {chunk.text}"
        )
    return blocks


def _standing_policies(chunks, versions):
    """
    Short company-wide documents every analysis needs whatever the complaint is about (escalation
    triggers, SLA priorities, routing), in their active versions. Same text for every complaint,
    so it sits in the cached part of the prompt. Knowledge-base documents, not the rule matrix.
    """
    standing = usable_chunks().filter(document__doc_id__in=settings.GENAI_STANDING_POLICIES).order_by(
        "document__doc_id", "order")
    return "\n\n".join(_excerpt_blocks(standing, chunks, versions)) or "None."


def _policy_excerpts(query, limit, chunks, versions):
    hits = [h["chunk"] for h in hybrid_search(query, limit=limit) if h["chunk"].chunk_id not in chunks]
    return "\n\n".join(_excerpt_blocks(hits, chunks, versions)) or "No further matching policy excerpts were found."


def _customer_context(complaint):
    f = complaint.facts or {}
    lines = [
        f"Customer type: {complaint.customer_type}",
        f"Complaint channel: {complaint.channel}; preferred contact: {complaint.preferred_contact}",
        f"Product: {complaint.product.name if complaint.product else 'not specified'}",
    ]
    if complaint.order:
        o = complaint.order
        lines += [
            f"Order {o.order_ref}: {o.product.name} x{o.quantity}, amount {o.amount} USD, status {o.status}, "
            f"{'express' if o.express else 'standard'} shipping",
            f"Order date {o.order_date}; estimated delivery {o.estimated_delivery_date or '-'}; "
            f"delivered {o.delivery_date or 'not yet'}",
            f"Days since purchase: {f.get('days_since_purchase')}; days since delivery: "
            f"{f.get('days_since_delivery')}; business days late: {f.get('days_late')}",
        ]
    else:
        lines.append("Order: no order reference was provided")
    if complaint.requested_resolution:
        lines.append(f"Customer's requested resolution (a request, not an entitlement): {complaint.requested_resolution}")

    earlier = complaint.customer.complaints.exclude(pk=complaint.pk).filter(created_at__lt=complaint.created_at)[:5]
    if earlier:
        lines.append("Earlier complaints from this customer (newest first):")
        lines += [f"  - {c.complaint_id} ({c.created_at:%Y-%m-%d}, status {c.status}): {c.title}" for c in earlier]
    else:
        lines.append("Earlier complaints from this customer: none")
    if complaint.related_complaint:
        lines.append(
            f"Intake linked this complaint to {complaint.related_complaint.complaint_id} as a "
            f"{complaint.match_type.replace('_', ' ')} ({f.get('previous_complaints', 0)} earlier related complaint(s))."
        )
    return "\n".join(lines)


def _security_notes(complaint):
    if not complaint.security_flags:
        return "No manipulation patterns were detected by the intake scanner."
    flags = "; ".join(f"{f['flag']}: \"{f['excerpt']}\"" for f in complaint.security_flags)
    return f"WARNING - possible manipulation attempt detected in the complaint text: {flags}"


def _complaint_text(complaint):
    parts = [f"Title: {complaint.title}", f"Description: {complaint.description}"]
    if complaint.supporting_information:
        parts.append(f"Supporting information: {complaint.supporting_information}")
    # A customer must not be able to close the <complaint> block and write "outside" it.
    return DELIMITER.sub("[removed tag]", "\n".join(parts))


def build_context(complaint, tone, policy_chunk_limit):
    chunks, versions = {}, {}
    standing = _standing_policies(chunks, versions)  # first, so retrieval does not repeat them
    excerpts = _policy_excerpts(f"{complaint.title}. {complaint.description}", policy_chunk_limit, chunks, versions)
    return PromptContext(
        values={
            "taxonomy": _taxonomy(),
            "departments": _departments(),
            "allowed_values": _allowed_values(),
            "standing_policies": standing,  # used by prompt v1.3+; older versions ignore it
            "policy_excerpts": excerpts,
            "customer_context": _customer_context(complaint),
            "security_notes": _security_notes(complaint),
            "tone": tone,
            "complaint": _complaint_text(complaint),
        },
        chunks=chunks,
        policy_versions=versions,
    )
