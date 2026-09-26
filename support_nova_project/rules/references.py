"""
Check that every rule's policy reference points at a real, usable knowledge-base section.

Useful after a policy revision (SRS 1.8.4): rules citing a section that no longer exists in
the new active version, or citing a document with no usable version, show up here.
"""

from knowledge_base.models import DocumentStatus, PolicyDocument

from .models import EscalationRule, ResolutionRule

OK = "ok"
MISSING_DOCUMENT = "missing_document"  # no document with this doc_id at all
NO_USABLE_VERSION = "no_usable_version"  # only draft / previous / superseded / expired versions
MISSING_SECTION = "missing_section"  # usable version exists but the section number doesn't


def check_reference(policy_id, section):
    versions = list(PolicyDocument.objects.filter(doc_id=policy_id))
    if not versions:
        return MISSING_DOCUMENT, None
    usable = [d for d in versions if d.is_usable]
    if not usable:
        return NO_USABLE_VERSION, None
    document = usable[0]
    if section and not document.chunks.filter(section=section).exists():
        return MISSING_SECTION, document
    return OK, document


def check_all_references(include_ok=False):
    results = []
    rules = [("resolution", r) for r in ResolutionRule.objects.filter(is_active=True)]
    rules += [("escalation", r) for r in EscalationRule.objects.filter(is_active=True).exclude(policy_id="")]
    for rule_type, rule in rules:
        status, document = check_reference(rule.policy_id, rule.policy_section)
        if status != OK or include_ok:
            results.append({
                "rule_type": rule_type,
                "rule_id": rule.rule_id,
                "policy_id": rule.policy_id,
                "policy_section": rule.policy_section,
                "status": status,
                "active_version": document.version if document else None,
            })
    return results
