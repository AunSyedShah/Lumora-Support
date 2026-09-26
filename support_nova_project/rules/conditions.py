"""
The small "condition language" used by both rule types.

A rule's conditions are a dict; every key present must be satisfied (AND).
List values are alternatives (OR). Example:
    {"categories": ["SAFETY"], "keywords_any": ["child", "baby"]}
    -> category is SAFETY  AND  the text mentions "child" or "baby"

In CSV files the same thing is written as:
    categories=SAFETY;keywords_any=child|baby
"""

import re
import unicodedata
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict


class Conditions(BaseModel):
    """Allowed condition keys. Unknown keys are rejected so typos can't silently disable a rule."""

    model_config = ConfigDict(extra="forbid")

    categories: list[str] | None = None
    subcategories: list[str] | None = None
    keywords_any: list[str] | None = None
    customer_types: list[str] | None = None
    products: list[str] | None = None
    min_amount: float | None = None
    max_amount: float | None = None
    min_days_since_purchase: int | None = None
    max_days_since_purchase: int | None = None
    min_days_since_delivery: int | None = None
    max_days_since_delivery: int | None = None
    min_days_late: int | None = None
    min_previous_complaints: int | None = None


LIST_KEYS = {"categories", "subcategories", "keywords_any", "customer_types", "products"}

# numeric condition -> (fact name, comparison)
NUMERIC_KEYS = {
    "min_amount": ("amount", "min"),
    "max_amount": ("amount", "max"),
    "min_days_since_purchase": ("days_since_purchase", "min"),
    "max_days_since_purchase": ("days_since_purchase", "max"),
    "min_days_since_delivery": ("days_since_delivery", "min"),
    "max_days_since_delivery": ("days_since_delivery", "max"),
    "min_days_late": ("days_late", "min"),
    "min_previous_complaints": ("previous_complaints", "min"),
}


@dataclass
class Facts:
    """Everything the rule engine knows about one complaint. None = not known."""

    text: str = ""
    customer_type: str | None = None
    product: str | None = None
    amount: float | None = None
    days_since_purchase: int | None = None
    days_since_delivery: int | None = None
    days_late: int | None = None
    previous_complaints: int = 0
    # filled in by the engine after classification:
    categories: set = field(default_factory=set)
    subcategories: set = field(default_factory=set)


def normalize_text(text):
    text = unicodedata.normalize("NFKC", text or "").lower()
    text = text.replace("’", "'").replace("‘", "'")  # curly apostrophes
    return re.sub(r"\s+", " ", text).strip()


NEAR_WORDS = 10  # "refund ~ refused": both parts within this many words of each other, in either order


def _phrase_starts(phrase, words):
    target = phrase.split()
    return [i for i in range(len(words) - len(target) + 1) if words[i:i + len(target)] == target]


def _near(phrase, normalized_text):
    """Word positions where 'a ~ b' matches (a and b close together), or [] if it does not."""
    left, right = (part.strip().lower() for part in phrase.split("~", 1))
    words = re.findall(r"[\w']+", normalized_text)
    a, b = _phrase_starts(left, words), _phrase_starts(right, words)
    return sorted({min(i, j) for i in a for j in b if abs(i - j) <= NEAR_WORDS})


def find_phrases(phrases, normalized_text):
    """
    Return the phrases that appear in the text as whole words (so 'sue' doesn't match 'issue').
    A phrase written as "a ~ b" matches when a and b appear close together, e.g. "refund ~ refused"
    matches "my refund request was refused" and "they refused the refund".
    """
    found = []
    for phrase in phrases:
        if "~" in phrase:
            if _near(phrase, normalized_text):
                found.append(phrase)
            continue
        pattern = r"(?<![\w])" + re.escape(phrase.lower()) + r"(?![\w])"
        if re.search(pattern, normalized_text):
            found.append(phrase)
    return found


def first_position(phrases, normalized_text):
    positions = []
    for phrase in phrases:
        if "~" in phrase:
            near = _near(phrase, normalized_text)
            if near:  # a word index; convert to a character position for comparison
                words = re.findall(r"[\w']+", normalized_text)
                positions.append(normalized_text.find(words[near[0]]))
        else:
            positions.append(normalized_text.find(phrase.lower()))
    positions = [p for p in positions if p >= 0]
    return min(positions) if positions else len(normalized_text)


@dataclass
class MatchResult:
    matched: bool
    reasons: list[str] = field(default_factory=list)  # why it matched (for explanations)
    missing_facts: list[str] = field(default_factory=list)  # facts we'd need to decide


def evaluate_conditions(conditions: dict, facts: Facts, normalized_text: str) -> MatchResult:
    reasons, missing = [], []

    for key, value in conditions.items():
        if key == "categories":
            if not facts.categories & set(value):
                return MatchResult(False)
            reasons.append(f"category in {value}")
        elif key == "subcategories":
            if not facts.subcategories & set(value):
                return MatchResult(False)
            reasons.append(f"subcategory in {value}")
        elif key == "keywords_any":
            hits = find_phrases(value, normalized_text)
            if not hits:
                return MatchResult(False)
            reasons.append(f"text mentions {hits}")
        elif key == "customer_types":
            if facts.customer_type is None:
                missing.append("customer_type")
            elif facts.customer_type not in value:
                return MatchResult(False)
            else:
                reasons.append(f"customer type is {facts.customer_type}")
        elif key == "products":
            if facts.product is None:
                missing.append("product")
            elif facts.product.lower() not in [p.lower() for p in value]:
                return MatchResult(False)
            else:
                reasons.append(f"product is {facts.product}")
        elif key in NUMERIC_KEYS:
            fact_name, kind = NUMERIC_KEYS[key]
            actual = getattr(facts, fact_name)
            if actual is None:
                missing.append(fact_name)
            elif (kind == "min" and actual < value) or (kind == "max" and actual > value):
                return MatchResult(False)
            else:
                reasons.append(f"{fact_name}={actual} ({key}={value})")

    if missing:
        return MatchResult(False, reasons, missing)
    return MatchResult(True, reasons)


# ---------------- CSV text <-> dict ----------------


def parse_conditions_text(text: str) -> dict:
    """'min_amount=500;keywords_any=lawyer|legal action' -> validated dict."""
    raw = {}
    for part in (text or "").split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError(f"Condition '{part}' must look like key=value.")
        key, value = (x.strip() for x in part.split("=", 1))
        if key in LIST_KEYS:
            raw[key] = [v.strip() for v in value.split("|") if v.strip()]
        else:
            raw[key] = value
    return clean_conditions(raw)


def clean_conditions(raw: dict) -> dict:
    """Validate with the Conditions model and drop empty keys. Raises ValueError on bad input."""
    conditions = Conditions.model_validate(raw).model_dump(exclude_none=True)
    for key in ("keywords_any", "customer_types"):
        if key in conditions:
            conditions[key] = [v.lower() for v in conditions[key]]
    for key in ("categories", "subcategories"):
        if key in conditions:
            conditions[key] = [v.upper() for v in conditions[key]]
    return conditions


def format_conditions(conditions: dict) -> str:
    parts = []
    for key, value in conditions.items():
        if isinstance(value, list):
            value = "|".join(value)
        elif isinstance(value, float) and value.is_integer():
            value = int(value)
        parts.append(f"{key}={value}")
    return ";".join(parts)
