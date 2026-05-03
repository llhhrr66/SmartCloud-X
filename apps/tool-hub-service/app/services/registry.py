import httpx

from app.core.business_tools_sdk import BusinessTool, filter_tool_definitions, build_catalog
from app.core.config import Settings, get_settings
from app.models.tools import ToolDescriptor
from app.core.observability import annotate_current_span, mark_upstream_error, span_or_noop
from app.services.business_tools_client import BusinessToolsClient, BusinessToolsDiscoveryUnavailableError


class ToolRegistry:
    def __init__(
        self,
        settings: Settings | None = None,
        business_tools_client: BusinessToolsClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._business_tools_client = business_tools_client or BusinessToolsClient(self._settings)
        self._catalog: dict[str, BusinessTool] = build_catalog()

    def list_tools(
        self,
        *,
        capability: str | None = None,
        mode: str | None = None,
        tag: str | None = None,
        query: str | None = None,
        strict_remote: bool | None = None,
    ) -> list[ToolDescriptor]:
        effective_strict_remote = self._settings.business_tools_discovery_strict if strict_remote is None else strict_remote
        with span_or_noop(
            "tool_hub.registry.list",
            attributes={"operation": "list", "tool_name": "*", "provider": "business-tools-service" if self._settings.business_tools_transport == "http" else "business-tools"},
        ):
            if self._settings.business_tools_transport == "http":
                try:
                    remote_tools = (
                        self._business_tools_client.discover_tools(
                            capability=capability,
                            mode=mode,
                            tag=tag,
                            query=query,
                        )
                        if effective_strict_remote
                        else self._business_tools_client.list_tools(
                            capability=capability,
                            mode=mode,
                            tag=tag,
                            query=query,
                        )
                    )
                    annotate_current_span(status="completed")
                    return [
                        ToolDescriptor.model_validate(tool.model_dump())
                        for tool in remote_tools
                    ]
                except BusinessToolsDiscoveryUnavailableError:
                    mark_upstream_error("business-tools-service", "discovery-unavailable")
                    raise
                except (httpx.HTTPError, ValueError):
                    mark_upstream_error("business-tools-service", "discovery-fallback")
                    pass
            annotate_current_span(status="fallback-local")
            return [
                ToolDescriptor.model_validate(definition.model_dump())
                for definition in filter_tool_definitions(
                    (tool.definition for _, tool in sorted(self._catalog.items(), key=lambda item: item[0])),
                    capability=capability,
                    mode=mode,
                    tag=tag,
                    query=query,
                )
            ]

    def get_tool(self, tool_name: str) -> BusinessTool | None:
        return self._catalog.get(tool_name)

    def describe_tool(self, tool_name: str, *, strict_remote: bool | None = None) -> ToolDescriptor | None:
        effective_strict_remote = self._settings.business_tools_discovery_strict if strict_remote is None else strict_remote
        with span_or_noop("tool_hub.registry.describe", attributes={"operation": "describe", "tool_name": tool_name}):
            if self._settings.business_tools_transport == "http":
                try:
                    definition = (
                        self._business_tools_client.discover_tool(tool_name)
                        if effective_strict_remote
                        else self._business_tools_client.describe_tool(tool_name)
                    )
                except BusinessToolsDiscoveryUnavailableError:
                    mark_upstream_error("business-tools-service", "describe-unavailable")
                    raise
                except (httpx.HTTPError, ValueError):
                    mark_upstream_error("business-tools-service", "describe-fallback")
                    definition = None
                if effective_strict_remote:
                    return ToolDescriptor.model_validate(definition.model_dump()) if definition is not None else None
                if definition is not None:
                    return ToolDescriptor.model_validate(definition.model_dump())
            tool = self.get_tool(tool_name)
            if tool is None:
                return None
            return ToolDescriptor.model_validate(tool.definition.model_dump())
