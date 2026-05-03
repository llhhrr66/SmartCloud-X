from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from urllib.parse import urlparse

from app.models.common import ApiEnvelope, ErrorInfo
from app.models.llm_provider import (
    LlmProviderCreate,
    LlmProviderModelsResult,
    LlmProviderRecord,
    LlmProviderTestRequest,
    LlmProviderTestResult,
    LlmProviderUpdate,
)
from app.services import llm_provider_store

router = APIRouter(prefix="/internal/v1/llm-providers", tags=["llm-providers"])


def _require_gateway(request: Request) -> None:
    caller = request.headers.get("X-Caller-Service", "").strip()
    if caller != "gateway-service":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ErrorInfo(code="FORBIDDEN", message="Caller service is not allowed.").model_dump(),
        )


def _mask_api_key(key: str) -> str:
    if len(key) <= 8:
        return "*" * len(key)
    return key[:4] + "*" * (len(key) - 8) + key[-4:]


def _row_to_record(row: dict[str, Any]) -> LlmProviderRecord:
    return LlmProviderRecord(
        provider_id=str(row["provider_id"]),
        name=str(row["name"]),
        api_key=_mask_api_key(str(row["api_key"])),
        api_url=str(row["api_url"]),
        model_name=str(row["model_name"]),
        provider_type=str(row.get("provider_type", "openai-compatible")),
        is_active=bool(row.get("is_active", 0)),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


@router.get("", response_model=ApiEnvelope[list[LlmProviderRecord]])
def list_providers(request: Request):
    _require_gateway(request)
    rows = llm_provider_store.list_providers()
    records = [_row_to_record(r) for r in rows]
    return ApiEnvelope(data=records)


@router.post("", response_model=ApiEnvelope[LlmProviderRecord], status_code=201)
def create_provider(request: Request, body: LlmProviderCreate):
    _require_gateway(request)
    row = llm_provider_store.create_provider(body.model_dump())
    from app.api.routes.orchestration import _runtime
    _runtime.invalidate_llm_client_cache()
    return ApiEnvelope(data=_row_to_record(row))


@router.get("/{provider_id}", response_model=ApiEnvelope[LlmProviderRecord])
def get_provider(request: Request, provider_id: str):
    _require_gateway(request)
    row = llm_provider_store.get_provider(provider_id)
    if not row:
        raise HTTPException(status_code=404, detail="Provider not found")
    return ApiEnvelope(data=_row_to_record(row))


@router.patch("/{provider_id}", response_model=ApiEnvelope[LlmProviderRecord])
def update_provider(request: Request, provider_id: str, body: LlmProviderUpdate):
    _require_gateway(request)
    row = llm_provider_store.update_provider(provider_id, body.model_dump(exclude_none=True))
    if not row:
        raise HTTPException(status_code=404, detail="Provider not found")
    from app.api.routes.orchestration import _runtime
    _runtime.invalidate_llm_client_cache()
    return ApiEnvelope(data=_row_to_record(row))


@router.delete("/{provider_id}", response_model=ApiEnvelope[bool])
def delete_provider(request: Request, provider_id: str):
    _require_gateway(request)
    ok = llm_provider_store.delete_provider(provider_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Provider not found")
    from app.api.routes.orchestration import _runtime
    _runtime.invalidate_llm_client_cache()
    return ApiEnvelope(data=True)


@router.post("/test", response_model=ApiEnvelope[LlmProviderTestResult])
def test_connection(request: Request, body: LlmProviderTestRequest):
    _require_gateway(request)
    try:
        from openai import OpenAI

        base_url = body.api_url.strip().rstrip("/")
        parsed = urlparse(base_url)
        if parsed.path in {"", "/"}:
            base_url = f"{base_url}/v1"

        client = OpenAI(api_key=body.api_key, base_url=base_url, timeout=10.0, max_retries=0)
        model = body.model_name or "gpt-3.5-turbo"
        started = time.perf_counter()
        completion = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Hi, please reply with your model name."}],
            max_tokens=32,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        content = completion.choices[0].message.content if completion.choices else None
        return ApiEnvelope(data=LlmProviderTestResult(
            success=True,
            message="Connection successful",
            model_id=getattr(completion, "model", None),
            latency_ms=latency_ms,
        ))
    except Exception as exc:
        return ApiEnvelope(data=LlmProviderTestResult(
            success=False,
            message=str(exc)[:200],
        ))


@router.post("/models", response_model=ApiEnvelope[LlmProviderModelsResult])
def fetch_models(request: Request, body: LlmProviderTestRequest):
    _require_gateway(request)
    try:
        from openai import OpenAI

        base_url = body.api_url.strip().rstrip("/")
        parsed = urlparse(base_url)
        if parsed.path in {"", "/"}:
            base_url = f"{base_url}/v1"

        client = OpenAI(api_key=body.api_key, base_url=base_url, timeout=10.0, max_retries=0)
        models_page = client.models.list()
        model_ids = [m.id for m in models_page.data] if models_page.data else []
        return ApiEnvelope(data=LlmProviderModelsResult(
            success=True,
            message=f"Found {len(model_ids)} models",
            models=sorted(model_ids),
        ))
    except Exception as exc:
        return ApiEnvelope(data=LlmProviderModelsResult(
            success=False,
            message=str(exc)[:200],
            models=[],
        ))
