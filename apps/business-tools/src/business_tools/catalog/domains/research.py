from __future__ import annotations

import json
from typing import Any

from business_tools.db import query_one
from business_tools.interfaces import ToolAuthRequirements, ToolInvocationRequest

from .._factory import _tool
from .._helpers import _normalize_string_list, _query_payload, _slugify_token, _with_result
from .._static_tool import StaticBusinessTool


def _research_generate_report_builder(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    topic = request.payload.get("topic") or _query_payload(request) or "待补充研究主题"

    # Try DB first — look for existing completed research on this topic
    row = query_one(
        "SELECT task_id, topic, summary, agent_result FROM research_tasks "
        "WHERE topic = :topic AND status = 'completed' AND deleted_at IS NULL "
        "ORDER BY updated_at DESC LIMIT 1",
        {"topic": topic},
    )
    if row:
        agent_result = row.get("agent_result")
        sections: list[str] = []
        executive_summary = row.get("summary") or ""
        if isinstance(agent_result, str):
            try:
                agent_result = json.loads(agent_result)
            except (json.JSONDecodeError, TypeError):
                agent_result = None
        if isinstance(agent_result, dict):
            executive_summary = agent_result.get("summary") or executive_summary
            for section in agent_result.get("sections") or []:
                if isinstance(section, dict) and section.get("title"):
                    sections.append(section["title"])
        if not sections:
            sections = ["业务背景与目标", "候选方案对比", "成本与风险评估", "推荐路线与下一步行动"]
        return _with_result(
            "已返回调研报告数据。",
            {
                "topic": row["topic"],
                "executive_summary": executive_summary,
                "outline": sections,
            },
            "db://research-tasks/" + row["task_id"],
        )

    # Fallback
    return _with_result(
        "已生成调研报告基线结构。",
        {
            "topic": topic,
            "executive_summary": "建议优先采用稳定可观测的多 Agent + Tool Hub 组合架构。",
            "outline": [
                "业务背景与目标",
                "候选方案对比",
                "成本与风险评估",
                "推荐路线与下一步行动",
            ],
        },
        "baseline://research-generate-report",
    )


def _research_reference_builder(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    topic = request.payload.get("topic") or _query_payload(request) or "待补充研究主题"

    # Try DB first — look for existing research task with reference data
    row = query_one(
        "SELECT task_id, topic, reference_urls, agent_result FROM research_tasks "
        "WHERE topic = :topic AND status = 'completed' AND deleted_at IS NULL "
        "ORDER BY updated_at DESC LIMIT 1",
        {"topic": topic},
    )
    if row:
        references: list[dict[str, str]] = []

        # Parse reference_urls
        ref_urls = row.get("reference_urls")
        if isinstance(ref_urls, str):
            try:
                ref_urls = json.loads(ref_urls)
            except (json.JSONDecodeError, TypeError):
                ref_urls = []
        if isinstance(ref_urls, list):
            for url in ref_urls:
                if isinstance(url, str) and url:
                    references.append({"title": url, "type": "reference-url"})

        # Parse citations from agent_result
        agent_result = row.get("agent_result")
        if isinstance(agent_result, str):
            try:
                agent_result = json.loads(agent_result)
            except (json.JSONDecodeError, TypeError):
                agent_result = None
        if isinstance(agent_result, dict):
            for citation in agent_result.get("citations") or []:
                if isinstance(citation, dict):
                    references.append({
                        "title": citation.get("title") or citation.get("url") or "参考来源",
                        "type": "citation",
                    })

        if references:
            return _with_result(
                "已返回调研参考源数据。",
                {
                    "topic": row["topic"],
                    "references": references,
                },
                "db://research-tasks/" + row["task_id"],
            )

    # Fallback
    return _with_result(
        "已收集调研参考源。",
        {
            "topic": topic,
            "references": [
                {"title": "LangGraph overview", "type": "official-doc"},
                {"title": "AWS Saga orchestration pattern", "type": "architecture"},
                {"title": "Phoenix observability docs", "type": "observability"},
            ],
        },
        "baseline://research-references",
    )


def _research_export_report_builder(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    topic = request.payload.get("topic") or _query_payload(request) or "待补充研究主题"
    export_format = str(request.payload.get("format", "markdown")).lower()
    if export_format not in {"markdown", "pdf"}:
        export_format = "markdown"
    topic_slug = _slugify_token(topic, fallback="research-report")

    # Try DB first — look for existing completed research with report file
    row = query_one(
        "SELECT task_id, topic, summary, output_format, report_file_id, agent_result "
        "FROM research_tasks "
        "WHERE topic = :topic AND status = 'completed' AND deleted_at IS NULL "
        "ORDER BY updated_at DESC LIMIT 1",
        {"topic": topic},
    )
    if row and row.get("report_file_id"):
        agent_result = row.get("agent_result")
        sections: list[dict[str, str]] = []
        if isinstance(agent_result, str):
            try:
                agent_result = json.loads(agent_result)
            except (json.JSONDecodeError, TypeError):
                agent_result = None
        if isinstance(agent_result, dict):
            sections = agent_result.get("sections") or []

        # Build content preview from DB sections
        content_parts = [f"# {row['topic']}", ""]
        summary = row.get("summary") or ""
        if summary:
            content_parts += ["## 摘要", summary, ""]
        for section in sections[:6]:
            if isinstance(section, dict):
                content_parts.append(f"## {section.get('title', '')}")
                content_parts.append(section.get("content", ""))
                content_parts.append("")

        report_format = row.get("output_format") or export_format
        extension = "md" if report_format == "markdown" else "pdf"
        return _with_result(
            "已返回调研报告导出数据。",
            {
                "artifact_id": row["report_file_id"],
                "topic": row["topic"],
                "format": report_format,
                "download_path": f"/artifacts/research/{topic_slug}.{extension}",
                "content_preview": "\n".join(content_parts),
                "line_count": len("\n".join(content_parts).splitlines()),
            },
            "db://research-tasks/" + row["task_id"],
        )

    # Fallback
    outline = _normalize_string_list(request.payload.get("outline")) or [
        "业务背景与目标",
        "候选方案对比",
        "成本与风险评估",
        "推荐路线与下一步行动",
    ]
    reference_titles = _normalize_string_list(request.payload.get("reference_titles"))
    content_preview = "\n".join(
        [
            f"# {topic}",
            "",
            "## 摘要",
            "建议优先采用稳定可观测的多 Agent + Tool Hub 组合架构。",
            "",
            "## 目录",
            *[f"- {item}" for item in outline[:4]],
        ]
    )
    if reference_titles:
        content_preview = "\n".join(
            [
                content_preview,
                "",
                "## 参考资料",
                *[f"- {title}" for title in reference_titles[:3]],
            ]
        )
    extension = "md" if export_format == "markdown" else "pdf"
    return _with_result(
        "已导出调研报告基线文件。",
        {
            "artifact_id": f"research_{topic_slug}_{export_format}",
            "topic": topic,
            "format": export_format,
            "download_path": f"/artifacts/research/{topic_slug}.{extension}",
            "content_preview": content_preview,
            "line_count": len(content_preview.splitlines()),
        },
        "baseline://research-export-report",
    )


def build_tools() -> list[StaticBusinessTool]:
    return [
        _tool(
            name="research.generate_report",
            capability="deep-research",
            description="Create a structured report skeleton for research tasks.",
            tags=["research", "report"],
            input_schema_hint={"topic": "string"},
            input_field_hints={"topic": "需要确认调研主题。"},
            output_schema_hint={"topic": "string", "executive_summary": "string", "outline": "string[]"},
            session_context_output_keys=["attributes.research_topic", "attributes.report_outline"],
            auth_requirements=ToolAuthRequirements(
                require_user_id=True,
                required_permissions=["user:research.write"],
            ),
            operation_required_fields={"preview": ["topic"], "execute": ["topic"]},
            cache_ttl_seconds=300,
            preview_builder=_research_generate_report_builder,
            execute_builder=_research_generate_report_builder,
        ),
        _tool(
            name="research.reference_search",
            capability="deep-research",
            description="Collect references for research tasks.",
            tags=["research", "references"],
            input_schema_hint={"topic": "string", "limit": "integer?"},
            input_field_hints={"topic": "需要确认调研主题。"},
            output_schema_hint={"references": "object[]"},
            session_context_bindings={"topic": ["attributes.research_topic"]},
            session_context_output_keys=["attributes.reference_titles"],
            prerequisite_tool_names=["research.generate_report"],
            auth_requirements=ToolAuthRequirements(
                require_user_id=True,
                required_permissions=["user:research.write"],
            ),
            operation_required_fields={"preview": ["topic"], "execute": ["topic"]},
            cache_ttl_seconds=300,
            preview_builder=_research_reference_builder,
            execute_builder=_research_reference_builder,
        ),
        _tool(
            name="research.export_report",
            capability="deep-research",
            description="Export the prepared research report to markdown or PDF.",
            tags=["research", "export", "artifact"],
            input_schema_hint={
                "topic": "string",
                "format": "markdown|pdf?",
                "outline": "string[]?",
                "reference_titles": "string[]?",
            },
            input_field_hints={"topic": "需要先确认调研主题或先生成调研报告。"},
            output_schema_hint={
                "artifact_id": "string",
                "format": "string",
                "download_path": "string",
                "content_preview": "string",
                "line_count": "integer",
            },
            session_context_bindings={
                "topic": ["attributes.research_topic"],
                "outline": ["attributes.report_outline"],
                "reference_titles": ["attributes.reference_titles"],
            },
            session_context_output_keys=[
                "attributes.last_report_export_id",
                "attributes.last_report_export_path",
                "attributes.last_report_export_format",
            ],
            prerequisite_tool_names=["research.reference_search"],
            mode="write",
            auth_requirements=ToolAuthRequirements(
                require_user_id=True,
                required_permissions=["user:research.write"],
            ),
            operation_required_fields={"preview": ["topic"], "execute": ["topic"]},
            timeout_ms=12000,
            idempotent=True,
            idempotency_window_seconds=86400,
            preview_builder=_research_export_report_builder,
            execute_builder=_research_export_report_builder,
        ),
    ]
