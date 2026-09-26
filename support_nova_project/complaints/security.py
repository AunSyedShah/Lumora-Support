"""
Prompt-injection / manipulation detection (SRS Steps 50-51).

Complaint text is UNTRUSTED DATA. These patterns do not block a complaint - a real customer may
quote such phrases - they only raise flags. The flags are shown to staff, stored for the audit
trail, and later make the GenAI pipeline treat the case with extra suspicion (manual review).
The actual protection is structural: complaint text is always passed to the model as data,
and the Python validation pipeline never takes instructions from it.
"""

import re

INJECTION_PATTERNS = {
    "ignore_instructions": r"\b(ignore|disregard|forget|override)\b.{0,40}\b(instructions?|rules|previous|prompts?|polic(y|ies)|guidelines|(rule )?matrix)\b"
                           r"|\b(ignore|disregard)\b.{0,15}\b(actual|real|above|following) complaint\b",
    "role_override": r"\b(you are now|act as (an?|the)|pretend (to be|you are)|system prompt|developer mode|jailbreak|new instructions?)\b"
                     r"|\bnote to the (ai|assistant|model|bot|system)\b|\[\s*(assistant|system|ai)\s*:"
                     r"|\b(print|reveal|show|repeat|output)\b.{0,20}\bprompt\b",
    # closing or opening the tags that wrap the complaint in the prompt, to "escape" from the data
    "delimiter_escape": r"<\s*/?\s*(complaint|system|assistant|instructions?)\s*>",
    "fake_authority": r"\b(admin(istrator)?|developer|system|manager|supervisor|ceo|lumora (staff|team))\b.{0,25}\b(override|has approved|approved this|authori[sz]e[ds]?|instructs?|says you must)\b"
                      r"|\bi authori[sz]e you\b",
    # Orders to the system about its own decision. A customer demanding a refund ("refund me
    # immediately", "approve my refund now") is a normal complaint, not an attack, and is not flagged.
    "forced_outcome": r"\b(you must|you have to|you are required to|automatically)\b.{0,30}\b(approve|grant|mark|classify)\b"
                      r"|\b(you must|you have to)\s+(reply|respond|say|write)\s+that\b",
    "embedded_policy_claim": r"\b(according to|per|under|as stated in)\b.{0,15}\b(your|the|lumora'?s?)\b.{0,15}\b(new|updated|secret|internal|latest)?\s*(policy|rule|terms)\b.{0,60}\b(entitled|must|guarantee[sd]?|owe)\b",
    "output_manipulation": r"[\"'](priority|urgency|escalation_required|escalation_level|category|subcategory|department|compensation|verification_status)[\"']\s*:"
                           r"|\b(priority|urgency|escalation_required|category|compensation)\s*[:=]\s*[\"']?(p[0-3]|low|medium|high|critical|true|false|none|full_refund)\b"
                           r"|\b(respond|reply|output|answer)\b.{0,15}\b(only )?(with|in) json\b|\bjson\b.{0,20}\b(as )?your answer\b"
                           r"|\b(classify|mark|label|categori[sz]e|route)\b.{0,15}\b(this|the|my)\s+(complaint|ticket|case)\b.{0,10}\bas\b",
}

_COMPILED = {name: re.compile(pattern, re.IGNORECASE | re.DOTALL) for name, pattern in INJECTION_PATTERNS.items()}


def detect_injection(text):
    """Return a list like [{"flag": "ignore_instructions", "excerpt": "ignore your rules"}]."""
    flags = []
    for name, pattern in _COMPILED.items():
        match = pattern.search(text)
        if match:
            flags.append({"flag": name, "excerpt": match.group(0)[:120]})
    return flags
