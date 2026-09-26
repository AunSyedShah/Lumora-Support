"""
Checks on the TEXT the GenAI produced (hallucination checks, SRS Steps 28, 32-35).

  required actions     is every mandatory rule action covered by the GenAI resolution steps?
  prohibited actions   does any step / response sentence do something the rule forbids?
  unsupported promises guaranteed refunds or compensation, deadlines not found in any policy,
                       unauthorised policy exceptions
  untraceable facts    order numbers, complaint references and amounts that do not come from
                       the complaint, the order record or the policy excerpts

Matching uses the same local sentence embeddings as duplicate detection plus simple keyword
overlap. There is no GenAI call here: the checks are deterministic and repeatable.
"""

import re

from django.conf import settings

from vector_search.embeddings import embed_texts

STOP = {"the", "and", "for", "with", "that", "this", "from", "into", "customer", "customers", "their",
        "within", "against", "whether", "about", "before", "after", "only", "they", "them", "your"}
NEGATION = re.compile(
    r"\b(do not|don't|does not|doesn't|never|must not|mustn't|should not|shouldn't|won't|will not|cannot|can't|"
    r"unable to|not able to|not in a position to|no longer|avoid|without|until|once|if|whether)\b",
    re.I,
)  # "until/once/if/whether" make a sentence conditional, not a commitment
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                "nine": 9, "ten": 10, "fourteen": 14, "thirty": 30, "twenty-four": 24, "forty-eight": 48}


def key_terms(text):
    """Word stems (first 5 letters) of the meaningful words - a crude but explainable stemmer."""
    return {w[:5] for w in re.findall(r"[a-z]+", text.lower()) if len(w) >= 4 and w not in STOP}


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text or "") if len(s.strip()) > 3]


def _best_matches(targets, candidates):
    """For each target phrase: (best cosine similarity, best keyword overlap, best candidate)."""
    if not targets or not candidates:
        return [(0.0, 0.0, None) for _ in targets]
    vectors = embed_texts(list(targets) + list(candidates))
    target_vecs, cand_vecs = vectors[: len(targets)], vectors[len(targets):]
    results = []
    for target, tv in zip(targets, target_vecs):
        sims = cand_vecs @ tv
        best = int(sims.argmax())
        terms = key_terms(target)
        overlap = max((len(terms & key_terms(c)) / len(terms) for c in candidates), default=0.0) if terms else 0.0
        results.append((float(sims[best]), overlap, candidates[best]))
    return results


def missing_required_actions(required, steps):
    """Required rule actions not covered by any GenAI step. Returns [(action, best_similarity)]."""
    missing = []
    for action, (sim, overlap, _) in zip(required, _best_matches(required, steps)):
        if sim < settings.REQUIRED_ACTION_SIMILARITY and overlap < 0.6:
            missing.append((action, round(sim, 2)))
    return missing


def prohibited_action_hits(prohibited, texts):
    """Prohibited rule actions that a non-negated GenAI sentence appears to perform."""
    candidates = [s for t in texts for s in sentences(t) if not NEGATION.search(s)]
    hits = []
    for action, (sim, overlap, sentence) in zip(prohibited, _best_matches(prohibited, candidates)):
        if sim >= settings.PROHIBITED_ACTION_SIMILARITY or overlap >= 0.8:
            hits.append((action, sentence, round(sim, 2)))
    return hits


# ---------------- unsupported promises ----------------

COMMIT = r"(we will|we'll|we are going to|we have|we've|i will|i'll|i have|i've|you will|you'll|you are entitled to)"
# The commitment must be directly about paying the refund ("we will refund you", "you will receive a
# full refund") - "I will check your eligibility for a refund" is not a promise.
REFUND_PROMISE = re.compile(
    COMMIT + r"\s+(?:be\s+)?(?:(?:happy|able|glad) to\s+)?(?:issue|process|send|give|arrange|provide|approve|pay|receive|get)?"
    r"\s*(?:you\s+)?(?:a\s+|your\s+|the\s+)?(?:full\s+|complete\s+|partial\s+)?(refund|reimburs)",
    re.I,
)
GUARANTEE = re.compile(r"\bguarantee[sd]?\b", re.I)
COMPENSATION_PROMISE = re.compile(COMMIT + r"\b[^.]{0,40}\b(voucher|gift card|discount|coupon|cash|compensat|free (replacement|device|month))", re.I)
EXCEPTION_PROMISE = re.compile(r"\b(make|made|making|approve[sd]?) (an|a one-time|this) exception\b|\bas a (one-time |special )?(courtesy|goodwill)\b|\bwaive[sd]? (the )?(restocking|fee)", re.I)
DEADLINE = re.compile(r"\b(by|before) (tomorrow|today|tonight|monday|tuesday|wednesday|thursday|friday|saturday|sunday|end of (the )?(day|week))\b|\b(will|should) (arrive|be delivered|reach you) (tomorrow|today)\b", re.I)
_NUMBER = r"(\d{1,3}|" + "|".join(NUMBER_WORDS) + r")\s*(?:\(\d+\)\s*)?"
_UNIT = r"(business |working |calendar )?(hour|day|week)s?\b"
# Any duration in policy text ("within 7 business days", "30 calendar days")
DURATION = re.compile(r"\b" + _NUMBER + _UNIT, re.I)
# A duration PROMISED in a response ("within 5 days", "in the next 2 business days") - not "5 days ago"
PROMISED_TIMELINE = re.compile(r"\b(?:within|in|up to|in the next|over the next)\s+" + _NUMBER + _UNIT, re.I)

def promises_refund(text):
    """True if a non-negated sentence commits to a refund."""
    return any(REFUND_PROMISE.search(s) and not NEGATION.search(s) for s in sentences(text))


REFUND_TYPES = {"full_refund", "partial_refund", "shipping_fee_refund"}
OTHER_COMPENSATION = {"fee_waiver", "replacement", "repair", "subscription_credit"}


def _as_number(token):
    return int(token) if token.isdigit() else NUMBER_WORDS.get(token.lower())


def supported_timelines(policy_texts):
    """Every 'N days / N business days / N hours' phrase that appears in the approved policy text."""
    found = set()
    for text in policy_texts:
        for m in DURATION.finditer(text):
            found.add((_as_number(m.group(1)), m.group(3).lower()))
    return found


def unsupported_promises(text, allowed_compensation, rule_decided, policy_texts):
    """Return [(kind, excerpt, why)] for commitments the policy / rules do not support."""
    findings = []
    allowed = set(allowed_compensation or [])
    for sentence in sentences(text):
        if NEGATION.search(sentence) and not GUARANTEE.search(sentence):
            continue
        if REFUND_PROMISE.search(sentence) or (GUARANTEE.search(sentence) and "refund" in sentence.lower()):
            if not allowed & REFUND_TYPES:
                findings.append(("guaranteed_refund", sentence, "No refund is allowed by the rule matrix for this case."))
            elif not rule_decided:
                findings.append(("refund_before_verification", sentence, "Refund eligibility is not confirmed yet (facts missing)."))
        if COMPENSATION_PROMISE.search(sentence) and not allowed & OTHER_COMPENSATION:
            findings.append(("guaranteed_compensation", sentence, "This compensation is not allowed by the rule matrix."))
        if EXCEPTION_PROMISE.search(sentence):
            findings.append(("policy_exception", sentence, "Policy exceptions need supervisor approval (CMPN-GDL 2.3)."))
        if DEADLINE.search(sentence):
            findings.append(("unsupported_deadline", sentence, "A specific date/day is promised that no policy supports."))

    supported = supported_timelines(policy_texts)
    for m in PROMISED_TIMELINE.finditer(text or ""):
        value = (_as_number(m.group(1)), m.group(3).lower())
        if value[0] is not None and value not in supported:
            findings.append(("unsupported_timeline", m.group(0), "This timeline does not appear in any approved policy excerpt."))
    return findings


# ---------------- untraceable facts ----------------

ORDER_REF = re.compile(r"\bORD-\d{5}\b", re.I)
COMPLAINT_REF = re.compile(r"\bCMP-\d{5}\b", re.I)
MONEY = re.compile(r"(?:\$|usd\s?)\s?(\d+(?:\.\d{1,2})?)|\b(\d+(?:\.\d{1,2})?)\s?(?:usd|dollars)\b", re.I)


def _amounts(text):
    return {float(a or b) for a, b in MONEY.findall(text or "")}


def untraceable_facts(generated_text, source_text, known_refs, known_amounts):
    """Reference numbers and amounts in the generated text that no source mentions."""
    findings = []
    source_upper = (source_text or "").upper()
    for ref in {r.upper() for r in ORDER_REF.findall(generated_text or "") + COMPLAINT_REF.findall(generated_text or "")}:
        if ref not in known_refs and ref not in source_upper:
            findings.append(("invented_reference", ref, "Reference number not found in the complaint, order or history."))
    allowed_amounts = known_amounts | _amounts(source_text)
    for amount in _amounts(generated_text):
        if amount not in allowed_amounts:
            findings.append(("invented_amount", f"{amount:g} USD", "Amount not found in the complaint, order or policies."))
    return findings
