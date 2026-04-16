import httpx

from app.core.business_tools_sdk import BusinessTool, filter_tool_definitions, build_catalog
from app.core.config import Settings, get_settings
from app.models.tools import ToolDescriptor
from app.services.business_tools_client import BusinessToolsClient


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
    ) -> list[ToolDescriptor]:
        if self._settings.business_tools_transport == "http":
            try:
                return [
                    ToolDescriptor.model_validate(tool.model_dump())
                    for tool in self._business_tools_client.list_tools(
                        capability=capability,
                        mode=mode,
                        tag=tag,
                        query=query,
                    )
                ]
            except (httpx.HTTPError, ValueError):
                pass
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

    def describe_tool(self, tool_name: str) -> ToolDescriptor | None:
        if self._settings.business_tools_transport == "http":
            try:
                definition = self._business_tools_client.describe_tool(tool_name)
            except (httpx.HTTPError, ValueError):
                definition = None
            if definition is not None:
                return ToolDescriptor.model_validate(definition.model_dump())
        tool = self.get_tool(tool_name)
        if tool is None:
            return None
        return ToolDescriptor.model_validate(tool.definition.model_dump())
