from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from urllib.request import Request as UrlRequest, urlopen
import json

from app.core.config import get_settings


@dataclass(slots=True)
class CampaignContext:
    campaign_id: str
    campaign_name: str
    topic: str
    audience: str
    tone: str
    keywords: list[str]
    highlights: list[str]
    landing_page_url: str | None


@dataclass(slots=True)
class GeneratedCopy:
    headline: str
    summary: str
    body: str
    call_to_action: str


class CopyGeneratorProvider(Protocol):
    async def generate(self, campaign: CampaignContext, *, tone: str, keywords: list[str]) -> GeneratedCopy: ...
    def capabilities(self) -> dict[str, Any]: ...


class TemplateCopyGenerator:
    async def generate(self, campaign: CampaignContext, *, tone: str, keywords: list[str]) -> GeneratedCopy:
        selected = keywords or campaign.highlights or []
        headline = f'{campaign.topic}'
        summary = f"面向{campaign.audience}" + (f"，突出{'、'.join(selected[:2])}等核心卖点。" if selected else "。")
        if not selected:
            body = f'{campaign.campaign_name}现已开放，围绕"{campaign.topic}"提供更贴近业务落地的推广素材。'
        else:
            body = "\n\n".join([
                f'{campaign.campaign_name}现已开放，围绕"{campaign.topic}"提供更贴近业务落地的推广素材。',
                f"重点强调 {'、'.join(selected)}，帮助{campaign.audience}快速理解活动价值与适用场景。",
            ])
        return GeneratedCopy(
            headline=headline,
            summary=summary,
            body=body,
            call_to_action='了解详情',
        )

    def capabilities(self) -> dict[str, Any]:
        return {'provider': 'template', 'mode': 'deterministic', 'llm_enabled': False}


class LLMCopyGenerator:
    async def generate(self, campaign: CampaignContext, *, tone: str, keywords: list[str]) -> GeneratedCopy:
        settings = get_settings()
        if not settings.marketing_llm_api_url or not settings.marketing_llm_api_key or not settings.marketing_llm_model:
            return await TemplateCopyGenerator().generate(campaign, tone=tone, keywords=keywords)
        prompt = {
            'model': settings.marketing_llm_model,
            'messages': [
                {'role': 'system', 'content': 'You generate Chinese marketing copy JSON.'},
                {'role': 'user', 'content': json.dumps({'campaign_name': campaign.campaign_name, 'topic': campaign.topic, 'audience': campaign.audience, 'tone': tone, 'keywords': keywords, 'highlights': campaign.highlights}, ensure_ascii=False)},
            ],
        }
        req = UrlRequest(settings.marketing_llm_api_url, data=json.dumps(prompt).encode('utf-8'), headers={'Authorization': f'Bearer {settings.marketing_llm_api_key}', 'Content-Type': 'application/json'}, method='POST')
        with urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
        content = payload.get('choices', [{}])[0].get('message', {}).get('content')
        if isinstance(content, str):
            parsed = json.loads(content)
            return GeneratedCopy(**parsed)
        return await TemplateCopyGenerator().generate(campaign, tone=tone, keywords=keywords)

    def capabilities(self) -> dict[str, Any]:
        settings = get_settings()
        return {'provider': 'llm', 'mode': 'openai-compatible-stub', 'configured': bool(settings.marketing_llm_api_url and settings.marketing_llm_api_key and settings.marketing_llm_model)}


def get_copy_generator() -> CopyGeneratorProvider:
    settings = get_settings()
    if settings.copy_generator_provider == 'llm':
        return LLMCopyGenerator()
    return TemplateCopyGenerator()
