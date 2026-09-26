"""
GenAI provider client. DeepSeek is OpenAI-compatible, so the official openai SDK is used with
DeepSeek's base URL; switching provider is a configuration change (.env), not a code change.

Retries are NOT done here (max_retries=0): the pipeline controls retries itself so every
attempt is logged and the total is capped (SRS Step 47).
"""

import time
from dataclasses import dataclass

import openai
from django.conf import settings

_client = None


class LLMError(Exception):
    def __init__(self, message, retryable):
        super().__init__(message)
        self.retryable = retryable


@dataclass
class LLMResult:
    content: str
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    cache_hit_tokens: int
    latency_ms: int
    finish_reason: str | None


def _get_client():
    global _client
    if _client is None:
        if not settings.DEEPSEEK_API_KEY:
            raise LLMError("DEEPSEEK_API_KEY is not configured.", retryable=False)
        _client = openai.OpenAI(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL,
            timeout=settings.GENAI_TIMEOUT_SECONDS,
            max_retries=0,
        )
    return _client


def _thinking_options(thinking, temperature):
    """
    deepseek-flash "thinks" before answering by default (high effort). Reasoning tokens count
    against max_tokens and add latency, and temperature is ignored while thinking.
    settings.GENAI_THINKING = "disabled" | "low" | "high".
    """
    # One fixed, non-personal user_id for the whole app: DeepSeek isolates its context cache per
    # user_id, so a per-customer id would stop complaints sharing the cached prompt prefix.
    extra = {"user_id": settings.GENAI_USER_ID}
    if thinking == "disabled":
        return {"temperature": temperature, "extra_body": {**extra, "thinking": {"type": "disabled"}}}
    return {"reasoning_effort": thinking, "extra_body": {**extra, "thinking": {"type": "enabled"}}}


def chat_json(messages, model, temperature, max_tokens, thinking="disabled"):
    """One JSON-mode chat completion. Raises LLMError (retryable or not) on API problems."""
    started = time.monotonic()
    try:
        response = _get_client().chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
            max_tokens=max_tokens,
            **_thinking_options(thinking, temperature),
        )
    except openai.AuthenticationError as e:
        raise LLMError(f"Authentication failed: {e}", retryable=False)
    except openai.BadRequestError as e:
        raise LLMError(f"Request rejected by the provider: {e}", retryable=False)
    except (openai.APITimeoutError, openai.APIConnectionError, openai.RateLimitError) as e:
        raise LLMError(f"{type(e).__name__}: {e}", retryable=True)
    except openai.APIStatusError as e:
        if e.status_code == 402:
            raise LLMError("The DeepSeek account has insufficient balance.", retryable=False)
        raise LLMError(f"Provider error {e.status_code}: {e}", retryable=e.status_code >= 500)

    choice = response.choices[0]
    usage = response.usage
    details = getattr(usage, "completion_tokens_details", None)
    return LLMResult(
        content=choice.message.content or "",
        prompt_tokens=usage.prompt_tokens if usage else 0,
        completion_tokens=usage.completion_tokens if usage else 0,
        reasoning_tokens=(getattr(details, "reasoning_tokens", 0) or 0) if details else 0,
        cache_hit_tokens=(getattr(usage, "prompt_cache_hit_tokens", 0) or 0) if usage else 0,
        latency_ms=int((time.monotonic() - started) * 1000),
        finish_reason=choice.finish_reason,
    )
