import asyncio
import base64
import json
import logging
import time
from dataclasses import dataclass
from io import BytesIO
from math import ceil
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageOps

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
    max_output_tokens: int | None = None,
    provider_sort: str | None = None,
) -> StructuredResponse:
    if not settings.openrouter_api_key:
        raise ApiError(503, "AI_NOT_CONFIGURED", "OpenRouter is not configured.")

    if image_labels is not None and len(image_labels) != len(image_paths):
        raise ValueError("Every analysis image must have one label.")

    content, request_image_count, contact_sheet_count = _build_image_content(
        prompt,
        image_paths,
        image_labels,
        settings.analysis_contact_sheet_frames,
        settings.analysis_contact_sheet_cell_width,
        settings.analysis_contact_sheet_cell_height,
        settings.analysis_contact_sheet_jpeg_quality,
    )

    system_prompt = (
        "You analyze silent competition video frames. Return JSON only, with no markdown or "
        "explanation, matching this JSON schema exactly: "
        f"{json.dumps(output_schema, separators=(',', ':'))}"
    )
    effective_max_output_tokens = max_output_tokens or settings.openrouter_max_output_tokens
    effective_provider_sort = provider_sort or settings.openrouter_provider_sort
    payload = {
        "model": settings.openrouter_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
        "temperature": 0.0,
        "max_tokens": effective_max_output_tokens,
        "provider": {"sort": effective_provider_sort},
        "usage": {"include": True},
    }
    started = time.monotonic()
    body: dict = {}
    parsed: dict | None = None
    last_error: Exception | None = None
    logger.info(
        "openrouter_request_initiated model=%s source_frame_count=%d request_image_count=%d contact_sheet_count=%d cell_size=%dx%d jpeg_quality=%d max_output_tokens=%d provider_sort=%s timeout_seconds=%d",
        settings.openrouter_model,
        len(image_paths),
        request_image_count,
        contact_sheet_count,
        settings.analysis_contact_sheet_cell_width,
        settings.analysis_contact_sheet_cell_height,
        settings.analysis_contact_sheet_jpeg_quality,
        effective_max_output_tokens,
        effective_provider_sort,
        settings.openrouter_timeout_seconds,
    )
    for attempt in range(1, settings.openrouter_max_retries + 2):
        body = {}
        raw_content = None
        logger.info(
            "openrouter_request_started model=%s source_frame_count=%d request_image_count=%d attempt=%d timeout_seconds=%d",
            settings.openrouter_model,
            len(image_paths),
            request_image_count,
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
                metadata = provider_error.get("metadata") if isinstance(provider_error, dict) else None
                logger.warning(
                    "openrouter_provider_error response_id=%s code=%s provider=%s metadata_keys=%s duration_ms=%d message=%s",
                    body.get("id"),
                    provider_error.get("code") if isinstance(provider_error, dict) else None,
                    metadata.get("provider_name") if isinstance(metadata, dict) else None,
                    sorted(metadata.keys()) if isinstance(metadata, dict) else [],
                    round((time.monotonic() - started) * 1000),
                    message.replace("\n", " ")[:500],
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
            choice = body.get("choices", [{}])[0] if isinstance(body, dict) else {}
            logger.warning(
                "openrouter_invalid_response model=%s attempt=%d error_type=%s finish_reason=%s content_chars=%s response_keys=%s",
                settings.openrouter_model,
                attempt,
                type(exc).__name__,
                choice.get("finish_reason") if isinstance(choice, dict) else None,
                len(raw_content) if isinstance(raw_content, str) else None,
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
            if last_error.response.status_code in (400, 413):
                raise ApiError(
                    502,
                    "AI_REQUEST_INVALID",
                    "The analysis batch exceeded the provider request limits.",
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
        parsed = _load_model_json(candidate)
    except json.JSONDecodeError as original_error:
        start = candidate.find("{")
        end = candidate.rfind("}")
        try:
            if start < 0 or end <= start:
                raise original_error
            parsed = _load_model_json(candidate[start : end + 1])
        except json.JSONDecodeError:
            parsed = _recover_truncated_analysis_json(candidate)
            if parsed is None:
                raise original_error
    if not isinstance(parsed, dict):
        raise TypeError("Structured response is not an object.")
    return parsed


def _load_model_json(candidate: str) -> object:
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as original_error:
        # Qwen occasionally escapes apostrophes even though JSON does not define \' as
        # an escape sequence. Repair only that specific invalid sequence.
        repaired = candidate.replace("\\'", "'")
        if repaired == candidate:
            raise
        try:
            parsed = json.loads(repaired)
        except json.JSONDecodeError:
            raise original_error
        logger.warning("openrouter_response_repaired repair=invalid_apostrophe_escape")
        return parsed


def _recover_truncated_analysis_json(candidate: str) -> dict | None:
    """Keep complete extraction records when generation ends midway through JSON."""
    candidate = candidate.replace("\\'", "'")
    summary = _decode_json_field(candidate, "summary")
    observations = _decode_json_field(candidate, "observations")
    domain_records = _decode_complete_array_items(candidate, "domain_records")
    if not isinstance(summary, str) or not isinstance(observations, list):
        return None
    if not domain_records and '"domain_records"' not in candidate:
        return None
    logger.warning(
        "openrouter_response_repaired repair=truncated_analysis_json observations=%d domain_records=%d",
        len(observations),
        len(domain_records),
    )
    return {
        "summary": summary,
        "observations": observations,
        "domain_records": domain_records,
    }


def _decode_json_field(candidate: str, field: str) -> object | None:
    marker = f'"{field}"'
    start = candidate.find(marker)
    if start < 0:
        return None
    colon = candidate.find(":", start + len(marker))
    if colon < 0:
        return None
    position = colon + 1
    while position < len(candidate) and candidate[position] in " \r\n\t":
        position += 1
    try:
        value, _ = json.JSONDecoder().raw_decode(candidate, position)
    except json.JSONDecodeError:
        return None
    return value


def _decode_complete_array_items(candidate: str, field: str) -> list[dict]:
    marker = f'"{field}"'
    start = candidate.find(marker)
    if start < 0:
        return []
    array_start = candidate.find("[", start + len(marker))
    if array_start < 0:
        return []
    decoder = json.JSONDecoder()
    position = array_start + 1
    items: list[dict] = []
    while position < len(candidate):
        while position < len(candidate) and candidate[position] in " \r\n\t,":
            position += 1
        if position >= len(candidate) or candidate[position] == "]":
            break
        try:
            value, position = decoder.raw_decode(candidate, position)
        except json.JSONDecodeError:
            break
        if isinstance(value, dict):
            items.append(value)
    return items


def _build_image_content(
    prompt: str,
    image_paths: list[Path],
    image_labels: list[str] | None,
    frames_per_sheet: int,
    cell_width: int = 240,
    frame_height: int = 135,
    jpeg_quality: int = 70,
) -> tuple[list[dict], int, int]:
    content: list[dict] = [{"type": "text", "text": prompt}]
    labels = image_labels or [f"Frame {index + 1}" for index in range(len(image_paths))]
    if frames_per_sheet <= 1 or len(image_paths) <= 1:
        for label, path in zip(labels, image_paths, strict=True):
            content.append({"type": "text", "text": label})
            content.append(_image_content(path.read_bytes()))
        return content, len(image_paths), 0

    sheet_count = 0
    for start in range(0, len(image_paths), frames_per_sheet):
        paths = image_paths[start : start + frames_per_sheet]
        sheet_labels = labels[start : start + frames_per_sheet]
        cell_names = [f"F{index:03d}" for index in range(start + 1, start + len(paths) + 1)]
        mapping = "\n".join(
            f"{cell_name}: {label}"
            for cell_name, label in zip(cell_names, sheet_labels, strict=True)
        )
        content.append(
            {
                "type": "text",
                "text": (
                    f"Contact sheet {sheet_count + 1}; cells are in reading order.\n{mapping}"
                ),
            }
        )
        content.append(
            _image_content(
                _contact_sheet_jpeg(
                    paths,
                    cell_names,
                    cell_width,
                    frame_height,
                    jpeg_quality,
                )
            )
        )
        sheet_count += 1
    return content, sheet_count, sheet_count


def _image_content(jpeg_bytes: bytes) -> dict:
    encoded = base64.b64encode(jpeg_bytes).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
    }


def _contact_sheet_jpeg(
    paths: list[Path],
    cell_names: list[str],
    cell_width: int = 240,
    frame_height: int = 135,
    jpeg_quality: int = 70,
) -> bytes:
    columns = 5
    label_height = 20
    rows = ceil(len(paths) / columns)
    sheet = Image.new("RGB", (columns * cell_width, rows * (frame_height + label_height)), "black")
    draw = ImageDraw.Draw(sheet)
    for index, (path, cell_name) in enumerate(zip(paths, cell_names, strict=True)):
        column = index % columns
        row = index // columns
        left = column * cell_width
        top = row * (frame_height + label_height)
        with Image.open(path) as source:
            frame = ImageOps.contain(source.convert("RGB"), (cell_width, frame_height))
        x = left + (cell_width - frame.width) // 2
        y = top + (frame_height - frame.height) // 2
        sheet.paste(frame, (x, y))
        draw.rectangle(
            (left, top + frame_height, left + cell_width, top + frame_height + label_height),
            fill="black",
        )
        draw.text((left + 5, top + frame_height + 3), cell_name, fill="white")
    output = BytesIO()
    sheet.save(output, format="JPEG", quality=jpeg_quality, optimize=True)
    return output.getvalue()
