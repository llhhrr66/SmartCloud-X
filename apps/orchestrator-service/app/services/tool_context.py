from __future__ import annotations

from typing import Any

from app.core.business_tools_sdk import ToolDefinition, is_missing_tool_value
from app.models.orchestration import SessionContext


def read_session_context_key(
    session_context: SessionContext,
    dotted_key: str,
) -> Any:
    current: Any = session_context.model_dump()
    for part in dotted_key.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def available_session_context_keys(session_context: SessionContext) -> set[str]:
    keys: set[str] = set()

    def _collect(prefix: str, value: Any) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                _collect(f"{prefix}.{key}" if prefix else key, nested)
            return
        if not prefix or is_missing_tool_value(value):
            return
        keys.add(prefix)

    _collect("", session_context.model_dump())
    return keys


def hydrate_payload_from_session_context(
    payload: dict[str, object],
    definition: ToolDefinition | None,
    session_context: SessionContext,
) -> dict[str, object]:
    hydrated = dict(payload)
    if definition is None:
        return hydrated

    for field, bindings in definition.session_context_bindings.items():
        if not is_missing_tool_value(hydrated.get(field)):
            continue
        for dotted_key in bindings:
            value = read_session_context_key(session_context, dotted_key)
            if is_missing_tool_value(value):
                continue
            hydrated[field] = _coerce_bound_value(definition, field, value)
            break

    return hydrated


def write_session_context_key(
    session_context: SessionContext,
    dotted_key: str,
    value: object,
) -> bool:
    parts = [part.strip() for part in dotted_key.split(".") if part.strip()]
    if not parts:
        return False

    root = parts[0]
    if root not in SessionContext.model_fields:
        return False

    if len(parts) == 1:
        setattr(session_context, root, value)
        return True

    current = getattr(session_context, root)
    if not isinstance(current, dict):
        return False

    target = current
    for part in parts[1:-1]:
        nested = target.get(part)
        if not isinstance(nested, dict):
            nested = {}
            target[part] = nested
        target = nested
    target[parts[-1]] = value
    setattr(session_context, root, current)
    return True


def apply_tool_input_bindings(
    session_context: SessionContext,
    definition: ToolDefinition | None,
    field: str,
    value: object,
) -> bool:
    if definition is None:
        return False

    applied = False
    candidate_fields = [field]
    if "." in field:
        leaf_field = field.rsplit(".", 1)[-1].strip()
        if leaf_field and leaf_field not in candidate_fields:
            candidate_fields.append(leaf_field)

    for candidate_field in candidate_fields:
        coerced = _coerce_bound_value(definition, candidate_field, value)
        for dotted_key in definition.session_context_bindings.get(candidate_field, []):
            applied = write_session_context_key(session_context, dotted_key, coerced) or applied
    return applied


def session_context_input_keys(definition: ToolDefinition | None) -> list[str]:
    if definition is None:
        return []
    deduped: list[str] = []
    for bindings in definition.session_context_bindings.values():
        for dotted_key in bindings:
            if dotted_key not in deduped:
                deduped.append(dotted_key)
    return deduped


def _coerce_bound_value(
    definition: ToolDefinition,
    field: str,
    value: object,
) -> object:
    hint = str(definition.input_schema_hint.get(field, ""))
    if "[]" in hint and isinstance(value, str):
        normalized = value.strip()
        return [normalized] if normalized else []
    return value
