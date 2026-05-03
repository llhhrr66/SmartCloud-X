from __future__ import annotations

from collections.abc import Iterable

from business_tools.interfaces import BusinessTool, ToolDefinition, ToolMode


def filter_tool_definitions(
    items: Iterable[BusinessTool | ToolDefinition],
    *,
    capability: str | None = None,
    mode: ToolMode | None = None,
    tag: str | None = None,
    query: str | None = None,
) -> list[ToolDefinition]:
    normalized_capability = capability.strip().lower() if capability else None
    normalized_mode = str(mode).strip().lower() if mode else None
    normalized_tag = tag.strip().lower() if tag else None
    normalized_query = query.strip().lower() if query else None

    definitions: list[ToolDefinition] = []
    for item in items:
        definition = item.definition if hasattr(item, "definition") else item
        searchable = " ".join(
            [
                definition.name,
                definition.capability,
                definition.description,
                *definition.tags,
            ]
        ).lower()
        if normalized_capability and definition.capability.lower() != normalized_capability:
            continue
        if normalized_mode and definition.mode.lower() != normalized_mode:
            continue
        if normalized_tag and normalized_tag not in {value.lower() for value in definition.tags}:
            continue
        if normalized_query and normalized_query not in searchable:
            continue
        definitions.append(definition.model_copy(deep=True))
    definitions.sort(key=lambda item: item.name)
    return definitions
