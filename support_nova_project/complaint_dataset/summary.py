"""Dataset coverage against the SRS minimums (printed by the commands, also used by the tests)."""

from collections import Counter

# (label, how to count it, SRS minimum)
SRS_MINIMUMS = [
    ("unique complaints", lambda specs: len(specs), 500),
    ("ambiguous or multi-issue", lambda specs: sum(bool({"ambiguous", "multi_issue"} & set(s.case_types)) for s in specs), 25),
    ("contradictory or difficult policy", lambda specs: sum(s.group in ("contradictory", "difficult_policy") for s in specs), 20),
    ("prompt-injection / adversarial", lambda specs: sum(s.group == "prompt_injection" for s in specs), 20),
    ("repeated or near-duplicate", lambda specs: sum(s.group in ("repeat", "near_duplicate") for s in specs), 25),
]
MIX = ["simple", "multi_issue", "incomplete", "emotional", "calm_critical", "high_priority", "low_priority",
       "repeated", "contradictory", "policy_exception", "unsupported_refund", "security", "privacy", "safety"]


def coverage(specs):
    tags = Counter(t for s in specs for t in s.case_types)
    return {
        "minimums": [(label, count(specs), minimum) for label, count, minimum in SRS_MINIMUMS],
        "mix": [(tag, tags[tag]) for tag in MIX],
        "groups": Counter(s.group for s in specs),
        "splits": Counter(s.split for s in specs),
        "categories": len({s.expected["category"] for s in specs if s.expected["category"]}),
        "subcategories": len({s.expected["subcategory"] for s in specs if s.expected["subcategory"]}),
        "departments": len({s.expected["department"] for s in specs if s.expected["department"]}),
        "rules": len({s.expected["rule"] for s in specs if s.expected["rule"]}),
        "escalation_rules": len({r for s in specs for r in s.expected["escalation_rules"]}),
    }


def coverage_lines(specs):
    c = coverage(specs)
    lines = ["SRS minimums:"]
    lines += [f"  {'OK ' if n >= m else 'LOW'} {label}: {n} (minimum {m})" for label, n, m in c["minimums"]]
    lines.append("Complaint mix: " + ", ".join(f"{tag} {n}" for tag, n in c["mix"]))
    lines.append("Groups: " + ", ".join(f"{g} {n}" for g, n in c["groups"].most_common()))
    lines.append(f"Split: {dict(c['splits'])}")
    lines.append(f"Expected labels use {c['categories']} categories, {c['subcategories']} subcategories, "
                 f"{c['departments']} departments, {c['rules']} resolution rules, {c['escalation_rules']} escalation rules")
    return lines
