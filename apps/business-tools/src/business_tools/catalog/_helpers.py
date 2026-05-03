from __future__ import annotations

from typing import Any

from business_tools.interfaces import ToolInvocationRequest


def _query_payload(request: ToolInvocationRequest) -> str:
    return str(
        request.payload.get("user_query")
        or request.payload.get("topic")
        or request.payload.get("theme")
        or request.payload.get("product_summary")
        or request.payload.get("product")
        or request.payload.get("subject")
        or ""
    )


def _with_result(
    summary: str,
    result: dict[str, Any],
    *citations: str,
) -> tuple[str, dict[str, Any], list[str]]:
    return summary, result, list(citations)


def _list_strings(values: list[Any]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value is None:
            continue
        normalized = str(value).strip()
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return deduped


def _normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        normalized = value.strip()
        return [normalized] if normalized else []
    if isinstance(value, list):
        return _list_strings(value)
    return []


def _slugify_token(value: Any, *, fallback: str) -> str:
    normalized = "".join(
        character.lower()
        if character.isalnum()
        else "-"
        for character in str(value or "").strip()
    )
    collapsed = "-".join(part for part in normalized.split("-") if part)
    return collapsed[:48] or fallback


def _mask_value(value: Any, *, keep_prefix: int = 2, keep_suffix: int = 2) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if len(raw) <= keep_prefix + keep_suffix:
        return "*" * len(raw)
    middle_length = max(len(raw) - keep_prefix - keep_suffix, 1)
    return f"{raw[:keep_prefix]}{'*' * middle_length}{raw[-keep_suffix:]}"


def _mask_phone(value: Any) -> str:
    raw = str(value or "").strip()
    if len(raw) < 7:
        return _mask_value(raw, keep_prefix=1, keep_suffix=1)
    return f"{raw[:3]}****{raw[-4:]}"


def _mask_email(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw or "@" not in raw:
        return _mask_value(raw, keep_prefix=1, keep_suffix=1)
    local, domain = raw.split("@", 1)
    masked_local = _mask_value(local, keep_prefix=1, keep_suffix=1) if local else "*"
    return f"{masked_local}@{domain}"


def _dedupe_ordered_strings(values: list[str]) -> list[str]:
    ordered: list[str] = []
    for value in values:
        normalized = str(value).strip()
        if normalized and normalized not in ordered:
            ordered.append(normalized)
    return ordered


def _current_billing_cycle(range_name: str) -> str:
    from datetime import date
    today = date.today()
    this_month = f"{today.year:04d}-{today.month:02d}"
    if today.month == 1:
        last_month = f"{today.year - 1:04d}-12"
    else:
        last_month = f"{today.year:04d}-{today.month - 1:02d}"
    if today.month <= 2:
        m3 = f"{today.year - 1:04d}-{today.month + 10:02d}"
    else:
        m3 = f"{today.year:04d}-{today.month - 2:02d}"
    last_3_months = f"{m3}~{this_month}"
    mapping = {
        "this_month": this_month,
        "last_month": last_month,
        "last_3_months": last_3_months,
        "custom": "custom-range",
    }
    return mapping.get(range_name, this_month)
