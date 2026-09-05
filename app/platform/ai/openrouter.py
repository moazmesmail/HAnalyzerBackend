import asyncio
import base64
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.platform.config import Settings
from app.platform.errors import ApiError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProviderUsage:
    provider_request_id: str | None
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    cost: float | None
    duration_ms: int


@dataclass(frozen=True)
class StructuredResponse:
    content: dict
    usage: ProviderUsage


def analyze_images(
    settings: Settings,
    prompt: str,
    image_paths: list[Path],
    output_schema: dict,
    image_labels: list[str] | None = None,
) -> StructuredResponse:
    if not settings.openrouter_api_key:
        raise ApiError(503, "AI_NOT_CONFIGURED", "OpenRouter is not configured.")

    if image_labels is not None and len(image_labels) != len(image_paths):
        raise ValueError("Every analysis image must have one label.")

    content: list[dict] = [{"type": "text", "text": prompt}]
    for index, path in enumerate(image_paths):
        if image_labels is not None:
            content.append({"type": "text", "text": image_labels[index]})
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
            }
        )

    system_prompt = (
        "You analyze silent competition video frames. Return JSON only, with no markdown or "
        "explanation, matching this JSON schema exactly: "
        f"{json.dumps(output_schema, separators=(',', ':'))}"
    )
    payload = {
        "model": settings.openrouter_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
        "temperature": 0.0,
        "max_tokens": 2500,
        "usage": {"include": True},
    }
    started = time.monotonic()
    body: dict = {}
    parsed: dict | None = None
    last_error: Exception | None = None
    for attempt in range(1, settings.openrouter_max_retries + 2):
        body = {}
        raw_content = None
        logger.info(
            "openrouter_request_started model=%s image_count=%d attempt=%d timeout_seconds=%d",
            settings.openrouter_model,
            len(image_paths),
            attempt,
            settings.openrouter_timeout_seconds,
        )
        try:
            body = asyncio.run(_post_json(settings, payload))
            if body.get("error"):
                provider_error = body["error"]
                message = (
                    provider_error.get("message", "Unknown provider error")
                    if isinstance(provider_error, dict)
                    else str(provider_error)
                )
                raise ApiError(502, "AI_PROVIDER_ERROR", f"OpenRouter error: {message[:300]}")
            raw_content = body["choices"][0]["message"]["content"]
            parsed = _parse_json_object(raw_content)
            break
        except (TimeoutError, httpx.TimeoutException) as exc:
            last_error = exc
            logger.warning(
                "openrouter_request_timeout model=%s attempt=%d timeout_seconds=%d",
                settings.openrouter_model,
                attempt,
                settings.openrouter_timeout_seconds,
            )
            break
        except httpx.HTTPStatusError as exc:
            last_error = exc
            logger.warning(
                "openrouter_request_rejected model=%s attempt=%d status_code=%d response=%s",
                settings.openrouter_model,
                attempt,
                exc.response.status_code,
                exc.response.text[:500],
            )
            if exc.response.status_code != 429:
                break
            if attempt <= settings.openrouter_max_retries:
                retry_after = exc.response.headers.get("Retry-After")
                try:
                    requested_wait = float(retry_after) if retry_after is not None else 2 ** (attempt - 1)
                except ValueError:
                    requested_wait = 2 ** (attempt - 1)
                wait_seconds = min(requested_wait, settings.openrouter_retry_max_wait_seconds)
                logger.info(
                    "openrouter_rate_limit_retry attempt=%d wait_seconds=%.1f",
                    attempt,
                    wait_seconds,
                )
                time.sleep(wait_seconds)
        except (httpx.RequestError, ApiError, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            last_error = exc
            logger.warning(
                "openrouter_invalid_response model=%s attempt=%d error_type=%s response_keys=%s",
                settings.openrouter_model,
                attempt,
                type(exc).__name__,
                sorted(body.keys()) if isinstance(body, dict) else [],
            )
            if raw_content is not None:
                logger.warning("openrouter_unparsed_content content=%r", str(raw_content)[:1000])
            break

    if parsed is None:
        if isinstance(last_error, ApiError):
            raise last_error
        if isinstance(last_error, httpx.HTTPStatusError):
            if last_error.response.status_code in (401, 403):
                raise ApiError(
                    502,
                    "AI_AUTHENTICATION_FAILED",
                    "OpenRouter rejected the configured API key.",
                ) from last_error
            raise ApiError(
                502,
                "AI_PROVIDER_ERROR",
                f"OpenRouter rejected the analysis request ({last_error.response.status_code}).",
            ) from last_error
        if isinstance(last_error, (TimeoutError, httpx.TimeoutException, httpx.RequestError)):
            raise ApiError(
                502,
                "AI_PROVIDER_UNAVAILABLE",
                "OpenRouter did not return a result within the request deadline.",
            ) from last_error
        raise ApiError(502, "AI_RESPONSE_INVALID", "OpenRouter returned an invalid structured response.") from last_error

    duration_ms = round((time.monotonic() - started) * 1000)
    raw_usage = body.get("usage") or {}
    logger.info(
        "openrouter_request_completed model=%s provider_request_id=%s duration_ms=%d total_tokens=%s",
        body.get("model") or settings.openrouter_model,
        body.get("id"),
        duration_ms,
        raw_usage.get("total_tokens"),
    )
    return StructuredResponse(
        content=parsed,
        usage=ProviderUsage(
            provider_request_id=body.get("id"),
            model=body.get("model") or settings.openrouter_model,
            prompt_tokens=raw_usage.get("prompt_tokens"),
            completion_tokens=raw_usage.get("completion_tokens"),
            total_tokens=raw_usage.get("total_tokens"),
            cost=raw_usage.get("cost"),
            duration_ms=duration_ms,
        ),
    )


async def _post_json(settings: Settings, payload: dict) -> dict:
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": settings.app_origin,
        "X-Title": settings.app_name,
    }
    timeout_seconds = settings.openrouter_timeout_seconds
    timeout = httpx.Timeout(timeout_seconds, connect=min(15, timeout_seconds))
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with asyncio.timeout(timeout_seconds):
            response = await client.post(
                settings.openrouter_base_url,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            return response.json()


def _parse_json_object(content: object) -> dict:
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        raise TypeError("Structured response is not an object.")

    candidate = content.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        candidate = "\n".join(
            lines[1:-1] if lines[-1].strip().startswith("```") else lines[1:]
        ).strip()
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(candidate[start : end + 1])
    if not isinstance(parsed, dict):
        raise TypeError("Structured response is not an object.")
    return parsed
