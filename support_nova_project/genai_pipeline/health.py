"""
Is the AI provider usable right now? Answered from what actually happened (the latest analysis), plus an
optional on-demand check by an administrator, whichever is newer. A failure the model caused by answering
badly (invalid JSON) is not an outage: only API-level failures (key, balance, network, provider) count.
"""

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from .client import LLMError, chat_json
from .models import GenAIAnalysis

CHECK_KEY = "genai_last_check"


def _ok(since=None):
    return {"ok": True, "kind": None, "message": None, "since": since}


def _from_analyses():
    latest = GenAIAnalysis.objects.order_by("-created_at").first()
    if latest is None or latest.status == GenAIAnalysis.Status.SUCCESS:
        return _ok(latest.created_at if latest else None), latest
    api_failures = [a for a in latest.attempts if a.get("stage") == "api"]
    if not api_failures:
        return _ok(latest.created_at), latest
    last = api_failures[-1]
    message = (last.get("errors") or [latest.error])[0]
    return {"ok": False, "kind": last.get("kind") or "other", "message": message, "since": latest.created_at}, latest


def usage():
    """How many AI calls were made, how much of the input DeepSeek served from its context cache, and the speed."""
    from django.db.models import Avg, Count, Q, Sum

    def row(version, qs):
        a = qs.aggregate(calls=Count("id"), failed=Count("id", filter=Q(status=GenAIAnalysis.Status.FAILED)),
                         inp=Sum("prompt_tokens"), hit=Sum("cache_hit_tokens"), out=Sum("completion_tokens"),
                         lat=Avg("latency_ms", filter=Q(status=GenAIAnalysis.Status.SUCCESS)))
        inp, hit = a["inp"] or 0, a["hit"] or 0
        return {"prompt_version": version, "calls": a["calls"], "failed": a["failed"], "input_tokens": inp,
                "cached_tokens": hit, "cached_percent": round(100 * hit / inp, 1) if inp else 0.0,
                "output_tokens": a["out"] or 0, "average_seconds": round((a["lat"] or 0) / 1000, 1)}

    rows = []
    versions = sorted(set(GenAIAnalysis.objects.values_list("prompt_template__version", flat=True)), key=lambda v: [int(x) if x.isdigit() else x for x in v.split(".")])
    for version in versions:
        rows.append(row(version, GenAIAnalysis.objects.filter(prompt_template__version=version)))
    return {"total": row("all", GenAIAnalysis.objects.all()), "by_version": rows}


def current_status():
    result, latest = _from_analyses()
    checked = cache.get(CHECK_KEY)
    if checked and (latest is None or checked["since"] > latest.created_at):
        return checked
    return result


def run_check():
    """One tiny real request: proves the key, the balance, the model name and the network all work."""
    now = timezone.now()
    try:
        chat_json([{"role": "user", "content": 'Reply with this JSON only: {"ok": true}'}],
                  settings.DEEPSEEK_MODEL, 0, 20, thinking="disabled")
        result = {**_ok(now), "since": now}
    except LLMError as e:
        result = {"ok": False, "kind": e.kind, "message": str(e), "since": now}
    cache.set(CHECK_KEY, result, 24 * 3600)
    return result
