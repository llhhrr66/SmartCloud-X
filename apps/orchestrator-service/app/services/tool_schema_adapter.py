from __future__ import annotations

import copy
from typing import Any

from app.core.business_tools_sdk import ToolDefinition


def tool_definitions_to_openai_tools(
    definitions: dict[str, ToolDefinition],
    allowed_tools: list[str],
) -> list[dict[str, Any]]:
    """Convert ToolDefinition objects to OpenAI function-calling ``tools=`` format.

    Only tools whose names appear in *allowed_tools* are included.
    ``ToolDefinition.input_schema`` (already JSON Schema) is used as the
    ``parameters`` field.  Descriptions from ``input_field_hints`` are merged
    into ``parameters.properties.*.description`` so the LLM knows what each
    field means.
    """
    allowed_set = set(allowed_tools)
    tools: list[dict[str, Any]] = []
    for name in allowed_tools:
        definition = definitions.get(name)
        if definition is None:
            continue
        tools.append(_definition_to_openai_tool(definition))
    return tools


def _definition_to_openai_tool(definition: ToolDefinition) -> dict[str, Any]:
    """Convert a single ToolDefinition to the OpenAI tool dict format.

    Format::

        {
            "type": "function",
            "function": {
                "name": "...",
                "description": "...",
                "parameters": { ... JSON Schema ... },
            },
        }
    """
    parameters = _build_parameters(definition)
    return {
        "type": "function",
        "function": {
            "name": definition.name,
            "description": _build_description(definition),
            "parameters": parameters,
        },
    }


def _build_description(definition: ToolDefinition) -> str:
    """Build a rich function description from ToolDefinition fields."""
    parts: list[str] = [definition.description]
    if definition.high_risk:
        parts.append("⚠ 高风险操作，需确认后执行。")
    if definition.mode == "write":
        parts.append("写操作。")
    return " ".join(parts)


def _build_parameters(definition: ToolDefinition) -> dict[str, Any]:
    """Build the JSON Schema ``parameters`` dict with enriched descriptions.

    Deep-copies ``input_schema`` to avoid mutating the original, then merges
    ``input_field_hints`` descriptions into each property.
    """
    schema = copy.deepcopy(definition.input_schema)
    if not schema:
        schema = {"type": "object", "properties": {}}

    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return schema

    hints = definition.input_field_hints
    for field_name, hint in hints.items():
        prop = properties.get(field_name)
        if isinstance(prop, dict):
            if "description" not in prop:
                prop["description"] = str(hint)
        else:
            properties[field_name] = {"description": str(hint)}

    if "required" not in schema:
        required_fields = _infer_required_fields(definition)
        if required_fields:
            schema["required"] = required_fields

    return schema


def _infer_required_fields(definition: ToolDefinition) -> list[str]:
    """Infer required fields from operation_required_fields for execute."""
    execute_required = definition.operation_required_fields.get("execute", [])
    if execute_required:
        return list(execute_required)
    return []
