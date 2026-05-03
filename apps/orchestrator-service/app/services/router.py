from __future__ import annotations

from app.core.business_tools_sdk import ToolDefinition, build_catalog
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
from app.services.tool_hub_client import ToolHubClient, ToolHubDiscoveryUnavailableError

from .agent_registry import (
    AGENT_KEYWORDS,
    AGENT_REGISTRY,
    SCENE_TO_AGENT,
    agent_code_for,
    allowed_tools_for,
    resolve_agent_name,
    step_objective,
)
from .route_text_signals import RouteTextSignals, build_signals
from .tool_plan_builder import (
    build_tool_plan,
    expand_tool_candidates,
    has_confirmation_pending,
)


class AgentRouter:
    """Keyword-based supervisor baseline router with spec-aligned metadata.

    Static data lives in ``agent_registry``; text classification in
    ``route_text_signals``; tool payload/suggestion/plan composition in
    ``tool_payload_builder``, ``tool_suggestion``, and ``tool_plan_builder``.
    This class wires those modules together with the agent config store and
    tool-hub catalog to produce ``RouteDecision`` instances.
    """

    # Re-exported for backward compatibility — tests reach in via these
    # class attributes.
    AGENT_KEYWORDS = AGENT_KEYWORDS
    AGENT_REGISTRY = AGENT_REGISTRY
    SCENE_TO_AGENT = SCENE_TO_AGENT

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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def route(self, request: RouteRequest) -> RouteDecision:
        text = request.user_query.lower()
        explicit_tool_candidates = expand_tool_candidates(request.tool_candidates, self._tool_definitions())
        signals = build_signals(text)
        primary = self._select_primary_agent(
            signals, request.preferred_agents, request.scene, explicit_tool_candidates, text=text
        )
        if self._marketing_needs_product_grounding(primary, text, request):
            resolved_primary = self._resolve_primary_agent("product_tech_agent")
            if resolved_primary is not None:
                primary = resolved_primary
        supporting_agents = self._select_supporting_agents(
            primary, signals, text, request, explicit_tool_candidates
        )
        requires_retrieval = self._determine_retrieval(request, text, primary)
        intent = IntentSummary(
            domain=primary.replace("_agent", ""),
            matched_domains=[signal.label for signal in signals if signal.score > 0],
            signals=signals,
            urgency=RouteTextSignals.determine_urgency(text),
            needs_human_handoff=any(
                token in request.user_query
                for token in ("人工", "转人工", "投诉", "升级", "紧急", "电话联系")
            ),
            scene=RouteTextSignals.infer_scene(primary, request.scene),
        )
        ordered_agents = [primary, *supporting_agents]
        if self._settings.tool_call_enabled and self._settings.llm_ready():
            tool_plan = []
            requires_tools = True
        else:
            tool_plan = build_tool_plan(
                request,
                primary,
                ordered_agents,
                text,
                explicit_tool_candidates,
                tool_definitions=self._tool_definitions(),
                agent_descriptor=self._agent_descriptor,
                max_tool_calls_per_agent=self._settings.max_tool_calls_per_agent,
            )
            requires_tools = bool(tool_plan)
        if request.constraints.disable_tools and tool_plan:
            requires_tools = True
            tool_plan = []
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
            requires_retrieval, requires_tools, intent.needs_human_handoff, tool_plan, request
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
        return [self._agent_descriptor(agent) for agent in self._routable_agents()]

    def available_admin_agents(
        self,
        *,
        scene: SceneName | None = None,
        status: str | None = None,
    ) -> list[AgentAdminRecord]:
        normalized_status = status.strip().lower() if status else None
        items = [self._admin_agent_record(agent) for agent in AGENT_REGISTRY]
        if scene is not None:
            items = [item for item in items if scene in item.supported_scenes]
        if normalized_status == "enabled":
            items = [item for item in items if item.enabled]
        elif normalized_status == "disabled":
            items = [item for item in items if not item.enabled]
        return items

    def get_admin_agent(self, agent_code: str) -> AgentAdminRecord:
        return self._admin_agent_record(resolve_agent_name(agent_code))

    def update_agent_config(
        self,
        agent_code: str,
        payload: AgentConfigUpdateRequest,
    ) -> AgentAdminRecord:
        agent_name = resolve_agent_name(agent_code)
        values = payload.model_dump(exclude_unset=True)
        fallback_agent = values.get("fallback_agent")
        if fallback_agent is not None:
            values["fallback_agent"] = self._normalize_fallback_agent(fallback_agent)
        self._agent_config_store.upsert(
            agent_name=agent_name, agent_code=agent_code_for(agent_name), values=values
        )
        return self._admin_agent_record(agent_name)

    # ------------------------------------------------------------------
    # Agent selection
    # ------------------------------------------------------------------

    def _select_primary_agent(
        self,
        signals: list[IntentSignal],
        preferred_agents: list[AgentName],
        scene: SceneName,
        tool_candidates: list[str],
        text: str = "",
    ) -> AgentName:
        ranked = sorted(
            [signal for signal in signals if signal.label in AGENT_REGISTRY],
            key=lambda signal: (signal.score, -list(AGENT_KEYWORDS.keys()).index(signal.label)),
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
        # 实例 ID + 费用查询词 → finance_order_agent（覆盖 "gpu" 等 product 关键词）
        from .route_text_signals import RouteTextSignals
        if (
            text
            and RouteTextSignals.extract_identifier(text, "instance_id") is not None
            and any(token in text for token in ("费用", "花费", "成本", "消费", "账单", "多少钱", "花了", "收费", "价格"))
        ):
            resolved_finance = self._resolve_primary_agent("finance_order_agent")
            if resolved_finance is not None:
                return resolved_finance
        scene_agent = SCENE_TO_AGENT.get(scene, "product_tech_agent")
        scene_signal = next((signal for signal in ranked if signal.label == scene_agent), None)
        if (
            scene != "customer_service"
            and scene_signal is not None
            and scene_signal.score > 0
            and ranked
            and scene_signal.score == ranked[0].score
        ):
            resolved_scene_agent = self._resolve_primary_agent(scene_agent)
            if resolved_scene_agent is not None:
                return resolved_scene_agent
        for signal in ranked:
            if signal.score <= 0:
                continue
            resolved = self._resolve_primary_agent(signal.label)  # type: ignore[arg-type]
            if resolved is not None:
                return resolved
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
            and any(token in text for token in ("活动", "优惠", "促销", "海报", "文案", "推广", "宣传", "链接"))
        ):
            supporting.append("ops_marketing_agent")
        if (
            primary == "deep_research_agent"
            and "product_tech_agent" in routable_agents
            and any(token in text for token in ("gpu", "云服务器", "部署", "技术"))
        ):
            supporting.append("product_tech_agent")
        deduped: list[AgentName] = []
        for agent in supporting:
            if agent not in deduped:
                deduped.append(agent)
        if primary == "ops_marketing_agent" and any(
            token in text for token in ("推广链接", "短链", "海报", "文案", "宣传")
        ) and not self._marketing_needs_product_grounding(primary, text, request):
            deduped = [agent for agent in deduped if agent != "product_tech_agent"]
        return deduped[: max(self._settings.max_handoff_steps - 1, 0)]

    def _determine_retrieval(self, request: RouteRequest, text: str, primary: AgentName) -> bool:
        if request.constraints.must_cite:
            return True
        if request.retrieval_required is not None:
            return request.retrieval_required
        retrieval_keywords = ("文档", "教程", "faq", "方案", "how", "最佳实践", "排查", "研究", "对比")
        return primary in {"deep_research_agent", "product_tech_agent"} and any(
            token in text for token in retrieval_keywords
        )

    def _marketing_needs_product_grounding(
        self,
        primary: AgentName,
        text: str,
        request: RouteRequest,
    ) -> bool:
        if primary != "ops_marketing_agent":
            return False
        attributes = request.session_context.attributes
        if any(
            attributes.get(key)
            for key in (
                "recommended_instance_summary",
                "recommended_instance_type",
                "recommended_gpu_model",
                "last_marketing_product_summary",
            )
        ):
            return False
        has_marketing_goal = any(
            token in text for token in ("文案", "海报", "推广", "宣传", "活动", "优惠", "促销", "链接")
        )
        has_product_signal = (
            any(token in text for token in ("实例", "算力", "部署", "机型", "规格", "推荐", "大模型"))
            or ("gpu" in text and any(token in text for token in ("实例", "部署", "规格", "推荐", "大模型", "算力")))
        )
        return has_marketing_goal and has_product_signal

    # ------------------------------------------------------------------
    # Handoff plan + checkpoints
    # ------------------------------------------------------------------

    def _build_handoff_plan(
        self,
        primary: AgentName,
        supporting_agents: list[AgentName],
        requires_retrieval: bool,
        tool_plan: list[ToolPlanItem],
    ) -> list[HandoffStep]:
        from .tool_plan_builder import _dedupe_strings  # type: ignore[attr-defined]

        ordered_agents = [primary, *supporting_agents][: self._settings.max_handoff_steps]
        handoff_plan: list[HandoffStep] = []
        previous_step_id: str | None = None
        for index, agent in enumerate(ordered_agents, start=1):
            step_id = f"step-{index}-{agent}"
            step_items = [item for item in tool_plan if item.assigned_agent == agent]
            step_tool_names = [item.tool_name for item in step_items]
            # When LLM tool-calling is active, tool_plan is empty but tasks
            # need suggested_tools for the review guard — use full allowed list.
            if not step_tool_names and self._settings.tool_call_enabled and self._settings.llm_ready():
                step_tool_names = allowed_tools_for(agent)
            handoff_plan.append(
                HandoffStep(
                    step_id=step_id,
                    order=index,
                    agent=agent,
                    objective=step_objective(agent, index == 1),
                    depends_on=[previous_step_id] if previous_step_id else [],
                    requires_retrieval=requires_retrieval if index == 1 else False,
                    tool_names=step_tool_names,
                    depends_on_tool_call_ids=_dedupe_strings(
                        dependency_id
                        for item in step_items
                        for dependency_id in item.depends_on_tool_call_ids
                    ),
                    session_context_inputs=_dedupe_strings(
                        context_key
                        for item in step_items
                        for context_key in item.session_context_input_keys
                    ),
                    session_context_outputs=_dedupe_strings(
                        context_key
                        for item in step_items
                        for context_key in item.session_context_output_keys
                    ),
                    exit_criteria="产出结构化摘要并交回 supervisor 聚合。",
                )
            )
            previous_step_id = step_id
        return handoff_plan

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
            or has_confirmation_pending(tool_plan, request, self._tool_definitions())
        )
        return [
            ExecutionCheckpoint(name="intent-classified", description="完成意图识别与主 agent 路由。", status="completed"),
            ExecutionCheckpoint(name="handoff-planned", description="生成多 agent handoff 计划。", status="completed"),
            ExecutionCheckpoint(
                name="retrieve-context",
                description="按需触发知识检索。",
                status="planned" if requires_retrieval else "skipped",
            ),
            ExecutionCheckpoint(
                name="invoke-tools",
                description="按计划调用或预览工具。",
                status="planned" if requires_tools else "skipped",
            ),
            ExecutionCheckpoint(
                name="collect-user-input",
                description="按需补充鉴权上下文或显式确认高风险写操作。",
                status="planned" if needs_user_input else "skipped",
            ),
            ExecutionCheckpoint(
                name="review-answer",
                description="执行统一响应复核与 guard 检查。",
                status="planned",
            ),
            ExecutionCheckpoint(
                name="human-review",
                description="必要时转人工或升级处理。",
                status="planned" if needs_human_handoff else "skipped",
            ),
        ]

    # ------------------------------------------------------------------
    # Tool / agent lookups
    # ------------------------------------------------------------------

    def _primary_agent_for_tool_candidates(self, tool_candidates: list[str]) -> AgentName | None:
        for tool_name in tool_candidates:
            owners = self._tool_owner_agents(tool_name)
            if owners:
                return owners[0]
        return None

    def _tool_owner_agents(self, tool_name: str) -> list[AgentName]:
        return [
            agent_name
            for agent_name in self._routable_agents()
            if tool_name in allowed_tools_for(agent_name)
        ]

    def _agent_descriptor(self, agent: AgentName) -> AgentDescriptor:
        meta = AGENT_REGISTRY[agent]
        override = self._agent_config_store.get(agent)
        return AgentDescriptor(
            name=agent,
            code=str(meta["code"]),
            display_name=str(meta["display_name"]),
            domain=agent.replace("_agent", ""),
            description=str(meta["description"]),
            supported_scenes=list(meta["supported_scenes"]),
            allowed_tools=allowed_tools_for(agent),
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
            agent for agent in AGENT_REGISTRY if self._admin_agent_record(agent).enabled
        ]
        return enabled_agents or list(AGENT_REGISTRY)

    def _normalize_fallback_agent(self, fallback_agent: str) -> str:
        normalized = fallback_agent.strip()
        if normalized == "orchestrator":
            return normalized
        return resolve_agent_name(normalized)

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
                else AGENT_REGISTRY[current]["fallback_agent"]
            )
            if fallback_agent in {None, "orchestrator"}:
                return None
            current = resolve_agent_name(str(fallback_agent))

    def _tool_definitions(self) -> dict[str, ToolDefinition]:
        if self._settings.tool_hub_transport == "http":
            if self._remote_tool_definitions is None:
                try:
                    remote_tool_definitions = {
                        definition.name: definition
                        for definition in self._tool_hub_client.list_tool_definitions()
                    }
                except ToolHubDiscoveryUnavailableError:
                    return {}
                self._remote_tool_definitions = remote_tool_definitions
            return self._remote_tool_definitions
        return {tool_name: tool.definition for tool_name, tool in self._catalog.items()}
