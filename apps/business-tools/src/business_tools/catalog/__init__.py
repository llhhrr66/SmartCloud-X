"""Business-tools catalog package.

The catalog is the registry of every static (in-process) business tool the
orchestrator can dispatch. The implementation is split into:

- ``_helpers``, ``_compensation``, ``_session_context_patch`` — shared
  primitives used by tool builders.
- ``_static_tool`` — the ``StaticBusinessTool`` adapter that enforces the
  cross-cutting policies (validation, auth, confirmation, idempotency).
- ``_factory`` — the ``_tool(...)`` builder + JSON-schema helpers.
- ``_filter`` — the ``filter_tool_definitions`` helper.
- ``domains/*`` — per-domain tool builders + ``_tool(...)`` registrations.

Public API:
- ``build_catalog()`` — assemble the canonical name → ``BusinessTool`` mapping.
- ``filter_tool_definitions(...)`` — filter tool definitions for discovery.
"""

from __future__ import annotations

from business_tools.interfaces import BusinessTool

from ._filter import filter_tool_definitions
from .domains import billing, icp, legacy, marketing, product, research, ticket


def build_catalog() -> dict[str, BusinessTool]:
    tools: list[BusinessTool] = [
        *product.build_tools(),
        *billing.build_tools(),
        *ticket.build_tools(),
        *icp.build_tools(),
        *marketing.build_tools(),
        *research.build_tools(),
        *legacy.build_tools(),
    ]
    return {tool.definition.name: tool for tool in tools}


__all__ = ["build_catalog", "filter_tool_definitions"]
