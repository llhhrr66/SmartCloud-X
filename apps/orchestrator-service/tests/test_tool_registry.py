from __future__ import annotations

import pytest

from app.tools.registry import (
    ALL_AGENT_DISALLOWED_TOOLS,
    ROLE_TOOL_WHITELIST,
    ToolDefinition,
    ToolRegistry,
    get_tool_registry,
)
from app.tools.permissions import PermissionMode, PermissionResult, check_permission
from app.tools.definitions import knowledge_tools, marketing_tools, research_tools

from pydantic import BaseModel


class _FakeInput(BaseModel):
    x: int


def _noop_execute(inp, ctx):
    return {"ok": True}


def _build_registry_with_fixtures() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(ToolDefinition(
        name="search_documents",
        description="search",
        input_schema=_FakeInput,
        is_readonly=True,
        allowed_roles=["research", "marketing", "admin"],
        execute_func=_noop_execute,
    ))
    reg.register(ToolDefinition(
        name="import_document",
        description="import",
        input_schema=_FakeInput,
        is_readonly=False,
        allowed_roles=["admin"],
        execute_func=_noop_execute,
    ))
    reg.register(ToolDefinition(
        name="generate_poster",
        description="poster",
        input_schema=_FakeInput,
        is_readonly=False,
        allowed_roles=["marketing", "admin"],
        execute_func=_noop_execute,
    ))
    reg.register(ToolDefinition(
        name="search",
        description="web search",
        input_schema=_FakeInput,
        is_readonly=True,
        allowed_roles=["research", "admin"],
        execute_func=_noop_execute,
    ))
    reg.register(ToolDefinition(
        name="delete_database",
        description="DANGER",
        input_schema=_FakeInput,
        is_readonly=False,
        allowed_roles=["admin"],
        execute_func=_noop_execute,
    ))
    return reg


class TestToolRegistration:
    def test_register_and_get(self):
        reg = ToolRegistry()
        tool = ToolDefinition(name="t1", description="d", input_schema=_FakeInput)
        reg.register(tool)
        assert reg.get_tool("t1") is tool
        assert reg.get_tool("missing") is None

    def test_register_overwrites_by_name(self):
        reg = ToolRegistry()
        t1 = ToolDefinition(name="t", description="first", input_schema=_FakeInput)
        t2 = ToolDefinition(name="t", description="second", input_schema=_FakeInput)
        reg.register(t1)
        reg.register(t2)
        assert reg.get_tool("t").description == "second"

    def test_predefined_tools_registered(self):
        all_tools = knowledge_tools + marketing_tools + research_tools
        names = {t.name for t in all_tools}
        expected = {
            "search_documents", "generate_poster", "search",
            "import_document", "create_campaign", "generate_copy",
            "analyze", "research_query", "list_knowledge_bases",
        }
        assert expected <= names

    def test_all_tool_input_schemas_are_pydantic(self):
        all_tools = knowledge_tools + marketing_tools + research_tools
        for tool in all_tools:
            assert issubclass(tool.input_schema, BaseModel)


class TestRoleFiltering:
    def test_admin_gets_all_non_denied(self):
        reg = _build_registry_with_fixtures()
        tools = reg.get_tools_for_role("admin")
        names = {t.name for t in tools}
        assert "search_documents" in names
        assert "import_document" in names
        assert "generate_poster" in names
        assert "delete_database" not in names

    def test_research_only_gets_whitelisted(self):
        reg = _build_registry_with_fixtures()
        tools = reg.get_tools_for_role("research")
        names = {t.name for t in tools}
        assert "search_documents" in names
        assert "search" in names
        assert "import_document" not in names
        assert "generate_poster" not in names

    def test_marketing_only_gets_whitelisted(self):
        reg = _build_registry_with_fixtures()
        tools = reg.get_tools_for_role("marketing")
        names = {t.name for t in tools}
        assert "search_documents" in names
        assert "generate_poster" in names
        assert "search" not in names


class TestDenyAllowLogic:
    def test_filter_with_deny_list(self):
        reg = _build_registry_with_fixtures()
        tools = reg.filter_tools(deny_list={"import_document"})
        names = {t.name for t in tools}
        assert "import_document" not in names
        assert "search_documents" in names

    def test_filter_with_allow_list(self):
        reg = _build_registry_with_fixtures()
        tools = reg.filter_tools(allow_list={"search_documents", "import_document"})
        assert {t.name for t in tools} == {"search_documents", "import_document"}

    def test_filter_allow_then_deny(self):
        reg = _build_registry_with_fixtures()
        tools = reg.filter_tools(
            allow_list={"search_documents", "import_document"},
            deny_list={"import_document"},
        )
        assert {t.name for t in tools} == {"search_documents"}

    def test_filter_deny_removes_multiple(self):
        reg = _build_registry_with_fixtures()
        tools = reg.filter_tools(deny_list={"search_documents", "generate_poster"})
        names = {t.name for t in tools}
        assert "search_documents" not in names
        assert "generate_poster" not in names
        assert "search" in names


class TestThreeLayerDefense:
    def test_layer1_blocks_disallowed(self):
        reg = _build_registry_with_fixtures()
        tools = reg.get_tools_for_role("admin")
        assert "delete_database" not in {t.name for t in tools}

    def test_layer1_covers_dangerous_ops(self):
        dangerous = {"delete_database", "drop_table", "truncate_table", "execute_raw_sql"}
        assert dangerous <= ALL_AGENT_DISALLOWED_TOOLS

    def test_layer2_all_roles_declared(self):
        for role in ["admin", "research", "marketing"]:
            assert role in ROLE_TOOL_WHITELIST

    def test_layer3_runtime_check(self):
        reg = _build_registry_with_fixtures()
        calls = []

        def checker(tool, ctx):
            calls.append(tool.name)
            return tool.name != "generate_poster"

        tools = reg.get_tools_for_role(
            "admin",
            user_context={"tenant_id": "t1"},
            permission_checker=checker,
        )
        assert len(calls) > 0
        assert "generate_poster" not in {t.name for t in tools}

    def test_layer3_skipped_without_context(self):
        reg = _build_registry_with_fixtures()
        tools = reg.get_tools_for_role("admin")
        assert "generate_poster" in {t.name for t in tools}


class TestPermissions:
    def test_readonly_auto(self):
        result = check_permission("search_documents", True, "research")
        assert result.mode == PermissionMode.AUTO

    def test_admin_write_auto(self):
        result = check_permission("import_document", False, "admin")
        assert result.mode == PermissionMode.AUTO

    def test_marketing_write_asks(self):
        result = check_permission("generate_poster", False, "marketing")
        assert result.mode == PermissionMode.ASK

    def test_research_write_asks(self):
        result = check_permission("dangerous", False, "research")
        assert result.mode == PermissionMode.ASK

    def test_unknown_write_denied(self):
        result = check_permission("dangerous", False, "guest")
        assert result.mode == PermissionMode.DENY


class TestSingleton:
    def test_same_instance(self):
        r1 = get_tool_registry()
        r2 = get_tool_registry()
        assert r1 is r2


class TestSchemaValidation:
    def test_import_document_rejects_missing_kb(self):
        from app.tools.definitions.knowledge_tools import ImportDocumentInput
        with pytest.raises(Exception):
            ImportDocumentInput.model_validate({"source_url": "http://x"})

    def test_poster_rejects_invalid_style(self):
        from app.tools.definitions.marketing_tools import GeneratePosterInput
        with pytest.raises(Exception):
            GeneratePosterInput.model_validate({"title": "test", "style": "bad"})

    def test_search_requires_query(self):
        from app.tools.definitions.research_tools import SearchInput
        with pytest.raises(Exception):
            SearchInput.model_validate({})