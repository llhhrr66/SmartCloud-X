from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from urllib.request import Request as UrlRequest, urlopen
import base64
import json

from app.core.config import get_settings


TRANSPARENT_PNG_BASE64 = (
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADElEQVQImWP4//8/AAX+Av5B3ZOxAAAAAElFTkSuQmCC'
)


@dataclass(slots=True)
class PosterTaskContext:
    task_id: str
    campaign_id: str
    campaign_name: str
    theme: str
    slogan: str
    size: str


@dataclass(slots=True)
class PosterResult:
    image_bytes: bytes
    mime_type: str = 'image/png'


class PosterGeneratorProvider(Protocol):
    async def generate(self, task: PosterTaskContext) -> PosterResult: ...
    def capabilities(self) -> dict[str, Any]: ...


class PlaceholderPosterGenerator:
    async def generate(self, task: PosterTaskContext) -> PosterResult:
        return PosterResult(image_bytes=base64.b64decode(TRANSPARENT_PNG_BASE64))

    def capabilities(self) -> dict[str, Any]:
        return {'provider': 'placeholder', 'mode': 'deterministic', 'real_image_generation': False}


class ImageServicePosterGenerator:
    async def generate(self, task: PosterTaskContext) -> PosterResult:
        settings = get_settings()
        if not settings.marketing_image_api_url or not settings.marketing_image_api_key:
            return await PlaceholderPosterGenerator().generate(task)
        req = UrlRequest(
            settings.marketing_image_api_url,
            data=json.dumps({'task_id': task.task_id, 'campaign_id': task.campaign_id, 'campaign_name': task.campaign_name, 'theme': task.theme, 'slogan': task.slogan, 'size': task.size}, ensure_ascii=False).encode('utf-8'),
            headers={'Authorization': f'Bearer {settings.marketing_image_api_key}', 'Content-Type': 'application/json'},
            method='POST',
        )
        with urlopen(req, timeout=20) as resp:
            body = resp.read()
            mime = resp.headers.get('Content-Type', 'image/png')
        return PosterResult(image_bytes=body, mime_type=mime)

    def capabilities(self) -> dict[str, Any]:
        settings = get_settings()
        return {'provider': 'image-service', 'mode': 'http-stub', 'configured': bool(settings.marketing_image_api_url and settings.marketing_image_api_key)}


def get_poster_generator() -> PosterGeneratorProvider:
    settings = get_settings()
    if settings.poster_generator_provider == 'image-service':
        return ImageServicePosterGenerator()
    if settings.poster_generator_provider == 'openai-image':
        from app.services.openai_image_generator import OpenAIImagePosterGenerator
        return OpenAIImagePosterGenerator()
    return PlaceholderPosterGenerator()
