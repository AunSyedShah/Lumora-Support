"""
Split parsed blocks into section-based chunks.

A new chunk starts at every section heading such as "5.2 Compensation for Late Delivery".
Each chunk keeps its section number, heading and page, so a GenAI answer can cite
"REF-POL section 5.2" and Python can verify that the citation exists.
"""

import re
from dataclasses import dataclass

from .parsing import Block

# "5", "5.", "5.2", "5.2.1" followed by a title, e.g. "5.2 Compensation"
NUMBERED_HEADING = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,3})\.?\s+(\S.{0,120})$")
MAX_CHUNK_CHARS = 1500


@dataclass
class Chunk:
    section: str
    heading: str
    page: int | None
    text: str


def _is_heading(block: Block):
    """Return (section, heading) if the block looks like a heading, otherwise None."""
    text = block.text
    if len(text) > 120:
        return None
    match = NUMBERED_HEADING.match(text)
    if match and (block.heading_hint or not text.endswith((".", ":", ";", ","))):
        return match.group(1), match.group(2).strip()
    if block.heading_hint and len(text) <= 80:
        return "", text  # un-numbered heading (e.g. DOCX "Heading 1" style)
    return None


def _split_long(text, limit=MAX_CHUNK_CHARS):
    """Split an over-long section on sentence boundaries so each piece stays readable."""
    if len(text) <= limit:
        return [text]
    pieces, current = [], ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if current and len(current) + len(sentence) + 1 > limit:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces


def chunk_blocks(blocks: list[Block], skip_first: int = 0) -> list[Chunk]:
    """
    Group blocks into chunks. `skip_first` lets the caller drop the title/metadata header
    blocks so they don't become a chunk of their own.
    """
    sections = []  # list of [section, heading, page, [texts]]
    current = ["", "Introduction", None, []]

    for block in blocks[skip_first:]:
        heading = _is_heading(block)
        if heading:
            if current[3]:
                sections.append(current)
            current = [heading[0], heading[1], block.page, []]
        else:
            if current[2] is None:
                current[2] = block.page
            current[3].append(block.text)
    if current[3]:
        sections.append(current)

    chunks = []
    for section, heading, page, texts in sections:
        for piece in _split_long("\n".join(texts)):
            chunks.append(Chunk(section=section, heading=heading, page=page, text=piece))
    return chunks
