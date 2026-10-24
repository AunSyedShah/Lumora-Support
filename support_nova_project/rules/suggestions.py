"""
Teach the rules from experience: suggest key phrases for the rule engine.

The AI often recognises a complaint the rule engine could not classify (no key phrase matched), and
reviewers sometimes reclassify a complaint the rules got wrong. Both are lessons for the RULES, so
this module mines those complaints for short phrases that point at one problem, and offers them to an
administrator, who adds each one with a click.

Why the rules and not the AI prompt: Pipeline 1 (AI) and Pipeline 2 (rules) must stay independent -
putting past rule results into the prompt would let the AI copy the rules and make the comparison
meaningless. Improving the rules keeps the independent check and makes it stronger. A person approves
every change; nothing is added automatically.

Safety: complaints with a prompt-injection flag are never used, and only whole-word phrases of two or
three words are suggested (the same matching the rule engine uses).
"""

import re
from collections import Counter, defaultdict

from catalog.models import Subcategory
from complaints.models import Complaint
from python_validation.models import ValidationResult
from workflow.models import AuditLog

from .conditions import find_phrases

STOPWORDS = frozenset("""
a about after again all also am an and any are as at be because been before being but by can could did do does
for from get got had has have he her here him his how i if in into is it its just me my no not of off on one
or our out over please she so some than that the their them then there these they this to too up us very was
we were what when where which while who why will with would you your hi hello dear thanks thank regards
""".split())
MIN_SEEN = 2  # a phrase must appear in at least this many teaching complaints of the same problem
MIN_PRECISION = 0.8  # share of ALL complaints containing the phrase that belong to that problem
# A single word is a broader key than a phrase, so it has to earn it: more evidence, higher precision.
SINGLE_WORD_MIN_SEEN = 3
SINGLE_WORD_MIN_PRECISION = 0.9
SINGLE_WORD_MIN_LENGTH = 7
CONTRACTION = re.compile(r"'(s|m|ve|d|ll|re)$")  # it's, I'm, I've ... are filler, not content (doesn't, won't are kept)
SEGMENT = re.compile(r"[^\w'\s]+")  # punctuation ends a phrase: "plug, sparked" is not the phrase "plug sparked"


def _phrases(text):
    """Two- and three-word phrases that start and end on a meaningful word."""
    found = set()
    for segment in SEGMENT.split(text or ""):
        words = segment.split()
        for word in words:
            if word.isalpha() and len(word) >= SINGLE_WORD_MIN_LENGTH and word not in STOPWORDS:
                found.add(word)
        for size in (2, 3):
            for i in range(len(words) - size + 1):
                gram = words[i:i + size]
                if not all(w.isalpha() or "'" in w for w in gram):
                    continue  # numbers and codes (order numbers, model numbers) are not reusable phrases
                if any(w in STOPWORDS or CONTRACTION.search(w) for w in (gram[0], gram[-1])) or any(len(w) < 3 for w in gram):
                    continue
                if sum(w not in STOPWORDS and len(w) >= 4 for w in gram) < 2:
                    continue  # needs at least two real content words, or it is too generic
                found.add(" ".join(gram))
    return found


def teaching_complaints():
    """Complaints whose final problem is known from a person or the AI, but the rules missed or got wrong."""
    latest = {}
    for result in ValidationResult.objects.select_related("complaint").order_by("created_at"):
        latest[result.complaint_id] = result
    reclassified = set(AuditLog.objects.filter(action=AuditLog.Action.RECLASSIFIED).values_list("complaint_id", flat=True))
    chosen = []
    for result in latest.values():
        complaint = result.complaint
        if not complaint.subcategory_id or complaint.security_flags:
            continue
        rule_pick = (result.independent_expected or {}).get("subcategory")
        if rule_pick is None or complaint.pk in reclassified:
            chosen.append(complaint)
    return chosen


def _rule_picks():
    """complaint id -> the problem the rule engine chose on its own (None = could not classify)."""
    picks = {}
    for result in ValidationResult.objects.order_by("created_at"):
        picks[result.complaint_id] = (result.independent_expected or {}).get("subcategory")
    return picks


def mine_keywords(evidence, universe, picks, existing, per_problem=3, limit=20):
    """
    The mining itself, free of the database so it can be tested and measured.
      evidence  [(id, problem code, normalized text)]  complaints to learn from
      universe  [(id, problem code, normalized text)]  every complaint with a known problem (to check precision)
      picks     {id: problem the rule engine chose, or None}
      existing  phrases that already are key phrases somewhere
    Returns [{subcategory, phrase, seen_in, also_in_other_problems, examples}] best first.
    """
    teaching_ids = {pk for pk, _, _ in evidence}
    seen = defaultdict(Counter)  # problem code -> phrase -> number of teaching complaints
    where = defaultdict(list)  # (problem code, phrase) -> ids
    for pk, code, text in evidence:
        for phrase in _phrases(text):
            seen[code][phrase] += 1
            where[(code, phrase)].append(pk)

    suggestions = []
    for code, counter in seen.items():
        chosen = []
        for phrase, count in sorted(counter.items(), key=lambda kv: (-kv[1], len(kv[0].split()), kv[0])):
            single = " " not in phrase
            if count < (SINGLE_WORD_MIN_SEEN if single else MIN_SEEN):
                continue
            if phrase in existing or any(phrase in c or c in phrase for c in chosen):
                continue
            inside = other = 0
            for pk, sub, text in universe:
                if not find_phrases([phrase], text):
                    continue
                # "elsewhere" = the final problem is another one, OR the rules already put it somewhere else
                # (a complaint a person reclassified is a teaching case, so the rules' old answer does not count)
                rule_pick = picks.get(pk)
                elsewhere = sub != code or (rule_pick not in (None, code) and pk not in teaching_ids)
                inside, other = (inside, other + 1) if elsewhere else (inside + 1, other)
            if not inside or inside / (inside + other) < (SINGLE_WORD_MIN_PRECISION if single else MIN_PRECISION):
                continue
            chosen.append(phrase)
            suggestions.append({"subcategory": code, "phrase": phrase, "seen_in": count,
                                "also_in_other_problems": other, "examples": where[(code, phrase)][:3]})
            if len(chosen) == per_problem:
                break
    suggestions.sort(key=lambda s: (-s["seen_in"], s["also_in_other_problems"], s["phrase"]))
    return suggestions[:limit]


def keyword_suggestions(per_problem=3, limit=20):
    """[{subcategory, subcategory_name, phrase, seen_in, also_in_other_problems, examples}] best first."""
    teaching = teaching_complaints()
    if not teaching:
        return []
    existing = {keyword.lower() for keywords in Subcategory.objects.values_list("keywords", flat=True) for keyword in keywords}
    universe = list(Complaint.objects.exclude(subcategory=None).values_list("pk", "subcategory__code", "normalized_text"))
    evidence = [(c.pk, c.subcategory.code, c.normalized_text) for c in teaching]
    names = dict(Subcategory.objects.values_list("code", "name"))
    ids = dict(Complaint.objects.filter(pk__in={pk for s in evidence for pk in [s[0]]}).values_list("pk", "complaint_id"))
    found = mine_keywords(evidence, universe, _rule_picks(), existing, per_problem, limit)
    return [{**s, "subcategory_name": names.get(s["subcategory"], s["subcategory"]),
             "examples": [ids.get(pk, str(pk)) for pk in s["examples"]]} for s in found]
