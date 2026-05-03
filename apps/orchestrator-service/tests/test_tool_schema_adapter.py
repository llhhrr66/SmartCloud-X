from app.core.business_tools_sdk import ToolDefinition
from app.services.tool_schema_adapter import (
    _build_description,
    _build_parameters,
    _infer_required_fields,
    tool_definitions_to_openai_tools,
)


def _sample_definition(
    *,
    name: str = "product.catalog_lookup",
    description: str = "查询云产品目录。",
    high_risk: bool = False,
    mode: str = "query",
    input_schema: dict | None = None,
    input_field_hints: dict | None = None,
    operation_required_fields: dict | None = None,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        capability="product",
        description=description,
        high_risk=high_risk,
        mode=mode,
        input_schema=input_schema if input_schema is not None else {
            "type": "object",
            "properties": {
                "category": {"type": "string"},
                "region": {"type": "string"},
            },
        },
        input_field_hints=input_field_hints if input_field_hints is not None else {
            "category": "产品分类，如 GPU、ECS",
            "region": "地域，如 cn-beijing",
        },
        operation_required_fields=operation_required_fields if operation_required_fields is not None else {
            "execute": ["category"],
        },
    )


# ------------------------------------------------------------------
# tool_definitions_to_openai_tools
# ------------------------------------------------------------------


def test_filters_by_allowed_tools() -> None:
    defs = {
        "product.catalog_lookup": _sample_definition(name="product.catalog_lookup"),
        "billing.query_statement": _sample_definition(name="billing.query_statement"),
    }
    result = tool_definitions_to_openai_tools(defs, ["product.catalog_lookup"])
    assert len(result) == 1
    assert result[0]["function"]["name"] == "product.catalog_lookup"


def test_skips_unknown_allowed_tool_names() -> None:
    defs = {"product.catalog_lookup": _sample_definition(name="product.catalog_lookup")}
    result = tool_definitions_to_openai_tools(defs, ["product.catalog_lookup", "nonexistent.tool"])
    assert len(result) == 1


def test_returns_empty_for_no_allowed_tools() -> None:
    defs = {"product.catalog_lookup": _sample_definition(name="product.catalog_lookup")}
    result = tool_definitions_to_openai_tools(defs, [])
    assert result == []


def test_output_format_structure() -> None:
    defs = {"product.catalog_lookup": _sample_definition(name="product.catalog_lookup")}
    result = tool_definitions_to_openai_tools(defs, ["product.catalog_lookup"])
    tool = result[0]
    assert tool["type"] == "function"
    fn = tool["function"]
    assert fn["name"] == "product.catalog_lookup"
    assert "description" in fn
    assert "parameters" in fn
    params = fn["parameters"]
    assert params["type"] == "object"
    assert "properties" in params


# ------------------------------------------------------------------
# _build_description
# ------------------------------------------------------------------


def test_build_description_plain() -> None:
    defn = _sample_definition(description="查询云产品目录。")
    desc = _build_description(defn)
    assert desc == "查询云产品目录。"


def test_build_description_high_risk() -> None:
    defn = _sample_definition(description="提交退款申请。", high_risk=True)
    desc = _build_description(defn)
    assert "高风险操作" in desc


def test_build_description_write_mode() -> None:
    defn = _sample_definition(description="创建工单。", mode="write")
    desc = _build_description(defn)
    assert "写操作" in desc


# ------------------------------------------------------------------
# _build_parameters
# ------------------------------------------------------------------


def test_build_parameters_merges_field_hints() -> None:
    defn = _sample_definition(
        input_schema={
            "type": "object",
            "properties": {
                "category": {"type": "string"},
                "region": {"type": "string"},
            },
        },
        input_field_hints={
            "category": "产品分类",
            "region": "地域",
        },
    )
    params = _build_parameters(defn)
    assert params["properties"]["category"]["description"] == "产品分类"
    assert params["properties"]["region"]["description"] == "地域"


def test_build_parameters_does_not_overwrite_existing_description() -> None:
    defn = _sample_definition(
        input_schema={
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "原有描述"},
            },
        },
        input_field_hints={"category": "提示描述"},
    )
    params = _build_parameters(defn)
    assert params["properties"]["category"]["description"] == "原有描述"


def test_build_parameters_creates_property_for_hint_without_schema() -> None:
    defn = _sample_definition(
        input_schema={"type": "object", "properties": {}},
        input_field_hints={"extra_field": "额外字段说明"},
    )
    params = _build_parameters(defn)
    assert "extra_field" in params["properties"]
    assert params["properties"]["extra_field"]["description"] == "额外字段说明"


def test_build_parameters_infers_required_fields() -> None:
    defn = _sample_definition(
        input_schema={"type": "object", "properties": {"category": {"type": "string"}}},
        operation_required_fields={"execute": ["category"]},
    )
    params = _build_parameters(defn)
    assert params["required"] == ["category"]


def test_build_parameters_does_not_add_required_when_schema_has_it() -> None:
    defn = _sample_definition(
        input_schema={
            "type": "object",
            "properties": {"category": {"type": "string"}},
            "required": ["category", "region"],
        },
        operation_required_fields={"execute": ["category"]},
    )
    params = _build_parameters(defn)
    assert params["required"] == ["category", "region"]


def test_build_parameters_empty_schema() -> None:
    defn = _sample_definition(input_schema={}, input_field_hints={}, operation_required_fields={})
    params = _build_parameters(defn)
    assert params == {"type": "object", "properties": {}}


# ------------------------------------------------------------------
# _infer_required_fields
# ------------------------------------------------------------------


def test_infer_required_fields_from_execute() -> None:
    defn = _sample_definition(operation_required_fields={"execute": ["category", "region"]})
    assert _infer_required_fields(defn) == ["category", "region"]


def test_infer_required_fields_empty() -> None:
    defn = _sample_definition(operation_required_fields={})
    assert _infer_required_fields(defn) == []
