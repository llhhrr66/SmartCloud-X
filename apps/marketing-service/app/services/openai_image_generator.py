"""OpenAI-compatible image generation poster provider.

Calls the /v1/images/generations endpoint (OpenAI Images API spec) to produce
real poster images via models like gpt-image-2.

Uses only stdlib (urllib, json, base64, asyncio) — no external HTTP client
dependency required.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any
from urllib.error import URLError
from urllib.request import Request as UrlRequest, urlopen

from app.core.config import get_settings
from app.services.poster_generator import (
    PosterGeneratorProvider,
    PosterResult,
    PosterTaskContext,
)

logger = logging.getLogger(__name__)

# OpenAI /v1/images/generations supported sizes
_SUPPORTED_SIZES = {"1024x1024", "1024x1792", "1792x1024"}

# Map arbitrary user-provided size strings to the nearest supported size
_SIZE_MAP: dict[str, str] = {
    "portrait": "1024x1792",
    "landscape": "1792x1024",
    "square": "1024x1024",
}


def _resolve_size(raw_size: str) -> str:
    """Map user-provided size string to an OpenAI-supported value.

    Rules:
    - If the raw_size exactly matches a supported size, use it.
    - If it contains keywords like "portrait" / "vertical" → 1024x1792
    - If it contains keywords like "landscape" / "horizontal" → 1792x1024
    - Parse WxH: if height > width → portrait; width > height → landscape
    - Default → 1024x1024
    """
    raw = raw_size.strip().lower()

    # Direct match
    if raw in _SUPPORTED_SIZES:
        return raw

    # Keyword match
    for keyword, mapped in _SIZE_MAP.items():
        if keyword in raw:
            return mapped

    # Try parsing WxH pattern
    parts = raw.split("x")
    if len(parts) == 2:
        try:
            w, h = int(parts[0]), int(parts[1])
            if h > w:
                return "1024x1792"
            if w > h:
                return "1792x1024"
            return "1024x1024"
        except (ValueError, IndexError):
            pass

    return "1024x1024"


def _build_prompt(task: PosterTaskContext) -> str:
    """Compose a generation prompt from the poster task fields."""
    parts: list[str] = []
    if task.theme:
        parts.append(f"{task.theme}主题")
    if task.slogan:
        parts.append(task.slogan)
    if task.campaign_name:
        parts.append(f"{task.campaign_name}营销活动海报")
    parts.append("高质量商业设计，专业排版")
    return "，".join(parts)


class OpenAIImagePosterGenerator:
    """Poster generator that calls an OpenAI-compatible /v1/images/generations endpoint."""

    async def generate(self, task: PosterTaskContext) -> PosterResult:
        settings = get_settings()
        api_url = settings.marketing_image_api_url
        api_key = settings.marketing_image_api_key

        if not api_url or not api_key:
            logger.warning("openai-image: api_url or api_key not configured, falling back to placeholder")
            from app.services.poster_generator import PlaceholderPosterGenerator
            return await PlaceholderPosterGenerator().generate(task)

        model = settings.marketing_image_model or "gpt-image-2"
        size = _resolve_size(task.size)
        prompt = _build_prompt(task)

        # Build the endpoint URL
        base = api_url.rstrip("/")
        endpoint = f"{base}/v1/images/generations"

        payload = json.dumps({
            "model": model,
            "prompt": prompt,
            "n": 1,
            "size": size,
            "response_format": "b64_json",
        }, ensure_ascii=False).encode("utf-8")

        req = UrlRequest(
            endpoint,
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        # Run the blocking urlopen in an executor so we don't stall the event loop
        loop = asyncio.get_event_loop()
        try:
            body_bytes = await loop.run_in_executor(
                None, self._do_request, req, 120,
            )
        except (URLError, OSError) as exc:
            raise RuntimeError(f"openai-image request failed: {exc}") from exc

        # Parse the JSON response
        try:
            resp_data = json.loads(body_bytes)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"openai-image: invalid JSON response: {exc}") from exc

        # Extract image from response — prefer b64_json, fall back to url
        images = resp_data.get("data", [])
        if not images:
            raise RuntimeError(f"openai-image: no image data in response, keys={list(resp_data.keys())}")

        first = images[0]
        mime_type = "image/png"  # default

        if "b64_json" in first and first["b64_json"]:
            image_bytes = base64.b64decode(first["b64_json"])
        elif "url" in first and first["url"]:
            image_url = first["url"]
            # Download the image from the URL
            try:
                img_req = UrlRequest(image_url)
                img_req.add_header("Authorization", f"Bearer {api_key}")
                with urlopen(img_req, timeout=60) as img_resp:
                    image_bytes = img_resp.read()
                    ct = img_resp.headers.get("Content-Type", "")
                    if ct and "/" in ct:
                        mime_type = ct.split(";")[0].strip()
            except (URLError, OSError) as exc:
                raise RuntimeError(f"openai-image: failed to download image from url: {exc}") from exc
        else:
            raise RuntimeError(f"openai-image: image entry has neither b64_json nor url, keys={list(first.keys())}")

        if not image_bytes:
            raise RuntimeError("openai-image: decoded image is empty")

        logger.info(
            "openai-image: generated poster task=%s size=%s model=%s image_bytes=%d",
            task.task_id, size, model, len(image_bytes),
        )
        return PosterResult(image_bytes=image_bytes, mime_type=mime_type)

    @staticmethod
    def _do_request(req: UrlRequest, timeout: int) -> bytes:
        """Synchronous urlopen — called inside run_in_executor."""
        with urlopen(req, timeout=timeout) as resp:
            return resp.read()

    def capabilities(self) -> dict[str, Any]:
        settings = get_settings()
        return {
            "provider": "openai-image",
            "mode": "api",
            "model": settings.marketing_image_model or "gpt-image-2",
            "configured": bool(settings.marketing_image_api_url and settings.marketing_image_api_key),
            "real_image_generation": True,
        }
