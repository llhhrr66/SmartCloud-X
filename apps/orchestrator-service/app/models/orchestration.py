from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from app.core.business_tools_sdk import ToolCompensationAction, ToolUserActionHint
from app.models.common import TraceContext


AgentName = Literal[
    "product_tech_agent",
    "finance_order_agent",
    "icp_service_agent",
    "ops_marketing_agent",
    "deep_research_agent",
]
SceneName = Literal[
    "customer_service",
    "billing",
    "technical_support",
    "icp",
    "marketing",
    "research",
]
ConversationStatus = Literal["active", "running", "archived", "closed", "deleted"]
MessageRole = Literal["user", "assistant", "system"]
MessageType = Literal["user_input", "assistant_response", "event"]
MessageStatus = Literal["running", "completed", "handoff", "need_user_input", "failed", "cancelled"]


class UserProfile(BaseModel):
    user_id: str | None = None
    roles: list[str] = Field(default_factory=lambda: ["user"])
    permissions: list[str] = Field(default_factory=list)
    account_id: str | None = None
    tenant_id: str = "default"
    locale: str = "zh-CN"
    channel: str = "web"
    vip_level: str = "normal"


class UserProfilePatch(BaseModel):
    user_id: str | None = None
    roles: list[str] | None = None
    permissions: list[str] | None = None
    account_id: str | None = None
    tenant_id: str | None = None
    locale: str | None = None
    channel: str | None = None
    vip_level: str | None = None


class SessionContext(BaseModel):
    history_summary: str | None = None
    recent_messages: list[dict[str, Any]] = Field(default_factory=list)
    active_products: list[str] = Field(default_factory=list)
    open_ticket_id: str | None = None
    confirmed_tool_names: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)


class RuntimeConstraints(BaseModel):
    must_cite: bool = False
    allow_handoff: bool = True
    max_tool_calls: int = 5
    disable_tools: bool = False


class IntentSignal(BaseModel):
    label: str
    score: int
    matched_keywords: list[str] = Field(default_factory=list)


class IntentSummary(BaseModel):
    domain: str
    matched_domains: list[str] = Field(default_factory=list)
    signals: list[IntentSignal] = Field(default_factory=list)
    urgency: Literal["low", "medium", "high"] = "medium"
    needs_human_handoff: bool = False
    scene: SceneName = "customer_service"


class RouteRequest(BaseModel):
    user_query: str = Field(min_length=1)
    conversation_id: str
    scene: SceneName = "customer_service"
    user_profile: UserProfile = Field(default_factory=UserProfile)
    session_context: SessionContext = Field(default_factory=SessionContext)
    retrieval_required: bool | None = None
    tool_candidates: list[str] = Field(default_factory=list)
    preferred_agents: list[AgentName] = Field(default_factory=list)
    constraints: RuntimeConstraints = Field(default_factory=RuntimeConstraints)


class AgentTask(BaseModel):
    agent: AgentName
    reason: str
    requires_retrieval: bool = False
    suggested_tools: list[str] = Field(default_factory=list)
    handoff_step_id: str | None = None
    depends_on_tool_call_ids: list[str] = Field(default_factory=list)
    session_context_inputs: list[str] = Field(default_factory=list)
    session_context_outputs: list[str] = Field(default_factory=list)


class AgentDescriptor(BaseModel):
    name: AgentName
    code: str
    display_name: str
    domain: str
    description: str
    version: str = "1.0.0"
    owner: str = "smartcloud-ai-team"
    input_schema_version: str = "1.0"
    output_schema_version: str = "1.0"
    supported_scenes: list[SceneName] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    fallback_agent: str = "orchestrator"
    max_tool_calls: int = 5


class AgentAdminRecord(BaseModel):
    name: AgentName
    code: str
    display_name: str
    domain: str
    description: str
    supported_scenes: list[SceneName] = Field(default_factory=list)
    tool_whitelist: list[str] = Field(default_factory=list)
    fallback_agent: str = "orchestrator"
    max_tool_calls: int = 5
    enabled: bool = True
    timeout_seconds: int = 90


class AgentAdminListResponse(BaseModel):
    items: list[AgentAdminRecord] = Field(default_factory=list)
    total: int = 0


class AgentConfigOverride(BaseModel):
    agent_name: AgentName
    agent_code: str
    enabled: bool | None = None
    max_tool_calls: int | None = None
    fallback_agent: str | None = None
    timeout_seconds: int | None = None
    updated_at: str | None = None


class AgentConfigUpdateRequest(BaseModel):
    enabled: bool | None = None
    max_tool_calls: int | None = Field(default=None, ge=1)
    fallback_agent: str | None = None
    timeout_seconds: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _validate_non_empty(self) -> "AgentConfigUpdateRequest":
        if self.model_dump(exclude_none=True) == {}:
            raise ValueError("At least one agent config field must be provided.")
        return self


class ToolPlanItem(BaseModel):
    tool_call_id: str
    tool_name: str
    assigned_agent: AgentName
    operation: Literal["preview", "execute"] = "preview"
    reason: str
    payload: dict[str, Any] = Field(default_factory=dict)
    required_payload_fields: list[str] = Field(default_factory=list)
    missing_payload_fields: list[str] = Field(default_factory=list)
    deferred_payload_fields: list[str] = Field(default_factory=list)
    missing_payload_hints: dict[str, str] = Field(default_factory=dict)
    depends_on_tool_call_ids: list[str] = Field(default_factory=list)
    session_context_input_keys: list[str] = Field(default_factory=list)
    session_context_output_keys: list[str] = Field(default_factory=list)
    readiness: Literal["ready", "ready_after_dependencies", "needs_user_input"] = "ready"
    auth_required: bool = False
    requires_account_context: bool = False
    required_permissions: list[str] = Field(default_factory=list)
    high_risk: bool = False
    tool_mode: Literal["query", "write"] | None = None
    timeout_ms: int | None = None
    idempotent: bool | None = None
    cache_ttl_seconds: int | None = None


class HandoffStep(BaseModel):
    step_id: str
    order: int
    agent: AgentName
    objective: str
    depends_on: list[str] = Field(default_factory=list)
    requires_retrieval: bool = False
    tool_names: list[str] = Field(default_factory=list)
    depends_on_tool_call_ids: list[str] = Field(default_factory=list)
    session_context_inputs: list[str] = Field(default_factory=list)
    session_context_outputs: list[str] = Field(default_factory=list)
    exit_criteria: str | None = None


class ExecutionCheckpoint(BaseModel):
    name: str
    description: str
    status: Literal["planned", "pending", "completed", "skipped", "failed"] = "planned"


class RouteDecision(BaseModel):
    primary_agent: AgentName
    supporting_agents: list[AgentName] = Field(default_factory=list)
    requires_retrieval: bool = False
    requires_tools: bool = False
    needs_human_handoff: bool = False
    intent: IntentSummary
    tasks: list[AgentTask] = Field(default_factory=list)
    handoff_plan: list[HandoffStep] = Field(default_factory=list)
    tool_plan: list[ToolPlanItem] = Field(default_factory=list)
    checkpoints: list[ExecutionCheckpoint] = Field(default_factory=list)
    summary: str


class MessageRequest(BaseModel):
    user_query: str = Field(min_length=1)
    message_id: str | None = None
    scene: SceneName = "customer_service"
    user_profile: UserProfile = Field(default_factory=UserProfile)
    session_context: SessionContext = Field(default_factory=SessionContext)
    retrieval_context: list[str] = Field(default_factory=list)
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    tool_candidates: list[str] = Field(default_factory=list)
    constraints: RuntimeConstraints = Field(default_factory=RuntimeConstraints)
    retrieval_required: bool | None = None
    preferred_agents: list[AgentName] = Field(default_factory=list)
    use_history: bool = True
    history_limit: int | None = None
    client_meta: dict[str, Any] = Field(default_factory=dict)
    trace: TraceContext | None = None


class ToolInvocation(BaseModel):
    tool_name: str
    tool_call_id: str
    operation: str
    status: str
    payload: dict[str, Any] = Field(default_factory=dict)
    summary: str | None = None
    citations: list[str] = Field(default_factory=list)
    auth_required: bool = False
    success: bool | None = None
    code: int | None = None
    retryable: bool = False
    latency_ms: int | None = None
    compensation: ToolCompensationAction | None = None
    provider: str | None = None
    audit_tags: list[str] = Field(default_factory=list)
    error_detail: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None
    session_context_patch: dict[str, Any] = Field(default_factory=dict)
    user_action_hint: ToolUserActionHint | None = None


class PendingUserAction(BaseModel):
    tool_name: str
    tool_call_id: str
    agent: AgentName | None = None
    action: str
    message: str
    missing_fields: list[str] = Field(default_factory=list)
    missing_payload_hints: dict[str, str] = Field(default_factory=dict)
    missing_auth_context: list[str] = Field(default_factory=list)
    required_permissions: list[str] = Field(default_factory=list)
    requires_account_context: bool = False
    confirmation_required: bool = False
    session_context_bindings: dict[str, list[str]] = Field(default_factory=dict)
    user_profile_bindings: dict[str, list[str]] = Field(default_factory=dict)
    confirm_tool_names: list[str] = Field(default_factory=list)


class ToolContextItem(BaseModel):
    tool_name: str
    tool_call_id: str
    status: str
    summary: str | None = None
    provider: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    patch_keys: list[str] = Field(default_factory=list)


class RetrievalSource(BaseModel):
    source_id: str
    source_type: str = "knowledge_base"
    title: str
    doc_id: str | None = None
    chunk_id: str | None = None
    score: float | None = None
    uri: str | None = None
    snippet: str | None = None
    backend_used: str | None = None
    domain: str | None = None


class RetrievalResult(BaseModel):
    query: str
    rewritten_query: str
    degraded: bool = False
    degradation_note: str | None = None
    backend_used: str
    sources: list[RetrievalSource] = Field(default_factory=list)
    raw_meta: dict[str, Any] = Field(default_factory=dict)


class FaqDocumentRef(BaseModel):
    docId: str
    title: str


class FaqMetadata(BaseModel):
    """Structured metadata for L1 FAQ cache hits.

    When an FAQ entry matches, this carries category, prerequisites,
    document references (linkable to knowledge-service document viewer),
    and related topics so the frontend can render a rich structured answer.
    """
    category: str | None = None
    prerequisites: list[str] = Field(default_factory=list)
    documentRefs: list[FaqDocumentRef] = Field(default_factory=list)
    relatedTopics: list[str] = Field(default_factory=list)
    matchReason: str | None = None
    tokenSaved: int = 0


class PermissionCheckRecord(BaseModel):
    """Record of a tool permission check for audit purposes."""
    tool_name: str
    agent: AgentName
    permission: Literal["allow", "ask", "deny"]
    effective_operation: Literal["preview", "execute"] = "preview"
    confirmed: bool = False
    reason: str = ""


class AgentExecutionResult(BaseModel):
    agent: AgentName
    status: Literal["success", "handoff", "need_user_input", "failed"] = "success"
    reasoning_summary: str
    tool_calls: list[ToolInvocation] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    retrieval_result: RetrievalResult | None = None
    confidence: float = 0.5
    final_answer: str | None = None
    handoff_received_from: AgentName | None = None
    next_agent: AgentName | None = None
    action_required: str | None = None
    risk_flags: list[str] = Field(default_factory=list)
    trace_tags: list[str] = Field(default_factory=list)
    handoff_reason: str | None = None
    handoff_payload: dict[str, Any] = Field(default_factory=dict)
    faq_metadata: FaqMetadata | None = None
    # Token usage from LLM calls
    prompt_tokens: int = 0
    completion_tokens: int = 0
    # Permission check audit trail
    permission_checks: list[PermissionCheckRecord] = Field(default_factory=list)


class PendingAgentHandoff(BaseModel):
    route: RouteDecision
    request_snapshot: MessageRequest
    source_user_message_id: str
    next_task_index: int = Field(ge=0)
    completed_executions: list[AgentExecutionResult] = Field(default_factory=list)
    handoff_from: AgentName | None = None


class AgentRouteRecord(BaseModel):
    step_id: str
    order: int
    agent: AgentName
    objective: str
    status: str = "planned"
    handoff_received_from: AgentName | None = None
    handoff_to: AgentName | None = None
    handoff_reason: str | None = None
    action_required: str | None = None
    tool_names: list[str] = Field(default_factory=list)
    tool_call_ids: list[str] = Field(default_factory=list)
    tool_statuses: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    depends_on_tool_call_ids: list[str] = Field(default_factory=list)
    session_context_inputs: list[str] = Field(default_factory=list)
    session_context_outputs: list[str] = Field(default_factory=list)
    context_highlights: dict[str, Any] = Field(default_factory=dict)


class SagaCompensationStep(BaseModel):
    saga_id: str
    step_id: str
    tool_name: str
    compensation: ToolCompensationAction
    status: Literal["armed", "completed", "failed"] = "armed"


class ExecutionEvent(BaseModel):
    sequence: int
    event: Literal[
        "route_selected",
        "checkpoint_updated",
        "tool_call",
        "tool_result",
        "agent_result",
        "review_result",
        "compensation_result",
        "state_persisted",
    ]
    message: str
    agent: AgentName | None = None
    tool_name: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class ResponseReviewIssue(BaseModel):
    code: str
    severity: Literal["warning", "error"] = "warning"
    message: str


class ResponseReview(BaseModel):
    status: Literal["approved", "warning", "blocked", "skipped"] = "approved"
    summary: str = "Response review approved."
    issues: list[ResponseReviewIssue] = Field(default_factory=list)
    requires_escalation: bool = False


class SessionStateSnapshot(BaseModel):
    conversation_id: str
    primary_agent: AgentName
    current_agent: AgentName | None = None
    version: int = 1
    session_context: SessionContext = Field(default_factory=SessionContext)
    agent_routes: list[AgentRouteRecord] = Field(default_factory=list)
    checkpoints: list[ExecutionCheckpoint] = Field(default_factory=list)
    tool_results: list[ToolInvocation] = Field(default_factory=list)
    tool_context: list[ToolContextItem] = Field(default_factory=list)
    compensation_stack: list[SagaCompensationStep] = Field(default_factory=list)
    events: list[ExecutionEvent] = Field(default_factory=list)
    pending_actions: list[str] = Field(default_factory=list)
    pending_user_actions: list[PendingUserAction] = Field(default_factory=list)
    pending_agent_handoff: PendingAgentHandoff | None = None
    final_response_summary: str | None = None
    review: ResponseReview | None = None
    trace: TraceContext | None = None


class SessionCreateRequest(BaseModel):
    scene: SceneName = "customer_service"
    title: str | None = None
    initial_context: SessionContext = Field(default_factory=SessionContext)


class SessionListResponse(BaseModel):
    items: list["ConversationRecord"] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20


class SessionUpdateRequest(BaseModel):
    title: str = Field(min_length=1)


class SessionDeleteResponse(BaseModel):
    conversation_id: str
    status: Literal["deleted"] = "deleted"


class SessionRetryRequest(BaseModel):
    message_id: str
    override_input: str | None = None


class SessionCancelRequest(BaseModel):
    message_id: str | None = None


class SessionCancelResponse(BaseModel):
    conversation_id: str
    message_id: str
    status: Literal["cancelled"] = "cancelled"


class SessionRollbackResponse(BaseModel):
    conversation_id: str
    status: Literal["completed", "failed", "partial"] = "completed"
    restored: bool = True
    summary: str | None = None
    compensated_steps: list["CompensationExecutionRecord"] = Field(default_factory=list)
    state_snapshot: Optional["SessionStateSnapshot"] = None


class ConversationRecord(BaseModel):
    conversation_id: str
    scene: SceneName
    status: ConversationStatus = "active"
    title: str | None = None
    current_agent: AgentName | None = None
    summary: str | None = None
    created_at: str
    updated_at: str
    last_message_at: str | None = None
    initial_context: SessionContext = Field(default_factory=SessionContext)
    pending_actions: list[str] = Field(default_factory=list)
    total_messages: int = 0


class ChatMessageRecord(BaseModel):
    conversation_id: str
    message_id: str
    role: MessageRole
    message_type: MessageType = "assistant_response"
    status: MessageStatus = "completed"
    content: str
    agent_name: AgentName | None = None
    citations: list[str] = Field(default_factory=list)
    finish_reason: str | None = None
    created_at: str
    updated_at: str
    request_id: str | None = None
    trace_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionMessagesPage(BaseModel):
    items: list[ChatMessageRecord] = Field(default_factory=list)
    next_cursor: str | None = None
    has_more: bool = False


class StreamEventRecord(BaseModel):
    event_id: str
    message_id: str | None = None
    sequence: int
    event: Literal[
        "meta",
        "reasoning",
        "retrieval",
        "tool_call",
        "tool_result",
        "delta",
        "citation",
        "done",
        "message.error",
    ]
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: str
class MessageEventPage(BaseModel):
    conversation_id: str
    message_id: str
    items: list[StreamEventRecord] = Field(default_factory=list)
    next_event_id: str | None = None
    has_more: bool = False


StreamEventPage = MessageEventPage


class ChatUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class OrchestratorResponse(BaseModel):
    conversation_id: str | None = None
    route: RouteDecision
    executions: list[AgentExecutionResult] = Field(default_factory=list)
    final_response_summary: str | None = None
    next_action: str = "respond-with-agent-summary"
    pending_actions: list[str] = Field(default_factory=list)
    pending_user_actions: list[PendingUserAction] = Field(default_factory=list)
    state_snapshot: SessionStateSnapshot | None = None
    review: ResponseReview | None = None
    trace: TraceContext | None = None
    # Compaction summary from auto-compact, for session context derivation
    compaction_summary: str | None = None


class ChatCompletionRequest(BaseModel):
    conversation_id: str | None = None
    message_id: str | None = None
    user_input: str = Field(min_length=1)
    scene: SceneName | None = None
    stream: bool = False
    context: dict[str, Any] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)
    context_control: dict[str, Any] = Field(default_factory=dict)
    user_profile: UserProfile = Field(default_factory=UserProfile)
    session_context: SessionContext = Field(default_factory=SessionContext)
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    tool_candidates: list[str] = Field(default_factory=list)
    confirmed_tool_names: list[str] = Field(default_factory=list)
    auth_context: dict[str, Any] = Field(default_factory=dict)
    history: list[dict[str, Any]] = Field(default_factory=list)
    constraints: RuntimeConstraints = Field(default_factory=RuntimeConstraints)
    client_meta: dict[str, Any] = Field(default_factory=dict)
    trace: TraceContext | None = None


class ChatCompletionResponse(BaseModel):
    conversation_id: str
    message_id: str
    status: str
    answer: str
    citations: list[str] = Field(default_factory=list)
    tool_calls: list[ToolInvocation] = Field(default_factory=list)
    pending_actions: list[str] = Field(default_factory=list)
    pending_user_actions: list[PendingUserAction] = Field(default_factory=list)
    usage: ChatUsage = Field(default_factory=ChatUsage)
    finish_reason: str | None = None
    response: dict[str, Any] | None = None
    review: ResponseReview | None = None
    next_action: str = "respond-with-agent-summary"
    final_response_summary: str | None = None
    executions: list[AgentExecutionResult] = Field(default_factory=list)
    state_snapshot: SessionStateSnapshot | None = None
    route: Optional[RouteDecision] = None


class InternalChatUser(BaseModel):
    user_id: str | None = None
    tenant_id: str = "default"
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    account_id: str | None = None


class InternalChatRequestPayload(BaseModel):
    conversation_id: str
    message_id: str | None = None
    user_input: str = Field(min_length=1)
    scene: SceneName = "customer_service"
    stream: bool = False
    session_context: SessionContext = Field(default_factory=SessionContext)
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    tool_candidates: list[str] = Field(default_factory=list)
    retrieval_required: bool | None = None


class InternalChatRequest(BaseModel):
    request_id: str
    trace_id: str
    user: InternalChatUser
    chat_request: InternalChatRequestPayload


class SessionContinueRequest(BaseModel):
    message_id: str | None = None
    user_input: str | None = None
    field_values: dict[str, object] = Field(default_factory=dict)
    session_context_patch: dict[str, Any] = Field(default_factory=dict)
    user_profile_patch: UserProfilePatch = Field(default_factory=UserProfilePatch)
    confirm_tool_names: list[str] = Field(default_factory=list)


class InternalChatResponse(BaseModel):
    conversation_id: str
    message_id: str
    status: str
    agent_name: AgentName
    route: RouteDecision
    executions: list[AgentExecutionResult] = Field(default_factory=list)
    final_answer: str | None = None
    citations: list[str] = Field(default_factory=list)
    tool_calls: list[ToolInvocation] = Field(default_factory=list)
    next_agent: AgentName | None = None
    pending_actions: list[str] = Field(default_factory=list)
    pending_user_actions: list[PendingUserAction] = Field(default_factory=list)
    state_snapshot: SessionStateSnapshot | None = None
    review: ResponseReview | None = None
    trace: TraceContext | None = None
    next_action: str = "respond-with-agent-summary"
    final_response_summary: str | None = None


class CompensationExecutionRecord(BaseModel):
    step_id: str
    tool_name: str
    action_name: str
    status: Literal["completed", "failed"] = "completed"
    success: bool = True
    message: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    provider: str | None = None
    code: int | None = None
    retryable: bool = False
    latency_ms: int | None = None
    error_detail: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None
