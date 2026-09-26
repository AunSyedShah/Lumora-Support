"""
Step 2 of the dataset: an LLM writes the complaint TEXT for each spec.

Kept separate from Pipeline 1 on purpose: its own prompt, its own client settings and its own
user_id, and it never sees the expected labels. The LLM only turns a scenario into a customer's
words; every label was already fixed by the spec.

Deterministic parts are done in code, not by the LLM:
  - prompt-injection payloads are inserted word for word (INJECTION_POSITIONS)
  - {ORDER_REF} / {PREVIOUS_REF} placeholders are filled in when the dataset is loaded
Each output is checked (length, placeholders, unwanted escalation triggers); a failed check is
retried once with a hint, and anything still wrong is kept but flagged for the human review.
"""

import copy
import json
import re
import time

import openai
from django.conf import settings
from django.db import connection

from rules.conditions import find_phrases, normalize_text
from rules.models import EscalationRule

from .expected import expected_labels
from .scenarios import LENGTHS, SCENARIOS, STYLES

WRITER_USER_ID = "supportnova-dataset-writer"  # not the pipeline's id: separate cache, separate usage
TEMPERATURE = 1.0  # variety matters more than consistency here
MAX_TOKENS = 900
MIN_WORDS = 25

CHANNEL_HINTS = {
    "web": "a web contact form (no greeting needed)",
    "email": "an e-mail (greeting and sign-off with a fictional first name)",
    "chat": "a live-chat message",
}
CUSTOMER_HINTS = {
    "standard": "a regular home customer",
    "premium": "a LumoraCare+ premium member (mention it only if it fits naturally)",
    "business": "a small business that uses Lumora devices in its office or shop",
}
# The expected labels depend on these fields; an extra trigger in the text is only a problem if it changes them.
LABEL_KEYS = ("category", "subcategory", "department", "supporting", "urgency", "priority", "escalation", "rule",
              "compensation")

SYSTEM_PROMPT = """You write realistic, synthetic customer complaints for testing a complaint-handling system.
The company is Lumora Home Technologies, a fictional smart-home company (hub, smart plugs and bulbs,
indoor and outdoor cameras, video doorbell, thermostat, smart lock, professional installation, and the
LumoraCare+ subscription with cloud recording).

Rules:
1. Write ONE complaint, as the customer, in the requested style, channel and length.
2. Include every listed fact, but in your own natural words. Do not copy the wording of the brief.
3. Do NOT add problems, facts or pressure that are not in the brief: no extra faults, no injuries,
   no safety hazards, no threats of legal action, regulators, social media or chargebacks, no mention
   of children, elderly or vulnerable people, unless the brief lists them.
4. Use relative time ("about three weeks ago", "last month"), never calendar dates.
5. Do not mention money amounts unless the brief gives them. Never invent order numbers,
   complaint numbers, phone numbers, e-mail addresses or card numbers. Use placeholders only
   where the brief tells you to, written exactly as given.
6. Only fictional first names. No real brands other than Lumora.
7. Answer in json only.

Example output:
{"title": "Thermostat stopped heating the house", "description": "Hi, my Lumora thermostat ...", "requested_resolution": "Please send a technician or replace it."}
"""

RETRY_HINT = "Your previous answer had these problems, fix them and answer again in json: {problems}"

NEAR_DUPLICATE_PROMPT = """A customer already sent the complaint below. A few hours later they send it AGAIN, almost
the same: keep nearly all the wording, change only a few words or one sentence, keep every fact and keep
any placeholder ({{ORDER_REF}}, {{PREVIOUS_REF}}) exactly as it is. Answer in json with the keys
"title", "description" and "requested_resolution".

Original title: {title}
Original complaint: {description}
Original requested resolution: {requested_resolution}"""


# ---------------- the brief for one spec ----------------

def roughly(days):
    """Customers talk about time roughly; the exact dates are in the order record."""
    if days <= 1:
        return "yesterday" if days == 1 else "today"
    if days < 14:
        return f"{days} days ago"
    if days < 60:
        return f"about {round(days / 7)} weeks ago"
    if days < 365:
        return f"about {round(days / 30.4)} months ago"
    years, months = divmod(round(days / 30.4), 12)
    year_text = "a year" if years == 1 else f"{years} years"
    return f"about {year_text} ago" if months == 0 else f"about {year_text} and {months} months ago"


def time_fact(spec):
    if not spec.has_order:
        return None
    if spec.order_status == "shipped":
        return f"The order was due about {spec.days_late} working days ago and has still not arrived."
    anchor = SCENARIOS[spec.subcategories[0]].anchor if spec.subcategories else "delivery"
    if anchor == "purchase":
        return f"It was bought {roughly(spec.days_since_purchase)}."
    return f"It was delivered {roughly(spec.days_since_delivery)}."


def brief(spec, product_names):
    lines = [
        f"Product: {product_names.get(spec.product, 'not specified') if spec.product else 'not specified - do not name a model'}",
        f"Channel: {CHANNEL_HINTS[spec.channel]}",
        f"Customer: {CUSTOMER_HINTS.get(spec.customer_type, 'a customer')}",
    ]
    if spec.subcategories:
        lines.append("What happened:")
        lines += [f"- {SCENARIOS[code].situation}" for code in spec.subcategories]
    # When the customer makes a false claim, the true dates stay in the order record only.
    facts = [] if spec.claims else [time_fact(spec)]
    if spec.has_order and (spec.quantity > 1 or spec.subcategories[0] in ("DUPLICATE_CHARGE", "INCORRECT_CHARGE")):
        facts.append(f"The order was for {spec.quantity} unit(s), {spec.amount:.2f} USD in total.")
    facts += [f"Make this detail clear: {phrase}" for phrase in spec.key_facts]
    facts += [f"The customer states (it may not be true, write it as a fact they believe): {claim}"
              for claim in spec.claims]
    facts = [f for f in facts if f]
    if facts:
        lines.append("Facts to include:")
        lines += [f"- {f}" for f in facts]
    if spec.extra:
        lines.append(f"Note: {spec.extra}")
    if spec.order_ref_in == "text":
        lines.append("Mention the order number, written exactly as {ORDER_REF}.")
    else:
        lines.append("Do not mention an order number.")
    if spec.group == "repeat":
        lines.append("You may refer to the earlier complaint number, written exactly as {PREVIOUS_REF}.")
    lines.append(f"The customer wants: {spec.wants}")
    lines.append(f"Style: {STYLES[spec.style]}")
    lines.append(f"Length of the description: {LENGTHS[spec.length]}")
    return "\n".join(lines)


def writer_messages(spec, product_names, original=None):
    if original is not None:  # near-duplicate: reword the original lightly
        return [{"role": "user", "content": NEAR_DUPLICATE_PROMPT.format(**original)}]
    return [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Write the complaint in json for this brief:\n{brief(spec, product_names)}"}]


# ---------------- checks ----------------

def escalation_keywords():
    """Escalation-rule trigger phrases, used only to find text that says MORE than the spec."""
    return {rule.rule_id: rule.conditions["keywords_any"]
            for rule in EscalationRule.objects.filter(is_active=True) if "keywords_any" in rule.conditions}


def check_text(spec, text, keywords, changes_labels=None, original=None):
    """
    Problems with one generated complaint (empty list = fine). An escalation trigger the spec did
    not ask for is a problem only when it would change the expected labels (changes_labels);
    e.g. "it gave me a shock" in an electric-shock complaint changes nothing.
    """
    problems = []
    description = text.get("description", "")
    if original and normalize_text(description) == normalize_text(original["description"]):
        problems.append("it is identical to the original complaint; change a few words or one sentence")
    if not text.get("title") or len(text["title"]) < 5:
        problems.append("the title is missing or too short")
    if len(description.split()) < MIN_WORDS:
        problems.append(f"the description has fewer than {MIN_WORDS} words")
    full = f"{text.get('title', '')} {description} {text.get('requested_resolution', '')}"
    if spec.order_ref_in == "text" and "{ORDER_REF}" not in full:
        problems.append("the order number placeholder {ORDER_REF} is missing")
    if spec.order_ref_in != "text" and "{ORDER_REF}" in full:
        problems.append("the order number must not be mentioned")
    if re.search(r"\b(ORD|CMP)-\d+", full):
        problems.append("it invents an order or complaint number; use only the placeholders")
    normalized = normalize_text(full)
    allowed = set(spec.expected.get("escalation_rules", [])) if spec.expected else set()
    if spec.group == "repeat":
        allowed.add("ESC-018")  # "this is the third time" is simply true for a follow-up complaint
    allowed_words = {k.lower() for k in spec.key_facts}
    for rule_id, phrases in keywords.items():
        hits = [p for p in find_phrases(phrases, normalized) if p not in allowed_words]
        if hits and rule_id not in allowed and (changes_labels is None or changes_labels(spec, hits)):
            problems.append(f"it mentions {hits}, which is not part of this complaint - remove it")
    return problems


# ---------------- deterministic edits ----------------

def insert_injection(spec, text):
    if not spec.injection:
        return text
    text = dict(text)
    payload, description = spec.injection, text["description"]
    if spec.injection_position == "start":
        text["description"] = f"{payload}\n\n{description}"
    elif spec.injection_position == "middle":
        sentences = re.split(r"(?<=[.!?])\s+", description)
        middle = max(1, len(sentences) // 2)
        text["description"] = " ".join(sentences[:middle] + [payload] + sentences[middle:])
    elif spec.injection_position == "end":
        text["description"] = f"{description}\n\n{payload}"
    else:
        text["supporting_information"] = payload
    return text


# ---------------- the API call ----------------

class WriterError(Exception):
    pass


_client = None


def _get_client():
    global _client
    if _client is None:
        if not settings.DEEPSEEK_API_KEY:
            raise WriterError("DEEPSEEK_API_KEY is not configured.")
        _client = openai.OpenAI(api_key=settings.DEEPSEEK_API_KEY, base_url=settings.DEEPSEEK_BASE_URL,
                                timeout=60, max_retries=2)
    return _client


def call_writer(messages, model):
    response = _get_client().chat.completions.create(
        model=model,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        extra_body={"user_id": WRITER_USER_ID, "thinking": {"type": "disabled"}},
    )
    content = response.choices[0].message.content or ""
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        data = {}
    text = {key: str(data.get(key) or "").strip() for key in ("title", "description", "requested_resolution")}
    usage = response.usage
    return text, (usage.prompt_tokens if usage else 0), (usage.completion_tokens if usage else 0)


def labels_changer(product_names):
    """changes_labels(spec, phrases): would these extra phrases change the expected labels?"""
    def changes_labels(spec, phrases):
        trial = copy.copy(spec)
        trial.key_facts = list(spec.key_facts) + list(phrases)
        new = expected_labels(trial, product_names)
        return any(new[key] != spec.expected.get(key) for key in LABEL_KEYS)
    return changes_labels


def write_complaint(spec, product_names, keywords, model, original=None):
    """Generate, check, retry once with a hint. Returns a record for generated_text.jsonl."""
    try:
        return _write_complaint(spec, product_names, keywords, model, original)
    finally:
        connection.close()  # runs in a worker thread: close its own database connection


def _write_complaint(spec, product_names, keywords, model, original):
    messages = writer_messages(spec, product_names, original)
    started = time.monotonic()
    tokens_in = tokens_out = 0
    for attempt in (1, 2):
        text, used_in, used_out = call_writer(messages, model)
        tokens_in, tokens_out = tokens_in + used_in, tokens_out + used_out
        problems = check_text(spec, text, keywords, labels_changer(product_names), original)
        if not problems:
            break
        messages = messages + [{"role": "assistant", "content": json.dumps(text)},
                               {"role": "user", "content": RETRY_HINT.format(problems="; ".join(problems))}]
    text["supporting_information"] = ""
    text = insert_injection(spec, text)
    return {
        "case_id": spec.case_id,
        **text,
        "flags": problems,  # still wrong after the retry -> a human checks it
        "attempts": attempt,
        "model": model,
        "prompt_tokens": tokens_in,
        "completion_tokens": tokens_out,
        "seconds": round(time.monotonic() - started, 1),
    }
