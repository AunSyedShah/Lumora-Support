"""
Answer one customer question from the shared company documents (retrieval-augmented generation).

  1. clean the question (markup, card numbers) and refuse obvious attempts to hijack the assistant
  2. look up the best matching excerpts, only in the documents an administrator shared
  3. no excerpts -> say so without calling the AI at all (cheaper, and it cannot make something up)
  4. otherwise the Agno agent answers from those excerpts only, or says it cannot ([[NO_ANSWER]])
Every exchange is recorded for administrators, without any link to the person who asked.
"""

import time

from agno.exceptions import ModelAuthenticationError, ModelProviderError
from django.conf import settings
from django.core.cache import cache

from complaints.preprocessing import mask_card_numbers, sanitize
from complaints.security import detect_injection
from genai_pipeline.client import FRIENDLY
from knowledge_base.retrieval import hybrid_search

from .agent import NO_ANSWER, build_agent, run
from .models import ChatbotSettings, ChatExchange

MAX_QUESTION = 600
MAX_TURNS = 6  # earlier messages of the same chat that are sent along
MAX_TURN_CHARS = 800

NOT_FOUND = "I couldn’t find that in our policies. If you tell us what happened, the team will look at your case."
BLOCKED = "I can only answer questions about Lumora’s policies, orders and products. What would you like to know?"
UNAVAILABLE = "I’m not available right now. You can still tell us what happened and the team will reply."
PREFIX = "Lumora Home Technologies - "


class ChatError(Exception):
    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


def _clean(text, limit):
    return mask_card_numbers(sanitize(text))[0][:limit]


def check_rate(user):
    """At most CHATBOT_RATE_LIMIT questions per user in a window; nothing about the user is stored."""
    key = f"chatbot-rate-{user.pk}"
    cache.add(key, 0, settings.CHATBOT_RATE_WINDOW_SECONDS)
    if cache.incr(key) > settings.CHATBOT_RATE_LIMIT:
        raise ChatError("You’ve asked a lot of questions in a short time. Please wait a few minutes and try again.", 429)


def _history(history):
    """The last few turns of this chat, cleaned. Anything that tries to give the assistant orders is dropped."""
    turns = []
    for turn in history[-MAX_TURNS:]:
        role = "assistant" if turn.role == "assistant" else "user"
        text = _clean(turn.text, MAX_TURN_CHARS)
        if text and not detect_injection(text):
            turns.append((role, text))
    return turns


def error_kind(error):
    """Which of genai_pipeline.client.FRIENDLY an Agno / provider error is."""
    if isinstance(error, ModelAuthenticationError):
        return "not_configured" if not settings.DEEPSEEK_API_KEY else "auth"
    if isinstance(error, ModelProviderError):
        status = error.status_code
        known = {401: "auth", 402: "balance", 429: "rate_limit", 400: "rejected", 404: "rejected"}
        return known.get(status) or ("unavailable" if status >= 500 else "other")
    return "other"


def _excerpts(hits):
    parts, sources = [], []
    for number, hit in enumerate(hits, start=1):
        chunk = hit["chunk"]
        title = chunk.document.title.removeprefix(PREFIX)
        place = " ".join(x for x in (f"section {chunk.section}" if chunk.section else "", chunk.heading) if x)
        parts.append(f"[{number}] {title} ({chunk.document.get_doc_type_display()}){' - ' + place if place else ''}\n{chunk.text}")
        if not any(s["title"] == title for s in sources):
            sources.append({"title": title, "section": chunk.section})
    return "\n\n".join(parts), sources


def find_excerpts(query, config=None):
    """The shared document passages that match, as (text for the assistant, [{title, section}]); ("", []) if none do."""
    config = config or ChatbotSettings.get()
    hits = hybrid_search(query, limit=settings.CHATBOT_CHUNKS, doc_ids=config.shared_docs)
    hits = [h for h in hits if (h.get("keyword_score") or 0) >= 3 or (h.get("semantic_score") or 0) >= settings.CHATBOT_MIN_SIMILARITY]
    return _excerpts(hits) if hits else ("", [])


def _record(question, status, answer, started, sources=(), error_kind="", result=None):
    metrics = getattr(result, "metrics", None)
    ChatExchange.objects.create(
        question=question, answer=answer, status=status, sources=list(sources), error_kind=error_kind,
        input_tokens=getattr(metrics, "input_tokens", 0) or 0, output_tokens=getattr(metrics, "output_tokens", 0) or 0,
        latency_ms=int((time.monotonic() - started) * 1000),
    )
    return {"answer": answer, "status": status, "sources": list(sources), "suggest_complaint": status != ChatExchange.Status.ANSWERED}


def ask(question, history=()):
    started = time.monotonic()
    config = ChatbotSettings.get()
    if not config.enabled:
        raise ChatError("The chat assistant is switched off right now.", 403)
    clean = _clean(question, MAX_QUESTION)
    if not clean:
        raise ChatError("Please type a question.", 400)
    if detect_injection(clean):
        return _record(clean, ChatExchange.Status.BLOCKED, BLOCKED, started)

    turns = _history(history)
    earlier = [text for role, text in turns if role == "user"][-1:]  # a follow-up ("and for opened items?") needs the topic before it
    excerpts, sources = find_excerpts(" ".join([*earlier, clean]), config)
    if not excerpts:
        return _record(clean, ChatExchange.Status.UNANSWERED, NOT_FOUND, started)

    try:
        result = run(build_agent(), turns, clean, excerpts)
    except Exception as e:  # provider down, key, balance ... - the customer gets a calm message, the administrator the reason
        return _record(clean, ChatExchange.Status.FAILED, UNAVAILABLE, started, error_kind=error_kind(e))
    text = str(result.content or "").strip()
    if not text or NO_ANSWER in text:
        return _record(clean, ChatExchange.Status.UNANSWERED, NOT_FOUND, started, result=result)
    return _record(clean, ChatExchange.Status.ANSWERED, text, started, sources=sources, result=result)
