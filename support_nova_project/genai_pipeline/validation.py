"""
GenAI JSON validation (SRS Steps 46-47).

FATAL problems make the answer unusable and trigger a controlled retry:
  - not JSON / not an object / empty
  - missing fields, wrong types, values outside the fixed lists (Pydantic)
  - category / subcategory / department codes that are not in the live catalog
  - contradictory escalation fields
NON-FATAL problems are kept as `validation_issues` and passed on to the Python validation
pipeline instead of being "retried away" - e.g. a cited policy that doesn't exist is evidence
of a hallucination and must stay visible.
"""

import json
import re

from pydantic import BaseModel, ValidationError

from catalog.models import Category, Department, Subcategory
from knowledge_base.models import PolicyChunk
from knowledge_base.retrieval import usable_chunks

from .output_schema import ComplaintAnalysisOutput


class OutputValidationError(Exception):
    def __init__(self, errors):
        super().__init__("; ".join(errors))
        self.errors = errors


def parse_json(raw):
    text = (raw or "").strip()
    if not text:
        raise OutputValidationError(["The response was empty."])
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)  # tolerate a markdown code fence
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise OutputValidationError([f"The response is not valid JSON ({e.msg} at line {e.lineno})."])
    if not isinstance(data, dict):
        raise OutputValidationError(["The response must be a single JSON object."])
    return data


def _pydantic_errors(error):
    messages, broken_objects = [], set()
    for e in error.errors()[:15]:
        location = ".".join(str(part) for part in e["loc"]) or "(root)"
        messages.append(f"{location}: {e['msg']}")
        if len(e["loc"]) > 1:
            broken_objects.add(e["loc"][0])
    # Tell the model the exact keys a broken nested object must have, so the retry can succeed.
    for name in sorted(broken_objects):
        annotation = ComplaintAnalysisOutput.model_fields[name].annotation if name in ComplaintAnalysisOutput.model_fields else None
        for candidate in getattr(annotation, "__args__", (annotation,)):
            if isinstance(candidate, type) and issubclass(candidate, BaseModel):
                messages.append(f"{name} must be an object with exactly these keys: {', '.join(candidate.model_fields)}.")
                break
    return messages


def validate_output(data, provided_chunks):
    """Return (ComplaintAnalysisOutput, non_fatal_issues). Raise OutputValidationError if fatal."""
    try:
        output = ComplaintAnalysisOutput.model_validate(data)
    except ValidationError as e:
        raise OutputValidationError(_pydantic_errors(e))

    errors = []
    active_categories = set(Category.objects.filter(is_active=True).values_list("code", flat=True))
    sub_to_category = dict(
        Subcategory.objects.filter(is_active=True, category__is_active=True).values_list("code", "category__code")
    )
    departments = set(Department.objects.filter(is_active=True).values_list("code", flat=True))

    for label, issue in [("primary_issue", output.primary_issue)] + [
        (f"secondary_issues.{i}", s) for i, s in enumerate(output.secondary_issues)
    ]:
        if issue.category not in active_categories:
            errors.append(f"{label}.category '{issue.category}' is not a valid category code.")
        elif sub_to_category.get(issue.subcategory) != issue.category:
            errors.append(f"{label}.subcategory '{issue.subcategory}' is not a subcategory of {issue.category}.")

    for code in [output.department] + output.supporting_departments:
        if code not in departments:
            errors.append(f"Department '{code}' is not a valid department code.")

    if output.escalation_required != (output.escalation_level != "none"):
        errors.append("escalation_required and escalation_level contradict each other.")
    if output.escalation_required and output.escalation_notes is None:
        errors.append("escalation_notes are required when escalation_required is true.")
    if errors:
        raise OutputValidationError(errors)

    return output, _policy_issues(output, provided_chunks)


def _policy_issues(output, provided_chunks):
    """Check every cited policy against the knowledge base and the excerpts actually provided."""
    issues = []
    usable = usable_chunks()
    references = [(r.policy_id, r.section, r.chunk_id, "policy_references") for r in output.policy_references]
    if output.compensation.policy_id:
        references.append((output.compensation.policy_id, output.compensation.section, None, "compensation"))

    for policy_id, section, chunk_id, where in references:
        if chunk_id and chunk_id not in provided_chunks:
            issues.append({"type": "chunk_not_provided", "where": where, "reference": chunk_id,
                           "detail": "Cited an excerpt that was not given to the model."})
        if not usable.filter(document__doc_id=policy_id).exists():
            kind = "outdated_policy" if PolicyChunk.objects.filter(document__doc_id=policy_id).exists() else "unknown_policy"
            issues.append({"type": kind, "where": where, "reference": f"{policy_id} {section or ''}".strip(),
                           "detail": "No active, effective version of this policy exists."})
        elif section and not usable.filter(document__doc_id=policy_id, section=section).exists():
            issues.append({"type": "unknown_section", "where": where, "reference": f"{policy_id} {section}",
                           "detail": "This section does not exist in the active version."})
    if not output.policy_references:
        issues.append({"type": "no_policy_reference", "where": "policy_references", "reference": "",
                       "detail": "The analysis cites no policy at all."})
    return issues
