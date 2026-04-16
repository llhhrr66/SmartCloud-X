from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable
import re

from app.core.business_tools_sdk import ToolDefinition, ToolExecutionContext, build_catalog, is_missing_tool_value
from app.core.config import get_settings
from app.models.orchestration import (
    AgentAdminRecord,
    AgentDescriptor,
    AgentName,
    AgentTask,
    AgentConfigUpdateRequest,
    ExecutionCheckpoint,
    HandoffStep,
    IntentSignal,
    IntentSummary,
    RouteDecision,
    RouteRequest,
    SceneName,
    ToolPlanItem,
)
from app.services.agent_config_store import AgentConfigStore
from app.services.tool_context import (
    available_session_context_keys,
    hydrate_payload_from_session_context,
    session_context_input_keys,
)
from app.services.tool_hub_client import ToolHubClient


class AgentRouter:
    """Keyword-based supervisor baseline router with spec-aligned metadata.

    Keeps stable planning output for a later LangGraph state machine.
    """

    AGENT_KEYWORDS: OrderedDict[str, tuple[str, ...]] = OrderedDict(
        [
            ("finance_order_agent", ("账单", "订单", "退款", "发票", "扣费", "工单")),
            ("icp_service_agent", ("备案", "实名", "合规", "icp", "核验")),
            ("ops_marketing_agent", ("营销", "活动", "海报", "推广", "优惠", "促销", "文案")),
            ("deep_research_agent", ("调研", "研究", "对比", "报告", "选型", "方案评估")),
            ("product_tech_agent", ("gpu", "云服务器", "ecs", "部署", "技术", "配置", "故障")),
        ]
    )
    HUMAN_HANDOFF_KEYWORDS = ("人工", "转人工", "投诉", "升级", "紧急", "电话联系")
    HIGH_URGENCY_KEYWORDS = ("紧急", "故障", "投诉", "服务异常")
    RETRIEVAL_KEYWORDS = ("文档", "教程", "faq", "方案", "how", "最佳实践", "排查", "研究", "对比")
    SCENE_TO_AGENT: dict[SceneName, AgentName] = {
        "billing": "finance_order_agent",
        "technical_support": "product_tech_agent",
        "icp": "icp_service_agent",
        "marketing": "ops_marketing_agent",
        "research": "deep_research_agent",
        "customer_service": "product_tech_agent",
    }
    AGENT_REGISTRY: dict[AgentName, dict[str, object]] = {
        "product_tech_agent": {
            "code": "product_tech",
            "display_name": "Product_Tech_Agent",
            "description": "处理产品咨询、云服务器、GPU、部署与技术排障。",
            "supported_scenes": ["customer_service", "technical_support", "research"],
            "allowed_tools": ["product.catalog_lookup", "support.playbook_search"],
            "fallback_agent": "orchestrator",
        },
            "finance_order_agent": {
                "code": "finance_order",
                "display_name": "Finance_Order_Agent",
                "description": "处理账单、订单、发票、退款和工单相关问题。",
                "supported_scenes": ["billing", "customer_service"],
            "allowed_tools": [
                "billing.query_statement",
                "order.query_order",
                "billing.create_invoice",
                "invoice.query_invoice",
                "order.create_refund",
                "ticket.create",
                "ticket.reply",
                "ticket.query_ticket",
            ],
            "fallback_agent": "orchestrator",
        },
        "icp_service_agent": {
            "code": "icp_service",
            "display_name": "ICP_Service_Agent",
            "description": "处理备案材料检查、流程说明与备案申请。",
            "supported_scenes": ["icp", "customer_service"],
            "allowed_tools": [
                "icp.material_check",
                "icp.verify_subject",
                "icp.submit_application",
                "icp.query_application",
            ],
            "fallback_agent": "orchestrator",
        },
            "ops_marketing_agent": {
                "code": "ops_marketing",
                "display_name": "Ops_Marketing_Agent",
                "description": "处理活动营销、海报 brief 与推广建议。",
                "supported_scenes": ["marketing", "customer_service"],
                "allowed_tools": [
                    "marketing.campaign_lookup",
                    "marketing.poster_brief",
                    "marketing.generate_copy",
                    "marketing.generate_promotion_link",
                    "marketing.generate_poster",
                ],
                "fallback_agent": "orchestrator",
            },
        "deep_research_agent": {
            "code": "deep_research",
            "display_name": "Deep_Research_Agent",
            "description": "处理技术选型、行业调研与报告生成。",
            "supported_scenes": ["research", "technical_support"],
            "allowed_tools": [
                "research.generate_report",
                "research.reference_search",
                "research.export_report",
            ],
            "fallback_agent": "orchestrator",
        },
    }
    IDENTIFIER_PATTERNS: dict[str, re.Pattern[str]] = {
        "order_no": re.compile(r"\b(ord[-_][a-z0-9._-]+)\b", re.IGNORECASE),
        "refund_no": re.compile(r"\b(refund[-_][a-z0-9._-]+)\b", re.IGNORECASE),
        "invoice_no": re.compile(r"\b(inv[-_][a-z0-9._-]+)\b", re.IGNORECASE),
        "ticket_no": re.compile(r"\b(tk[-_][a-z0-9._-]+)\b", re.IGNORECASE),
        "application_no": re.compile(r"\b(icp[-_][a-z0-9._-]+)\b", re.IGNORECASE),
    }
    CERTIFICATE_NO_PATTERN = re.compile(r"\b([0-9A-Z]{15,18})\b", re.IGNORECASE)
    PHONE_PATTERN = re.compile(r"(?<!\d)(1\d{10})(?!\d)")

    def __init__(
        self,
        tool_hub_client: ToolHubClient | None = None,
        agent_config_store: AgentConfigStore | None = None,
    ) -> None:
        self._catalog = build_catalog()
        self._tool_hub_client = tool_hub_client or ToolHubClient()
        self._settings = get_settings()
        self._agent_config_store = agent_config_store or AgentConfigStore()
        self._remote_tool_definitions: dict[str, ToolDefinition] | None = None

    def route(self, request: RouteRequest) -> RouteDecision:
        text = request.user_query.lower()
        explicit_tool_candidates = self._expand_tool_candidates(request.tool_candidates)
        signals = self._build_signals(text)
        primary = self._select_primary_agent(
            signals,
            request.preferred_agents,
            request.scene,
            explicit_tool_candidates,
        )
        supporting_agents = self._select_supporting_agents(
            primary,
            signals,
            text,
            request,
            explicit_tool_candidates,
        )
        requires_retrieval = self._determine_retrieval(request, text, primary)
        intent = IntentSummary(
            domain=primary.replace("_agent", ""),
            matched_domains=[signal.label for signal in signals if signal.score > 0],
            signals=signals,
            urgency=self._determine_urgency(text),
            needs_human_handoff=any(token in request.user_query for token in self.HUMAN_HANDOFF_KEYWORDS),
            scene=self._infer_scene(primary, request.scene),
        )
        tool_plan = self._build_tool_plan(
            request,
            primary,
            supporting_agents,
            text,
            explicit_tool_candidates,
        )
        requires_tools = bool(tool_plan)
        handoff_plan = self._build_handoff_plan(primary, supporting_agents, requires_retrieval, tool_plan)
        tasks = [
            AgentTask(
                agent=step.agent,
                reason=step.objective,
                requires_retrieval=step.requires_retrieval,
                suggested_tools=step.tool_names,
                handoff_step_id=step.step_id,
                depends_on_tool_call_ids=step.depends_on_tool_call_ids,
                session_context_inputs=step.session_context_inputs,
                session_context_outputs=step.session_context_outputs,
            )
            for step in handoff_plan
        ]
        checkpoints = self._build_checkpoints(
            requires_retrieval,
            requires_tools,
            intent.needs_human_handoff,
            tool_plan,
            request,
        )
        return RouteDecision(
            primary_agent=primary,
            supporting_agents=supporting_agents,
            requires_retrieval=requires_retrieval,
            requires_tools=requires_tools,
            needs_human_handoff=intent.needs_human_handoff,
            intent=intent,
            tasks=tasks,
            handoff_plan=handoff_plan,
            tool_plan=tool_plan,
            checkpoints=checkpoints,
            summary=(
                f"Routed to {primary} with {len(supporting_agents)} supporting agent(s); "
                f"retrieval={requires_retrieval}, tools={len(tool_plan)}, "
                f"human_handoff={intent.needs_human_handoff}."
            ),
        )

    def available_agents(self) -> list[AgentDescriptor]:
        routable_agents = self._routable_agents()
        return [
            self._agent_descriptor(agent)
            for agent in routable_agents
        ]

    def available_admin_agents(
        self,
        *,
        scene: SceneName | None = None,
        status: str | None = None,
    ) -> list[AgentAdminRecord]:
        normalized_status = status.strip().lower() if status else None
        items = [
            self._admin_agent_record(agent)
            for agent in self.AGENT_REGISTRY
        ]
        if scene is not None:
            items = [item for item in items if scene in item.supported_scenes]
        if normalized_status == "enabled":
            items = [item for item in items if item.enabled]
        elif normalized_status == "disabled":
            items = [item for item in items if not item.enabled]
        return items

    def get_admin_agent(self, agent_code: str) -> AgentAdminRecord:
        agent_name = self._resolve_agent_name(agent_code)
        return self._admin_agent_record(agent_name)

    def update_agent_config(
        self,
        agent_code: str,
        payload: AgentConfigUpdateRequest,
    ) -> AgentAdminRecord:
        agent_name = self._resolve_agent_name(agent_code)
        values = payload.model_dump(exclude_unset=True)
        fallback_agent = values.get("fallback_agent")
        if fallback_agent is not None:
            values["fallback_agent"] = self._normalize_fallback_agent(fallback_agent)
        self._agent_config_store.upsert(
            agent_name=agent_name,
            agent_code=self._agent_code(agent_name),
            values=values,
        )
        return self._admin_agent_record(agent_name)

    def _build_signals(self, text: str) -> list[IntentSignal]:
        signals: list[IntentSignal] = []
        for agent, keywords in self.AGENT_KEYWORDS.items():
            matched = [keyword for keyword in keywords if keyword in text]
            signals.append(
                IntentSignal(
                    label=agent,
                    score=len(matched),
                    matched_keywords=matched,
                )
            )
        return signals

    def _select_primary_agent(
        self,
        signals: list[IntentSignal],
        preferred_agents: list[AgentName],
        scene: SceneName,
        tool_candidates: list[str],
    ) -> AgentName:
        ranked = sorted(
            [signal for signal in signals if signal.label in self.AGENT_REGISTRY],
            key=lambda signal: (signal.score, -list(self.AGENT_KEYWORDS.keys()).index(signal.label)),
            reverse=True,
        )
        if preferred_agents:
            for preferred_agent in preferred_agents:
                resolved = self._resolve_primary_agent(preferred_agent)
                if resolved is not None:
                    return resolved
        candidate_owner = self._primary_agent_for_tool_candidates(tool_candidates)
        if candidate_owner is not None:
            return candidate_owner
        for signal in ranked:
            if signal.score <= 0:
                continue
            resolved = self._resolve_primary_agent(signal.label)  # type: ignore[arg-type]
            if resolved is not None:
                return resolved
        scene_agent = self.SCENE_TO_AGENT.get(scene, "product_tech_agent")
        resolved_scene_agent = self._resolve_primary_agent(scene_agent)
        if resolved_scene_agent is not None:
            return resolved_scene_agent
        return self._routable_agents()[0]

    def _select_supporting_agents(
        self,
        primary: AgentName,
        signals: list[IntentSignal],
        text: str,
        request: RouteRequest,
        tool_candidates: list[str],
    ) -> list[AgentName]:
        if not request.constraints.allow_handoff:
            return []
        routable_agents = set(self._routable_agents())
        supporting: list[AgentName] = []
        if request.tool_candidates:
            supporting.extend(
                agent
                for agent in request.preferred_agents[1:]
                if agent != primary and agent in routable_agents
            )
            for tool_name in tool_candidates:
                supporting.extend(
                    agent
                    for agent in self._tool_owner_agents(tool_name)
                    if agent != primary and agent in routable_agents
                )
            deduped: list[AgentName] = []
            for agent in supporting:
                if agent not in deduped:
                    deduped.append(agent)
            return deduped[: max(self._settings.max_handoff_steps - 1, 0)]
        for signal in signals:
            if signal.label == primary or signal.score <= 0 or signal.label not in routable_agents:
                continue
            supporting.append(signal.label)  # type: ignore[arg-type]
        if (
            primary == "product_tech_agent"
            and "ops_marketing_agent" in routable_agents
            and any(token in text for token in ("活动", "优惠", "促销"))
        ):
            supporting.append("ops_marketing_agent")
        if (
            primary == "deep_research_agent"
            and "product_tech_agent" in routable_agents
            and any(
            token in text for token in ("gpu", "云服务器", "部署", "技术")
            )
        ):
            supporting.append("product_tech_agent")
        deduped: list[AgentName] = []
        for agent in supporting:
            if agent not in deduped:
                deduped.append(agent)
        if primary == "ops_marketing_agent" and any(
            token in text for token in ("推广链接", "短链", "海报", "文案", "宣传")
        ):
            deduped = [agent for agent in deduped if agent != "product_tech_agent"]
        return deduped[: max(self._settings.max_handoff_steps - 1, 0)]

    def _determine_retrieval(self, request: RouteRequest, text: str, primary: AgentName) -> bool:
        if request.constraints.must_cite:
            return True
        if request.retrieval_required is not None:
            return request.retrieval_required
        return primary in {"deep_research_agent", "product_tech_agent"} and any(
            token in text for token in self.RETRIEVAL_KEYWORDS
        )

    def _determine_urgency(self, text: str) -> str:
        if any(token in text for token in self.HIGH_URGENCY_KEYWORDS):
            return "high"
        if any(token in text for token in ("尽快", "今天", "马上")):
            return "medium"
        return "low"

    def _infer_scene(self, primary: AgentName, requested_scene: SceneName) -> SceneName:
        if requested_scene != "customer_service":
            return requested_scene
        mapping: dict[AgentName, SceneName] = {
            "product_tech_agent": "technical_support",
            "finance_order_agent": "billing",
            "icp_service_agent": "icp",
            "ops_marketing_agent": "marketing",
            "deep_research_agent": "research",
        }
        return mapping.get(primary, "customer_service")

    def _build_handoff_plan(
        self,
        primary: AgentName,
        supporting_agents: list[AgentName],
        requires_retrieval: bool,
        tool_plan: list[ToolPlanItem],
    ) -> list[HandoffStep]:
        ordered_agents = [primary, *supporting_agents][: self._settings.max_handoff_steps]
        handoff_plan: list[HandoffStep] = []
        previous_step_id: str | None = None
        for index, agent in enumerate(ordered_agents, start=1):
            step_id = f"step-{index}-{agent}"
            step_items = [item for item in tool_plan if item.assigned_agent == agent]
            step_tools = [item.tool_name for item in step_items]
            handoff_plan.append(
                HandoffStep(
                    step_id=step_id,
                    order=index,
                    agent=agent,
                    objective=self._step_objective(agent, index == 1),
                    depends_on=[previous_step_id] if previous_step_id else [],
                    requires_retrieval=requires_retrieval if index == 1 else False,
                    tool_names=step_tools,
                    depends_on_tool_call_ids=self._dedupe_strings(
                        dependency_id
                        for item in step_items
                        for dependency_id in item.depends_on_tool_call_ids
                    ),
                    session_context_inputs=self._dedupe_strings(
                        context_key
                        for item in step_items
                        for context_key in item.session_context_input_keys
                    ),
                    session_context_outputs=self._dedupe_strings(
                        context_key
                        for item in step_items
                        for context_key in item.session_context_output_keys
                    ),
                    exit_criteria="产出结构化摘要并交回 supervisor 聚合。",
                )
            )
            previous_step_id = step_id
        return handoff_plan

    def _step_objective(self, agent: AgentName, primary: bool) -> str:
        objectives = {
            "product_tech_agent": "评估产品选型、部署方案与技术排障建议。",
            "finance_order_agent": "核对账单、订单、退款、发票或工单处理状态。",
            "icp_service_agent": "核对备案材料、流程或状态，并指出缺口。",
            "ops_marketing_agent": "整理活动、营销文案和海报 brief 候选。",
            "deep_research_agent": "组织调研提纲、参考资料与报告结构。",
        }
        prefix = "主处理" if primary else "补充处理"
        return f"{prefix}：{objectives[agent]}"

    def _build_tool_plan(
        self,
        request: RouteRequest,
        primary: AgentName,
        supporting_agents: list[AgentName],
        text: str,
        tool_candidates: list[str],
    ) -> list[ToolPlanItem]:
        ordered_agents = [primary, *supporting_agents]
        selected_tools: list[ToolPlanItem] = []
        available_context_keys = available_session_context_keys(request.session_context)
        produced_context_keys: dict[str, str] = {}
        confirmed_tool_names = self._confirmed_tool_names(request)
        for agent in ordered_agents:
            suggested_tools = self._order_tools_for_dependencies(
                self._suggest_tools(agent, request, text, tool_candidates)
            )[: min(request.constraints.max_tool_calls, self._agent_descriptor(agent).max_tool_calls)]
            for index, tool_name in enumerate(suggested_tools, start=1):
                definition = self._tool_definitions().get(tool_name)
                operation = "execute"
                if definition is None:
                    operation = "preview"
                payload = self._build_tool_payload(tool_name, request, text, definition)
                required_fields = (
                    list(definition.operation_required_fields.get("execute", []))
                    if definition is not None
                    else []
                )
                missing_payload, deferred_payload, dependency_ids = self._resolve_payload_requirements(
                    definition=definition,
                    payload=payload,
                    required_fields=required_fields,
                    available_context_keys=available_context_keys,
                    produced_context_keys=produced_context_keys,
                    selected_tools=selected_tools,
                )
                missing_auth = self._missing_auth_context(definition, request, operation=operation) if definition else []
                confirmation_pending = bool(
                    definition
                    and operation == "execute"
                    and definition.auth_requirements.confirmation_required
                    and tool_name not in confirmed_tool_names
                )
                if (
                    definition is not None
                    and operation == "execute"
                    and confirmation_pending
                    and not missing_payload
                    and not missing_auth
                ):
                    operation = "preview"
                    confirmation_pending = False
                selected_tools.append(
                    ToolPlanItem(
                        tool_call_id=f"tc-{agent}-{index}",
                        tool_name=tool_name,
                        assigned_agent=agent,
                        operation=operation,
                        reason=f"{agent} needs {tool_name} for baseline orchestration.",
                        payload=payload,
                        required_payload_fields=required_fields,
                        missing_payload_fields=missing_payload,
                        deferred_payload_fields=deferred_payload,
                        missing_payload_hints={
                            field: definition.input_field_hints[field]
                            for field in [*missing_payload, *deferred_payload]
                            if definition and field in definition.input_field_hints
                        },
                        depends_on_tool_call_ids=dependency_ids,
                        session_context_input_keys=session_context_input_keys(definition),
                        session_context_output_keys=list(definition.session_context_output_keys) if definition else [],
                        readiness=self._tool_readiness(
                            missing_payload=missing_payload,
                            dependency_ids=dependency_ids,
                            missing_auth=missing_auth,
                            confirmation_pending=confirmation_pending,
                        ),
                        auth_required=bool(missing_auth),
                        requires_account_context=bool(
                            definition and definition.auth_requirements.require_account_id
                        ),
                        required_permissions=list(
                            definition.auth_requirements.required_permissions if definition else []
                        ),
                        high_risk=bool(definition and definition.high_risk),
                        tool_mode=definition.mode if definition else None,
                        timeout_ms=definition.timeout_ms if definition else None,
                        idempotent=definition.idempotent if definition else None,
                        cache_ttl_seconds=definition.cache_ttl_seconds if definition else None,
                    )
                )
                if definition is not None:
                    for context_key in definition.session_context_output_keys:
                        produced_context_keys.setdefault(context_key, f"tc-{agent}-{index}")
        deduped: list[ToolPlanItem] = []
        seen: set[tuple[str, AgentName]] = set()
        for item in selected_tools:
            key = (item.tool_name, item.assigned_agent)
            if key not in seen:
                seen.add(key)
                deduped.append(item)
        return deduped[: self._settings.max_tool_calls_per_agent * max(len(ordered_agents), 1)]

    def _suggest_tools(
        self,
        agent: AgentName,
        request: RouteRequest,
        text: str,
        tool_candidates: list[str],
    ) -> list[str]:
        if tool_candidates:
            allowed_tools = set(self._allowed_tools(agent))
            return [tool_name for tool_name in tool_candidates if tool_name in allowed_tools]
        if agent == "finance_order_agent":
            tools = []
            if any(token in text for token in ("账单", "扣费", "消费")):
                tools.append("billing.query_statement")
            order_status_requested = any(
                token in text for token in ("订单状态", "订单详情", "订单信息", "订单进度")
            )
            refund_status_requested = "退款" in text and any(
                token in text for token in ("状态", "进度", "详情", "查询")
            )
            invoice_status_requested = any(
                token in text for token in ("发票状态", "开票状态", "发票进度", "开票进度", "发票详情")
            )
            ticket_status_requested = "工单" in text and any(
                token in text for token in ("状态", "进度", "详情", "查询", "跟进", "处理到哪")
            )
            if order_status_requested or refund_status_requested:
                tools.append("order.query_order")
            if invoice_status_requested:
                tools.append("invoice.query_invoice")
            if any(token in text for token in ("发票", "开票")) and not invoice_status_requested:
                tools.append("billing.create_invoice")
            if any(token in text for token in ("退款", "退费")) and not refund_status_requested:
                tools.append("order.create_refund")
            if any(token in text for token in ("工单", "售后")):
                if ticket_status_requested:
                    tools.append("ticket.query_ticket")
                else:
                    tools.append("ticket.reply" if "回复" in text else "ticket.create")
            return tools or self._allowed_tools(agent)[:2]
        if agent == "icp_service_agent":
            tools = []
            verification_requested = any(token in text for token in ("实名", "实名认证", "核身", "主体核验"))
            materials_requested = any(token in text for token in ("材料", "资料", "清单"))
            submit_requested = any(token in text for token in ("提交", "申请", "上线"))
            if verification_requested:
                tools.append("icp.verify_subject")
            if materials_requested or submit_requested or ("备案" in text and not verification_requested):
                tools.append("icp.material_check")
            icp_status_requested = "备案" in text and any(
                token in text for token in ("状态", "进度", "详情", "查询", "审核", "结果")
            )
            if icp_status_requested:
                tools.append("icp.query_application")
            if submit_requested and not icp_status_requested:
                tools.append("icp.submit_application")
            return tools or self._allowed_tools(agent)
        if agent == "ops_marketing_agent":
            tools = []
            poster_requested = any(token in text for token in ("海报", "poster", "视觉", "版式"))
            if any(token in text for token in ("活动", "优惠", "促销", "推广")):
                tools.append("marketing.campaign_lookup")
            if poster_requested:
                tools.append("marketing.poster_brief")
            if any(token in text for token in ("文案", "宣传语", "广告语", "slogan", "标题", "卖点")):
                if (
                    "marketing.campaign_lookup" not in tools
                    and not request.session_context.attributes.get("last_campaign_name")
                ):
                    tools.append("marketing.campaign_lookup")
                tools.append("marketing.generate_copy")
            if any(token in text for token in ("推广链接", "短链", "utm", "落地页", "链接")):
                if (
                    "marketing.campaign_lookup" not in tools
                    and not request.session_context.attributes.get("last_campaign_name")
                ):
                    tools.append("marketing.campaign_lookup")
                tools.append("marketing.generate_promotion_link")
            if poster_requested:
                tools.append("marketing.generate_poster")
            return tools or self._allowed_tools(agent)
        if agent == "deep_research_agent":
            export_requested = any(token in text for token in ("导出", "markdown", "pdf", "下载"))
            has_existing_report = bool(
                request.session_context.attributes.get("research_topic")
                or request.session_context.attributes.get("report_outline")
            )
            if export_requested and has_existing_report:
                tools = []
                if not request.session_context.attributes.get("reference_titles"):
                    tools.append("research.reference_search")
                tools.append("research.export_report")
                return tools
            tools = ["research.generate_report"]
            if any(token in text for token in ("研究", "调研", "对比", "报告", "参考")):
                tools.append("research.reference_search")
            if export_requested:
                if "research.reference_search" not in tools:
                    tools.append("research.reference_search")
                tools.append("research.export_report")
            return tools
        if agent == "product_tech_agent":
            tools = ["product.catalog_lookup"]
            if any(token in text for token in ("部署", "技术", "故障", "配置", "排查")):
                tools.append("support.playbook_search")
            return tools
        return self._allowed_tools(agent)

    def _resolve_payload_requirements(
        self,
        *,
        definition: ToolDefinition | None,
        payload: dict[str, object],
        required_fields: list[str],
        available_context_keys: set[str],
        produced_context_keys: dict[str, str],
        selected_tools: list[ToolPlanItem],
    ) -> tuple[list[str], list[str], list[str]]:
        if definition is None:
            return [], [], []

        missing_payload: list[str] = []
        deferred_payload: list[str] = []
        dependency_ids = self._dedupe_strings(
            item.tool_call_id
            for item in selected_tools
            if item.tool_name in definition.prerequisite_tool_names
        )

        for field in required_fields:
            if not is_missing_tool_value(payload.get(field)):
                continue
            binding_keys = definition.session_context_bindings.get(field, [])
            if any(binding_key in available_context_keys for binding_key in binding_keys):
                continue
            binding_dependency_ids = self._dedupe_strings(
                produced_context_keys[binding_key]
                for binding_key in binding_keys
                if binding_key in produced_context_keys
            )
            if binding_dependency_ids:
                deferred_payload.append(field)
                dependency_ids.extend(binding_dependency_ids)
                continue
            missing_payload.append(field)

        return (
            missing_payload,
            deferred_payload,
            self._dedupe_strings(dependency_ids),
        )

    @staticmethod
    def _tool_readiness(
        *,
        missing_payload: list[str],
        dependency_ids: list[str],
        missing_auth: list[str],
        confirmation_pending: bool,
    ) -> str:
        if missing_payload or missing_auth or confirmation_pending:
            return "needs_user_input"
        if dependency_ids:
            return "ready_after_dependencies"
        return "ready"

    def _order_tools_for_dependencies(self, tool_names: list[str]) -> list[str]:
        deduped = self._dedupe_strings(tool_names)
        if len(deduped) <= 1:
            return deduped

        remaining = list(deduped)
        ordered: list[str] = []
        while remaining:
            progressed = False
            for tool_name in list(remaining):
                definition = self._tool_definitions().get(tool_name)
                prerequisites = [
                    prerequisite
                    for prerequisite in (definition.prerequisite_tool_names if definition else [])
                    if prerequisite in deduped
                ]
                if all(prerequisite in ordered for prerequisite in prerequisites):
                    ordered.append(tool_name)
                    remaining.remove(tool_name)
                    progressed = True
            if progressed:
                continue
            ordered.extend(remaining)
            break
        return ordered

    @staticmethod
    def _dedupe_strings(values: Iterable[object]) -> list[str]:
        deduped: list[str] = []
        for value in values:
            normalized = str(value).strip()
            if normalized and normalized not in deduped:
                deduped.append(normalized)
        return deduped

    def _build_tool_payload(
        self,
        tool_name: str,
        request: RouteRequest,
        text: str,
        definition: ToolDefinition | None,
    ) -> dict[str, object]:
        raw_query = request.user_query
        base_payload: dict[str, object] = {
            "user_query": request.user_query,
            "conversation_id": request.conversation_id,
        }
        if request.user_profile.account_id:
            base_payload["account_id"] = request.user_profile.account_id
        if request.user_profile.user_id:
            base_payload["user_id"] = request.user_profile.user_id

        if tool_name == "billing.query_statement":
            if any(token in text for token in ("本月", "这个月")):
                base_payload["range"] = "this_month"
            elif any(token in text for token in ("上月", "上个月", "上期")):
                base_payload["range"] = "last_month"
            elif any(token in text for token in ("最近三个月", "近三个月", "过去三个月")):
                base_payload["range"] = "last_3_months"
        elif tool_name == "order.query_order":
            extracted_order_no = self._extract_identifier(raw_query, "order_no")
            extracted_refund_no = self._extract_identifier(raw_query, "refund_no")
            if extracted_order_no is not None:
                base_payload["order_no"] = extracted_order_no
            if extracted_refund_no is not None:
                base_payload["refund_no"] = extracted_refund_no
        elif tool_name == "billing.create_invoice":
            extracted_invoice_no = self._extract_identifier(raw_query, "invoice_no")
            if extracted_invoice_no is not None:
                base_payload["invoice_no"] = extracted_invoice_no
        elif tool_name == "invoice.query_invoice":
            extracted_invoice_no = self._extract_identifier(raw_query, "invoice_no")
            if extracted_invoice_no is not None:
                base_payload["invoice_no"] = extracted_invoice_no
        elif tool_name == "order.create_refund":
            extracted_order_no = self._extract_identifier(raw_query, "order_no")
            if extracted_order_no is not None:
                base_payload["order_no"] = extracted_order_no
        elif tool_name == "ticket.create":
            base_payload.update(
                {
                    "subject": request.user_query,
                    "content": request.user_query,
                    "priority": "high" if "紧急" in text else "medium",
                    "category": "billing" if request.scene == "billing" else "technical_support",
                }
            )
        elif tool_name == "ticket.reply":
            extracted_ticket_no = self._extract_identifier(raw_query, "ticket_no")
            if extracted_ticket_no is not None:
                base_payload["ticket_no"] = extracted_ticket_no
            base_payload["content"] = request.user_query
        elif tool_name == "ticket.query_ticket":
            extracted_ticket_no = self._extract_identifier(raw_query, "ticket_no")
            if extracted_ticket_no is not None:
                base_payload["ticket_no"] = extracted_ticket_no
        elif tool_name == "icp.verify_subject":
            if "个人" in text:
                base_payload["subject_type"] = "personal"
            elif any(token in text for token in ("企业", "公司")):
                base_payload["subject_type"] = "enterprise"
            extracted_certificate_no = self._extract_certificate_no(raw_query)
            extracted_phone = self._extract_phone(raw_query)
            if extracted_certificate_no is not None:
                base_payload["certificate_no"] = extracted_certificate_no
            if extracted_phone is not None:
                base_payload["contact_phone"] = extracted_phone
        elif tool_name == "icp.query_application":
            extracted_application_no = self._extract_identifier(raw_query, "application_no")
            if extracted_application_no is not None:
                base_payload["application_no"] = extracted_application_no
        elif tool_name == "marketing.campaign_lookup":
            base_payload["product"] = "GPU" if "gpu" in text else "云服务"
        elif tool_name == "marketing.poster_brief":
            base_payload["theme"] = request.user_query
            base_payload["cta"] = "立即咨询"
        elif tool_name == "marketing.generate_copy":
            if "微信" in text:
                base_payload["channel"] = "wechat"
            elif "邮件" in text:
                base_payload["channel"] = "email"
            elif "短信" in text:
                base_payload["channel"] = "sms"
            else:
                base_payload["channel"] = "web"
            if "限时" in text or "冲量" in text:
                base_payload["tone"] = "urgent"
            elif "轻松" in text or "亲和" in text:
                base_payload["tone"] = "friendly"
            else:
                base_payload["tone"] = "professional"
        elif tool_name == "marketing.generate_promotion_link":
            if "微信" in text:
                base_payload["channel"] = "wechat"
            elif "邮件" in text:
                base_payload["channel"] = "email"
            elif "短信" in text:
                base_payload["channel"] = "sms"
            else:
                base_payload["channel"] = "web"
        elif tool_name == "marketing.generate_poster":
            if "方图" in text or "方版" in text:
                base_payload["size"] = "square"
            elif "横版" in text:
                base_payload["size"] = "landscape"
            else:
                base_payload["size"] = "portrait"
            if "微信" in text:
                base_payload["channel"] = "wechat"
            elif "邮件" in text:
                base_payload["channel"] = "email"
            elif "短信" in text:
                base_payload["channel"] = "sms"
            else:
                base_payload["channel"] = "web"
        elif tool_name == "research.generate_report":
            base_payload["topic"] = request.user_query
        elif tool_name == "research.reference_search":
            base_payload["topic"] = request.user_query
            base_payload["limit"] = 5
        elif tool_name == "research.export_report":
            base_payload["format"] = "pdf" if "pdf" in text else "markdown"
        base_payload = hydrate_payload_from_session_context(
            base_payload,
            definition,
            request.session_context,
        )
        if tool_name in self._confirmed_tool_names(request):
            base_payload["_confirmed"] = True
        return {key: value for key, value in base_payload.items() if value is not None and value != ""}

    def _extract_identifier(self, query: str, identifier_type: str) -> str | None:
        pattern = self.IDENTIFIER_PATTERNS.get(identifier_type)
        if pattern is None:
            return None
        match = pattern.search(query)
        if match is None:
            return None
        return match.group(1)

    def _extract_certificate_no(self, query: str) -> str | None:
        match = self.CERTIFICATE_NO_PATTERN.search(query)
        if match is None:
            return None
        return match.group(1).upper()

    def _extract_phone(self, query: str) -> str | None:
        match = self.PHONE_PATTERN.search(query)
        if match is None:
            return None
        return match.group(1)

    def _build_checkpoints(
        self,
        requires_retrieval: bool,
        requires_tools: bool,
        needs_human_handoff: bool,
        tool_plan: list[ToolPlanItem],
        request: RouteRequest,
    ) -> list[ExecutionCheckpoint]:
        needs_user_input = (
            any(item.auth_required or item.missing_payload_fields for item in tool_plan)
            or self._has_confirmation_pending(tool_plan, request)
        )
        checkpoints = [
            ExecutionCheckpoint(name="intent-classified", description="完成意图识别与主 agent 路由。", status="completed"),
            ExecutionCheckpoint(name="handoff-planned", description="生成多 agent handoff 计划。", status="completed"),
        ]
        checkpoints.append(
            ExecutionCheckpoint(
                name="retrieve-context",
                description="按需触发知识检索。",
                status="planned" if requires_retrieval else "skipped",
            )
        )
        checkpoints.append(
            ExecutionCheckpoint(
                name="invoke-tools",
                description="按计划调用或预览工具。",
                status="planned" if requires_tools else "skipped",
            )
        )
        checkpoints.append(
            ExecutionCheckpoint(
                name="collect-user-input",
                description="按需补充鉴权上下文或显式确认高风险写操作。",
                status="planned" if needs_user_input else "skipped",
            )
        )
        checkpoints.append(
            ExecutionCheckpoint(
                name="review-answer",
                description="执行统一响应复核与 guard 检查。",
                status="planned",
            )
        )
        checkpoints.append(
            ExecutionCheckpoint(
                name="human-review",
                description="必要时转人工或升级处理。",
                status="planned" if needs_human_handoff else "skipped",
            )
        )
        return checkpoints

    @staticmethod
    def _missing_auth_context(
        definition: ToolDefinition,
        request: RouteRequest,
        *,
        operation: str = "execute",
    ) -> list[str]:
        if operation != "execute":
            return []
        return ToolExecutionContext(
            user_id=request.user_profile.user_id,
            account_id=request.user_profile.account_id,
            roles=request.user_profile.roles,
            permissions=request.user_profile.permissions,
            tenant_id=request.user_profile.tenant_id,
        ).missing_auth(definition.auth_requirements)

    @staticmethod
    def _confirmed_tool_names(request: RouteRequest) -> set[str]:
        confirmed_tool_names = set(request.session_context.confirmed_tool_names)
        extra_confirmed = request.session_context.attributes.get("confirmed_tool_names", [])
        if isinstance(extra_confirmed, str):
            extra_confirmed = [extra_confirmed]
        confirmed_tool_names.update(extra_confirmed)
        return confirmed_tool_names

    def _has_confirmation_pending(
        self,
        tool_plan: list[ToolPlanItem],
        request: RouteRequest,
    ) -> bool:
        confirmed_tool_names = self._confirmed_tool_names(request)
        for item in tool_plan:
            definition = self._tool_definitions().get(item.tool_name)
            if definition is None:
                continue
            if (
                definition.auth_requirements.confirmation_required
                and item.tool_name not in confirmed_tool_names
            ):
                return True
        return False

    def _expand_tool_candidates(self, tool_candidates: list[str]) -> list[str]:
        expanded: list[str] = []
        visiting: set[str] = set()

        def _visit(tool_name: str) -> None:
            normalized = str(tool_name).strip()
            if not normalized or normalized in expanded or normalized in visiting:
                return
            definition = self._tool_definitions().get(normalized)
            if definition is None:
                return
            visiting.add(normalized)
            for prerequisite in definition.prerequisite_tool_names:
                _visit(prerequisite)
            visiting.remove(normalized)
            if normalized not in expanded:
                expanded.append(normalized)

        for tool_name in tool_candidates:
            _visit(str(tool_name))
        return expanded

    def _primary_agent_for_tool_candidates(
        self,
        tool_candidates: list[str],
    ) -> AgentName | None:
        for tool_name in tool_candidates:
            owners = self._tool_owner_agents(tool_name)
            if owners:
                return owners[0]
        return None

    def _tool_owner_agents(self, tool_name: str) -> list[AgentName]:
        owners: list[AgentName] = []
        for agent_name in self._routable_agents():
            if tool_name in self._allowed_tools(agent_name):
                owners.append(agent_name)
        return owners

    def _allowed_tools(self, agent: AgentName) -> list[str]:
        return list(self.AGENT_REGISTRY[agent]["allowed_tools"])

    def _agent_descriptor(self, agent: AgentName) -> AgentDescriptor:
        meta = self.AGENT_REGISTRY[agent]
        override = self._agent_config_store.get(agent)
        return AgentDescriptor(
            name=agent,
            code=str(meta["code"]),
            display_name=str(meta["display_name"]),
            domain=agent.replace("_agent", ""),
            description=str(meta["description"]),
            supported_scenes=list(meta["supported_scenes"]),
            allowed_tools=self._allowed_tools(agent),
            fallback_agent=str(
                override.fallback_agent
                if override and override.fallback_agent is not None
                else meta["fallback_agent"]
            ),
            max_tool_calls=(
                override.max_tool_calls
                if override and override.max_tool_calls is not None
                else self._settings.max_tool_calls_per_agent
            ),
        )

    def _admin_agent_record(self, agent: AgentName) -> AgentAdminRecord:
        descriptor = self._agent_descriptor(agent)
        override = self._agent_config_store.get(agent)
        enabled = override.enabled if override and override.enabled is not None else True
        timeout_seconds = (
            override.timeout_seconds
            if override and override.timeout_seconds is not None
            else self._settings.default_agent_timeout_seconds
        )
        return AgentAdminRecord(
            name=descriptor.name,
            code=descriptor.code,
            display_name=descriptor.display_name,
            domain=descriptor.domain,
            description=descriptor.description,
            supported_scenes=list(descriptor.supported_scenes),
            tool_whitelist=list(descriptor.allowed_tools),
            fallback_agent=descriptor.fallback_agent,
            max_tool_calls=descriptor.max_tool_calls,
            enabled=enabled,
            timeout_seconds=timeout_seconds,
        )

    def _routable_agents(self) -> list[AgentName]:
        enabled_agents = [
            agent
            for agent in self.AGENT_REGISTRY
            if self._admin_agent_record(agent).enabled
        ]
        return enabled_agents or list(self.AGENT_REGISTRY)

    def _resolve_agent_name(self, agent_code: str) -> AgentName:
        normalized = agent_code.strip()
        for agent_name, meta in self.AGENT_REGISTRY.items():
            if normalized in {agent_name, str(meta["code"])}:
                return agent_name
        raise ValueError(f"Unknown agent code: {agent_code}")

    def _normalize_fallback_agent(self, fallback_agent: str) -> str:
        normalized = fallback_agent.strip()
        if normalized == "orchestrator":
            return normalized
        return self._resolve_agent_name(normalized)

    def _agent_code(self, agent: AgentName) -> str:
        return str(self.AGENT_REGISTRY[agent]["code"])

    def _resolve_primary_agent(self, agent: AgentName) -> AgentName | None:
        visited: set[AgentName] = set()
        current = agent
        while True:
            if current in visited:
                return None
            visited.add(current)
            override = self._agent_config_store.get(current)
            enabled = override.enabled if override and override.enabled is not None else True
            if enabled:
                return current
            fallback_agent = (
                override.fallback_agent
                if override and override.fallback_agent is not None
                else self.AGENT_REGISTRY[current]["fallback_agent"]
            )
            if fallback_agent in {None, "orchestrator"}:
                return None
            current = self._resolve_agent_name(str(fallback_agent))

    def _tool_definitions(self) -> dict[str, ToolDefinition]:
        if self._settings.tool_hub_transport == "http":
            if self._remote_tool_definitions is None:
                self._remote_tool_definitions = {
                    definition.name: definition
                    for definition in self._tool_hub_client.list_tool_definitions()
                }
            if self._remote_tool_definitions:
                return self._remote_tool_definitions
        return {
            tool_name: tool.definition
            for tool_name, tool in self._catalog.items()
        }
