from __future__ import annotations

from typing import Any

from business_tools.interfaces import (
    ToolAuthRequirements,
    ToolDefinition,
    ToolMode,
    ToolOperation,
)

from ._helpers import _dedupe_ordered_strings
from ._static_tool import ResultBuilder, StaticBusinessTool


def _schema_property_from_hint(hint: Any) -> dict[str, Any]:
    if isinstance(hint, dict):
        return dict(hint)

    normalized = str(hint or "string").strip()
    optional = normalized.endswith("?")
    if optional:
        normalized = normalized[:-1]

    if normalized.endswith("[]"):
        items_schema = _schema_property_from_hint(normalized[:-2] or "string")
        items_schema.pop("nullable", None)
        schema: dict[str, Any] = {"type": "array", "items": items_schema}
    elif "|" in normalized:
        schema = {
            "type": "string",
            "enum": [part for part in normalized.split("|") if part],
        }
    else:
        schema = {
            "string": {"type": "string"},
            "integer": {"type": "integer"},
            "number": {"type": "number"},
            "boolean": {"type": "boolean"},
            "object": {"type": "object"},
        }.get(normalized, {"type": "string"})

    if optional:
        schema["nullable"] = True
    return schema


def _schema_from_hint(
    properties_hint: dict[str, Any],
    *,
    required_fields: list[str] | None = None,
    field_hints: dict[str, str] | None = None,
) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for field_name, hint in properties_hint.items():
        property_schema = _schema_property_from_hint(hint)
        if field_hints and field_name in field_hints:
            property_schema.setdefault("description", field_hints[field_name])
        properties[field_name] = property_schema

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required_fields:
        schema["required"] = required_fields
    return schema


def _tool(
    *,
    name: str,
    capability: str,
    description: str,
    tags: list[str],
    input_schema_hint: dict[str, Any],
    input_field_hints: dict[str, str] | None = None,
    output_schema_hint: dict[str, Any],
    session_context_bindings: dict[str, list[str]] | None = None,
    session_context_output_keys: list[str] | None = None,
    prerequisite_tool_names: list[str] | None = None,
    mode: ToolMode = "query",
    auth_requirements: ToolAuthRequirements | None = None,
    operation_required_fields: dict[ToolOperation, list[str]] | None = None,
    timeout_ms: int = 5000,
    idempotent: bool = True,
    idempotency_window_seconds: int | None = None,
    high_risk: bool = False,
    cache_ttl_seconds: int | None = None,
    preview_builder: ResultBuilder,
    execute_builder: ResultBuilder | None = None,
) -> StaticBusinessTool:
    ordered_required_fields = _dedupe_ordered_strings(
        [
            field
            for fields in (operation_required_fields or {}).values()
            for field in fields
        ]
    )
    effective_field_hints = input_field_hints or {}
    return StaticBusinessTool(
        ToolDefinition(
            name=name,
            capability=capability,
            description=description,
            tags=tags,
            input_schema=_schema_from_hint(
                input_schema_hint,
                required_fields=ordered_required_fields,
                field_hints=effective_field_hints,
            ),
            input_schema_hint=input_schema_hint,
            input_field_hints=effective_field_hints,
            output_schema=_schema_from_hint(output_schema_hint),
            output_schema_hint=output_schema_hint,
            session_context_bindings=session_context_bindings or {},
            session_context_output_keys=session_context_output_keys or [],
            prerequisite_tool_names=prerequisite_tool_names or [],
            mode=mode,
            auth_requirements=auth_requirements or ToolAuthRequirements(),
            operation_required_fields=operation_required_fields or {},
            timeout_ms=timeout_ms,
            idempotent=idempotent,
            idempotency_window_seconds=idempotency_window_seconds,
            high_risk=high_risk,
            cache_ttl_seconds=cache_ttl_seconds,
        ),
        preview_builder=preview_builder,
        execute_builder=execute_builder,
    )
