"""
Complaint pre-processing (SRS Step 11): sanitise, normalise, mask sensitive data, extract metadata.
"""

import hashlib
import html
import re
import unicodedata

from django.utils.html import strip_tags

from rules.conditions import normalize_text

# Control characters and invisible "zero-width" characters that can hide text from humans
# (a known trick for smuggling instructions past reviewers). Newlines and tabs are kept.
INVISIBLE_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏ -‮⁠-⁤﻿]")

# 13-19 digits, optionally separated by spaces or dashes (card-number shape).
CARD_CANDIDATE = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")

ORDER_REF = re.compile(r"\bORD-\d{5}\b", re.IGNORECASE)
COMPLAINT_REF = re.compile(r"\bCMP-\d{5}\b", re.IGNORECASE)
AMOUNT = re.compile(r"(?:\$|usd\s?|£|€)\s?(\d{1,6}(?:[.,]\d{2})?)|\b(\d{1,6}(?:\.\d{2})?)\s?(?:usd|dollars)\b", re.IGNORECASE)
ISO_DATE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")


def sanitize(text):
    """Remove HTML, invisible characters and messy whitespace. Keeps line breaks."""
    text = html.unescape(strip_tags(text or ""))
    text = unicodedata.normalize("NFKC", text)
    text = INVISIBLE_CHARS.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(line.strip() for line in text.split("\n")).strip()


def _passes_luhn(digits):
    """Standard card-number checksum; avoids masking ordinary long numbers."""
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d)
        if i % 2 == 1:
            n = n * 2 - 9 if n * 2 > 9 else n * 2
        total += n
    return total % 10 == 0


def mask_card_numbers(text):
    """Replace anything that looks like a real card number. Returns (text, how_many_masked)."""
    count = 0

    def replace(match):
        nonlocal count
        digits = re.sub(r"\D", "", match.group())
        if 13 <= len(digits) <= 19 and _passes_luhn(digits):
            count += 1
            return f"[CARD ENDING {digits[-4:]}]"
        return match.group()

    return CARD_CANDIDATE.sub(replace, text), count


def extract_metadata(text):
    """Reference numbers, amounts, dates and e-mails mentioned in the complaint text."""
    amounts = []
    for m in AMOUNT.finditer(text):
        value = (m.group(1) or m.group(2)).replace(",", ".")
        amounts.append(float(value))
    return {
        "order_refs": sorted({r.upper() for r in ORDER_REF.findall(text)}),
        "complaint_refs": sorted({r.upper() for r in COMPLAINT_REF.findall(text)}),
        "amounts": amounts,
        "dates": ISO_DATE.findall(text),
        "emails": EMAIL.findall(text),
    }


def normalized_for_matching(title, description):
    return normalize_text(f"{title}. {description}")


def text_fingerprint(normalized):
    """Hash used to spot exact duplicates (ignores case, spacing and punctuation)."""
    letters_only = re.sub(r"[^a-z0-9]+", " ", normalized).strip()
    return hashlib.sha256(letters_only.encode()).hexdigest()
