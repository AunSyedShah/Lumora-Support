"""
Pipeline 1 - Python GenAI Complaint Intelligence Pipeline.

    active prompt -> context (own policy retrieval) -> DeepSeek JSON call -> parse -> validate
                  -> [controlled retry with the validation errors, max GENAI_MAX_ATTEMPTS]
                  -> GenAIAnalysis record (success, or failed -> manual review)

Retry strategy (SRS Step 47):
  - empty / invalid JSON / schema errors: retry, telling the model exactly what was wrong
  - network, timeout, rate limit, 5xx:   retry after a short pause (1s, 2s, ...)
  - authentication / bad request / insufficient balance / content filter: stop immediately
Every attempt is recorded, and the number of attempts is capped, so there are no infinite retries.
"""

import time

from django.conf import settings

from complaints.models import Complaint

from .client import LLMError, chat_json
from .context import build_context
from .models import GenAIAnalysis
from .prompts import get_active_prompt, render_messages, render_retry
from .validation import OutputValidationError, parse_json, validate_output


def analyze_complaint(complaint, tone=None, requested_by=None):
    prompt = get_active_prompt()
    tone = tone or settings.GENAI_DEFAULT_TONE
    context = build_context(complaint, tone, settings.GENAI_POLICY_CHUNKS)
    messages = render_messages(prompt, context.values)
    config = {
        "temperature": settings.GENAI_TEMPERATURE if settings.GENAI_THINKING == "disabled" else None,
        "thinking": settings.GENAI_THINKING,
        "max_tokens": settings.GENAI_MAX_TOKENS,
        "response_format": "json_object",
        "tone": tone,
        "max_attempts": settings.GENAI_MAX_ATTEMPTS,
        "policy_chunks": settings.GENAI_POLICY_CHUNKS,
    }

    conversation = list(messages)
    attempts, output, issues, raw, error = [], None, [], "", ""
    prompt_tokens = completion_tokens = cache_hit_tokens = latency_ms = 0

    for number in range(1, settings.GENAI_MAX_ATTEMPTS + 1):
        try:
            result = chat_json(
                conversation, settings.DEEPSEEK_MODEL, settings.GENAI_TEMPERATURE,
                settings.GENAI_MAX_TOKENS, thinking=settings.GENAI_THINKING,
            )
        except LLMError as e:
            attempts.append({"attempt": number, "ok": False, "stage": "api", "errors": [str(e)]})
            error = str(e)
            if not e.retryable:
                break
            time.sleep(settings.GENAI_RETRY_BACKOFF_SECONDS * number)
            continue

        raw = result.content
        prompt_tokens += result.prompt_tokens
        completion_tokens += result.completion_tokens
        cache_hit_tokens += result.cache_hit_tokens
        latency_ms += result.latency_ms
        record = {"attempt": number, "latency_ms": result.latency_ms, "finish_reason": result.finish_reason,
                  "reasoning_tokens": result.reasoning_tokens, "cache_hit_tokens": result.cache_hit_tokens}
        if result.finish_reason == "content_filter":
            # The provider refused the content; asking again will not change that -> manual review.
            error = "Blocked by the provider's content filter."
            attempts.append({**record, "ok": False, "stage": "provider", "errors": [error]})
            break

        try:
            data = parse_json(raw)
            validated, issues = validate_output(data, context.chunks)
        except OutputValidationError as e:
            errors = list(e.errors)
            if result.finish_reason == "length":
                errors.append("The answer was cut off because it was too long; keep text fields shorter.")
            attempts.append({**record, "ok": False, "stage": "validation", "errors": errors})
            error = "; ".join(errors)
            # Controlled retry: show the model its own answer and exactly what was wrong with it.
            conversation = messages + (
                [{"role": "assistant", "content": raw}] if raw.strip() else []
            ) + [{"role": "user", "content": render_retry(prompt, errors)}]
            continue

        attempts.append({**record, "ok": True, "stage": "validation", "errors": []})
        output, error = validated.model_dump(mode="json"), ""
        break

    analysis = GenAIAnalysis.objects.create(
        complaint=complaint,
        prompt_template=prompt,
        provider=settings.GENAI_PROVIDER,
        model=settings.DEEPSEEK_MODEL,
        generation_config=config,
        request_messages=messages,
        retrieved_chunks=[{"chunk_id": cid, **info} for cid, info in context.chunks.items()],
        policy_versions=context.policy_versions,
        status=GenAIAnalysis.Status.SUCCESS if output else GenAIAnalysis.Status.FAILED,
        attempts=attempts,
        raw_response=raw,
        output=output,
        validation_issues=issues if output else [],
        error=error,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cache_hit_tokens=cache_hit_tokens,
        latency_ms=latency_ms,
        requested_by=requested_by,
    )
    if output and complaint.status == Complaint.Status.NEW:
        complaint.status = Complaint.Status.ANALYZED
        complaint.save(update_fields=["status", "updated_at"])
    return analysis
