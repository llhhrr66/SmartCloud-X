import type {
  AuthUserProfile,
  ChatMessageRecord,
  ConversationRecord,
  ForgotPasswordResponseData,
  LoginResponseData,
  MarketingCopyResult as ContractMarketingCopyResult,
  PosterTask as ContractPosterTask,
  RefreshTokenResponseData,
  ResearchTask as ContractResearchTask,
  SendCodeResponseData,
  ToolInvocation
} from '@smartcloud-x/common-schemas';
import { asRecord, getNumber, getOptionalNumber, getOptionalString, getString, getStringArray, isRecord } from '../core/utils';
import {
  classifyApiError,
  extractApiErrorDetails,
  extractEnvelopeCode,
  extractEnvelopeMessage,
  extractUserActionHintAction,
  type RawSseEvent
} from '../core/envelope';
import type {
  AuthSession,
  ChangePasswordRequest,
  ChatCompletionRequest,
  ChatCompletionResponse,
  ChatActionRequiredPayload,
  ChatAttachment,
  ChatMessage,
  ChatStreamEvent,
  Citation,
  ConversationSummary,
  CreatePosterTaskRequest,
  CreateResearchTaskRequest,
  CurrentUser,
  ForgotPasswordChallenge,
  ForgotPasswordChallengeRequest,
  LoginRequest,
  MarketingCampaign,
  MarketingCopyRequest,
  MarketingCopyResult,
  PosterTask,
  ResetPasswordRequest,
  ResearchTask,
  SendCodeRequest,
  SendCodeResponse,
  SessionCancelResult,
  SessionCreateRequest,
  SessionListQuery,
  SessionRetryResult,
  ToolCallRecord,
  UserProfileUpdateRequest
} from './types';

function nowIso(): string {
  return new Date().toISOString();
}

function buildExpiresAt(expiresIn: number): string {
  return new Date(Date.now() + expiresIn * 1000).toISOString();
}

function buildClientGeneratedId(prefix: string): string {
  const generated =
    typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;

  return `${prefix}-${generated}`;
}

function normalizeMessageType(value: unknown): ChatMessage['messageType'] {
  switch (value) {
    case 'user_input':
    case 'text':
      return 'text';
    case 'assistant_response':
    case 'markdown':
      return 'markdown';
    case 'image':
    case 'file':
    case 'event':
      return value;
    default:
      return 'markdown';
  }
}

function normalizeMessageStatus(value: unknown): ChatMessage['status'] {
  switch (value) {
    case 'running':
    case 'completed':
    case 'handoff':
    case 'need_user_input':
    case 'failed':
    case 'cancelled':
    case 'error':
      return value;
    default:
      return 'completed';
  }
}

function normalizeAssistantContent(value: unknown): string {
  if (typeof value !== 'string') {
    return '';
  }

  const text = value.trim();
  if (!text) {
    return '';
  }

  try {
    const parsed = JSON.parse(text) as Record<string, unknown>;
    for (const key of ['final_answer', 'answer', 'finalAnswer']) {
      const content = parsed[key];
      if (typeof content === 'string' && content.trim()) {
        return content.trim();
      }
    }
  } catch {
    return value;
  }

  return value;
}

function normalizeToolStatus(value: unknown): ToolCallRecord['status'] {
  switch (value) {
    case 'running':
    case 'success':
    case 'failed':
    case 'timeout':
    case 'cancelled':
      return value;
    default:
      return 'pending';
  }
}

function buildToolDataPreview(record: Record<string, unknown>): Record<string, unknown> | undefined {
  if (isRecord(record.output_summary)) {
    return record.output_summary;
  }

  if (typeof record.output_summary === 'string') {
    return {
      summary: record.output_summary
    };
  }

  if (typeof record.input_summary === 'string') {
    return {
      summary: record.input_summary
    };
  }

  return undefined;
}

function mapUsage(record: Record<string, unknown>): {
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
} {
  return {
    promptTokens: getNumber(record, ['prompt_tokens', 'promptTokens']),
    completionTokens: getNumber(record, ['completion_tokens', 'completionTokens']),
    totalTokens: getNumber(record, ['total_tokens', 'totalTokens'])
  };
}

export function mapCurrentUser(payload: Record<string, unknown> | AuthUserProfile): CurrentUser {
  const record = asRecord(payload);
  return {
    userId: getString(record, ['user_id', 'userId'], 'u_unknown'),
    tenantId: getString(record, ['tenant_id', 'tenantId'], 'default'),
    name: getString(record, ['name'], 'SmartCloud 用户'),
    email: getString(record, ['email']),
    mobile: getString(record, ['mobile']),
    avatarUrl: getOptionalString(record, ['avatar_url', 'avatarUrl']),
    locale: getString(record, ['locale'], 'zh-CN'),
    timeZone: getString(record, ['time_zone', 'timeZone'], 'Asia/Shanghai'),
    permissions: getStringArray(record.permissions)
  };
}

export function buildAuthSessionFromLoginResponse(
  payload: Record<string, unknown> | LoginResponseData
): AuthSession {
  const record = asRecord(payload);
  const expiresIn = getNumber(record, ['expires_in', 'expiresIn'], 7200);

  return {
    accessToken: getString(record, ['access_token', 'accessToken']),
    refreshToken: getString(record, ['refresh_token', 'refreshToken']),
    expiresIn,
    expiresAt: buildExpiresAt(expiresIn),
    user: mapCurrentUser(asRecord(record.user))
  };
}

export function buildAuthSessionFromRefreshResponse(
  payload: Record<string, unknown> | RefreshTokenResponseData,
  fallback: AuthSession
): AuthSession {
  const record = asRecord(payload);
  const expiresIn = getNumber(record, ['expires_in', 'expiresIn'], fallback.expiresIn);
  const nextUser = isRecord(record.user) ? mapCurrentUser(record.user) : fallback.user;

  return {
    accessToken: getString(record, ['access_token', 'accessToken'], fallback.accessToken),
    refreshToken: getString(record, ['refresh_token', 'refreshToken'], fallback.refreshToken),
    expiresIn,
    expiresAt: buildExpiresAt(expiresIn),
    user: nextUser
  };
}

export function toLoginRequestBody(input: LoginRequest): Record<string, unknown> {
  return {
    login_type: input.loginType,
    account: input.account,
    password: input.password,
    sms_code: input.loginType === 'sms' ? input.verificationCode : undefined,
    email_code: input.loginType === 'email_code' ? input.verificationCode : undefined,
    captcha_token: input.captchaToken
  };
}

export function toSendCodeRequestBody(input: SendCodeRequest): Record<string, unknown> {
  return {
    scene: input.scene,
    account: input.account,
    account_type: input.accountType,
    captcha_token: input.captchaToken
  };
}

export function mapSendCodeResponse(
  payload: Record<string, unknown> | SendCodeResponseData,
  fallbackScene: SendCodeResponse['scene'],
  fallbackAccount: string
): SendCodeResponse {
  const record = asRecord(payload);
  return {
    scene: (record.scene as SendCodeResponse['scene']) ?? fallbackScene,
    maskedAccount: getString(record, ['masked_account', 'maskedAccount'], fallbackAccount),
    expireIn: getNumber(record, ['expire_in', 'expireIn'], 300)
  };
}

export function toForgotPasswordChallengeRequestBody(
  input: ForgotPasswordChallengeRequest
): Record<string, unknown> {
  return {
    account: input.account,
    account_type: input.accountType,
    verification_code: input.verificationCode
  };
}

export function mapForgotPasswordChallenge(
  payload: Record<string, unknown> | ForgotPasswordResponseData
): ForgotPasswordChallenge {
  const record = asRecord(payload);
  return {
    challengeId: getString(record, ['challenge_id', 'challengeId']),
    expireIn: getNumber(record, ['expire_in', 'expireIn'], 600)
  };
}

export function toResetPasswordRequestBody(input: ResetPasswordRequest): Record<string, unknown> {
  return {
    challenge_id: input.challengeId,
    account: input.account,
    verification_code: input.verificationCode,
    new_password: input.newPassword,
    confirm_password: input.confirmPassword
  };
}

export function toRefreshTokenRequestBody(refreshToken: string): Record<string, unknown> {
  return {
    refresh_token: refreshToken
  };
}

export function toLogoutRequestBody(refreshToken?: string): Record<string, unknown> {
  return {
    refresh_token: refreshToken
  };
}

export function isOperationSuccessful(value: unknown): boolean {
  const record = asRecord(value);
  if (typeof record.success === 'boolean') {
    return record.success;
  }

  return true;
}

export function toUserProfileUpdateRequestBody(
  input: UserProfileUpdateRequest
): Record<string, unknown> {
  return {
    name: input.name,
    avatar_url: input.avatarUrl,
    locale: input.locale,
    time_zone: input.timeZone
  };
}

export function toChangePasswordRequestBody(
  input: ChangePasswordRequest
): Record<string, unknown> {
  return {
    old_password: input.oldPassword,
    new_password: input.newPassword,
    confirm_password: input.confirmPassword
  };
}

export function toSessionCreateRequestBody(
  input: SessionCreateRequest
): Record<string, unknown> {
  return {
    scene: input.scene,
    title: input.title,
    initial_context: input.initialContext ?? ''
  };
}

function mapChatAttachment(input: ChatAttachment): Record<string, unknown> {
  return {
    file_id: input.fileId,
    name: input.fileName,
    file_name: input.fileName,
    mime_type: input.mimeType,
    size: input.size
  };
}

export function toChatCompletionRequestBody(
  request: ChatCompletionRequest,
  userAgent = typeof navigator === 'undefined' ? 'unknown' : navigator.userAgent
): Record<string, unknown> {
  return {
    conversation_id: request.conversationId,
    message_id: request.messageId,
    user_input: request.userInput,
    stream: request.stream,
    scene: request.scene,
    attachments: request.attachments.map(mapChatAttachment),
    context_control: {
      use_history: true,
      history_limit: request.options.maxHistoryTurns,
      must_cite: request.scene === 'billing' || request.scene === 'icp'
    },
    client_meta: {
      page: '/chat',
      user_agent: userAgent
    },
    context: {
      user_id: request.context.userId,
      tenant_id: request.context.tenantId,
      channel: request.context.channel,
      locale: request.context.locale
    },
    options: {
      use_rag: request.options.useRag,
      use_tools: request.options.useTools,
      max_history_turns: request.options.maxHistoryTurns,
      agent_hint: request.options.agentHint
    }
  };
}

export function mapMarketingCampaign(value: unknown): MarketingCampaign {
  const record = asRecord(value);
  return {
    campaignId: getString(record, ['campaign_id', 'campaignId'], 'camp_unknown'),
    name: getString(record, ['name'], '未命名活动'),
    productType: getString(record, ['product_type', 'productType'], '-'),
    status: (record.status as MarketingCampaign['status']) ?? 'draft',
    startAt: getString(record, ['start_at', 'startAt'], nowIso()),
    endAt: getString(record, ['end_at', 'endAt'], nowIso()),
    landingPageUrl: getString(record, ['landing_page_url', 'landingPageUrl'], '#'),
    highlights: getStringArray(record.highlights)
  };
}

export function toMarketingCopyRequestBody(input: MarketingCopyRequest): Record<string, unknown> {
  return {
    campaign_id: input.campaignId,
    topic: input.topic,
    audience: input.audience,
    tone: input.tone,
    keywords: input.keywords
  };
}

export function mapMarketingCopyResult(
  value: unknown | ContractMarketingCopyResult
): MarketingCopyResult {
  const record = asRecord(value);
  return {
    copyId: getString(record, ['copy_id', 'copyId'], 'copy_unknown'),
    campaignId: getString(record, ['campaign_id', 'campaignId']),
    campaignName: getString(record, ['campaign_name', 'campaignName'], '营销活动'),
    topic: getString(record, ['topic']),
    audience: getString(record, ['audience']),
    tone: (record.tone as MarketingCopyResult['tone']) ?? 'professional',
    headline: getString(record, ['headline'], '营销文案待生成'),
    summary: getString(record, ['summary']),
    body: getString(record, ['body']),
    callToAction: getString(record, ['call_to_action', 'callToAction'], '立即了解详情'),
    keywords: getStringArray(record.keywords),
    landingPageUrl:
      getOptionalString(record, ['landing_page_url', 'landingPageUrl']) ?? undefined,
    createdAt: getString(record, ['created_at', 'createdAt'], nowIso())
  };
}

export function buildMarketingCopyResultFromGenerateResponse(
  value: unknown,
  input: MarketingCopyRequest
): MarketingCopyResult {
  return mapMarketingCopyResult({
    ...asRecord(value),
    campaign_id: input.campaignId,
    topic: input.topic,
    audience: input.audience,
    tone: input.tone,
    keywords: input.keywords
  });
}

export function toCreatePosterTaskRequestBody(input: CreatePosterTaskRequest): Record<string, unknown> {
  return {
    campaign_id: input.campaignId,
    theme: input.theme,
    slogan: input.slogan,
    size: input.size
  };
}

export function mapPosterTask(value: unknown): PosterTask {
  const record = asRecord(value as ContractPosterTask | Record<string, unknown>);
  return {
    taskId: getString(record, ['task_id', 'taskId'], 'poster_unknown'),
    campaignId: getString(record, ['campaign_id', 'campaignId']),
    campaignName: getString(record, ['campaign_name', 'campaignName'], '营销活动'),
    theme: getString(record, ['theme']),
    slogan: getString(record, ['slogan']),
    size: getString(record, ['size'], '1024x1536'),
    status: (record.status as PosterTask['status']) ?? 'queued',
    createdAt: getString(record, ['created_at', 'createdAt'], nowIso()),
    estimatedSeconds: getNumber(record, ['estimated_seconds', 'estimatedSeconds']),
    imageUrl: getOptionalString(record, ['image_url', 'imageUrl']),
    errorMessage: getOptionalString(record, ['error_message', 'errorMessage']),
    updatedAt: getString(record, ['updated_at', 'updatedAt'], nowIso())
  };
}

export function buildPosterTaskFromCreateResponse(
  value: unknown,
  input: CreatePosterTaskRequest
): PosterTask {
  return mapPosterTask({
    ...asRecord(value),
    campaign_id: input.campaignId,
    theme: input.theme,
    slogan: input.slogan,
    size: input.size
  });
}

export function toCreateResearchTaskRequestBody(
  input: CreateResearchTaskRequest
): Record<string, unknown> {
  return {
    topic: input.topic,
    scope: input.scope,
    depth: input.depth,
    output_format: input.outputFormat,
    reference_urls: input.referenceUrls
  };
}

export function mapResearchTask(value: unknown): ResearchTask {
  const record = asRecord(value as ContractResearchTask | Record<string, unknown>);
  return {
    taskId: getString(record, ['task_id', 'taskId'], 'task_unknown'),
    topic: getString(record, ['topic'], '未命名任务'),
    scope: getString(record, ['scope']),
    depth: (record.depth as ResearchTask['depth']) ?? 'standard',
    outputFormat: (record.output_format as ResearchTask['outputFormat']) ?? 'markdown',
    status: (record.status as ResearchTask['status']) ?? 'queued',
    progress: getNumber(record, ['progress']),
    summary: getString(record, ['summary']),
    createdAt: getString(record, ['created_at', 'createdAt'], nowIso()),
    reportFileId: getOptionalString(record, ['report_file_id', 'reportFileId']),
    startedAt: getOptionalString(record, ['started_at', 'startedAt']),
    finishedAt: getOptionalString(record, ['finished_at', 'finishedAt']),
    errorMessage: getOptionalString(record, ['error_message', 'errorMessage']),
    updatedAt: getString(record, ['updated_at', 'updatedAt'], nowIso()),
    referenceUrls: getStringArray(record.reference_urls ?? record.referenceUrls)
  };
}

export function buildResearchTaskFromCreateResponse(
  value: unknown,
  input: CreateResearchTaskRequest
): ResearchTask {
  const record = asRecord(value);
  return mapResearchTask({
    ...record,
    topic: input.topic,
    scope: input.scope,
    depth: input.depth,
    output_format: input.outputFormat,
    reference_urls: input.referenceUrls,
    progress: record.progress ?? 0,
    summary: record.summary ?? '研究任务已创建，等待后端服务完成生成。'
  });
}

export function mapCitation(value: unknown): Citation {
  const record = asRecord(value);
  return {
    id: getString(record, ['id', 'citation_id'], 'cite_unknown'),
    title: getString(record, ['title'], '引用资料'),
    sourceType: getString(record, ['source_type', 'sourceType'], 'knowledge_base'),
    docId: getString(record, ['doc_id', 'docId']),
    chunkId: getString(record, ['chunk_id', 'chunkId']),
    url: getOptionalString(record, ['url'])
  };
}

export function mapRetryCitation(value: unknown, index: number): Citation {
  if (typeof value === 'string') {
    return {
      id: `retry_citation_${index + 1}`,
      title: value,
      sourceType: 'knowledge_base',
      docId: '',
      chunkId: ''
    };
  }

  return mapCitation(value);
}

export function mapToolCallRecord(value: unknown): ToolCallRecord {
  const record = asRecord(value as ToolInvocation | Record<string, unknown>);
  return {
    toolName: getString(record, ['tool_name', 'toolName'], 'tool.unknown'),
    toolCallId: getString(record, ['tool_call_id', 'toolCallId'], 'tc_unknown'),
    status: normalizeToolStatus(record.status),
    arguments: isRecord(record.arguments) ? record.arguments : isRecord(record.payload) ? record.payload : undefined,
    latencyMs: getOptionalNumber(record, ['latency_ms', 'latencyMs']),
    dataPreview: isRecord(record.data_preview)
      ? record.data_preview
      : isRecord(record.dataPreview)
        ? record.dataPreview
        : buildToolDataPreview(record)
  };
}

export function mapConversationSummary(value: unknown): ConversationSummary {
  const record = asRecord(value as ConversationRecord | Record<string, unknown>);
  const createdAt = getString(record, ['created_at', 'createdAt'], nowIso());
  const updatedAt = getString(record, ['updated_at', 'updatedAt'], nowIso());
  return {
    conversationId: getString(record, ['conversation_id', 'conversationId'], 'conv_unknown'),
    title: getString(record, ['title'], '未命名会话'),
    scene: (record.scene as ConversationSummary['scene']) ?? 'customer_service',
    status: (record.status as ConversationSummary['status']) ?? 'active',
    createdAt,
    currentAgent: getString(record, ['current_agent', 'currentAgent'], 'Orchestrator'),
    updatedAt,
    lastMessageAt: getString(record, ['last_message_at', 'lastMessageAt'], updatedAt),
    summary: getString(record, ['summary']),
    messageCount: getNumber(record, ['message_count', 'messageCount', 'total_messages']),
    totalTokens: getOptionalNumber(record, ['total_tokens', 'totalTokens']),
    totalCost: getOptionalString(record, ['total_cost', 'totalCost'])
  };
}

export function mapChatMessage(value: unknown, conversationIdFallback?: string): ChatMessage {
  const record = asRecord(value as ChatMessageRecord | Record<string, unknown>);
  const messageId = getString(record, ['message_id', 'messageId', 'id']);
  const fallbackId = messageId || buildClientGeneratedId('msg');
  const role = (record.role as ChatMessage['role']) ?? 'assistant';
  const rawContent = getString(record, ['content']);

  return {
    id: getString(record, ['id', 'message_id', 'messageId'], fallbackId),
    messageId: getString(record, ['message_id', 'messageId', 'id'], fallbackId),
    conversationId: getString(record, ['conversation_id', 'conversationId'], conversationIdFallback ?? ''),
    role,
    messageType: normalizeMessageType(record.message_type ?? record.messageType),
    content: role === 'assistant' ? normalizeAssistantContent(rawContent) : rawContent,
    createdAt: getString(record, ['created_at', 'createdAt'], nowIso()),
    parentMessageId: getOptionalString(record, ['parent_message_id', 'parentMessageId']),
    agentName: getOptionalString(record, ['agent_name', 'agentName']),
    status: normalizeMessageStatus(record.status),
    citations: Array.isArray(record.citations_json)
      ? record.citations_json.map(mapCitation)
      : Array.isArray(record.citations)
        ? record.citations.map(mapCitation)
        : undefined,
    toolCalls: Array.isArray(record.tool_calls_json)
      ? record.tool_calls_json.map(mapToolCallRecord)
      : Array.isArray(record.toolCalls)
        ? record.toolCalls.map(mapToolCallRecord)
        : Array.isArray(record.tool_calls)
          ? record.tool_calls.map(mapToolCallRecord)
          : undefined,
    finishReason: getOptionalString(record, ['finish_reason', 'finishReason']),
    updatedAt: getOptionalString(record, ['updated_at', 'updatedAt'])
  };
}

function normalizeRetryExecutionStatus(
  value: unknown
): SessionRetryResult['status'] {
  switch (value) {
    case 'queued':
    case 'running':
      return value;
    default:
      return 'completed';
  }
}

function normalizeRetryResolution(
  value: unknown
): SessionRetryResult['resolution'] {
  switch (value) {
    case 'success':
    case 'handoff':
    case 'need_user_input':
    case 'failed':
      return value;
    default:
      return undefined;
  }
}

export function mapChatCompletionResponse(value: unknown): ChatCompletionResponse {
  const record = asRecord(value);
  const response = asRecord(record.response);
  const usage = isRecord(record.usage) ? record.usage : isRecord(response.usage) ? response.usage : {};
  const rawCitations = Array.isArray(record.citations)
    ? record.citations
    : Array.isArray(response.citations)
      ? response.citations
      : [];
  const rawToolCalls = Array.isArray(record.tool_calls)
    ? record.tool_calls
    : Array.isArray(record.toolCalls)
      ? record.toolCalls
      : Array.isArray(response.tool_calls)
        ? response.tool_calls
        : [];

  return {
    answer:
      getOptionalString(record, ['answer', 'final_answer', 'finalAnswer']) ??
      getOptionalString(response, ['final_response_summary', 'finalResponseSummary']),
    citations: rawCitations.map(mapRetryCitation),
    toolCalls: rawToolCalls.map(mapToolCallRecord),
    finishReason:
      getOptionalString(record, ['finish_reason', 'finishReason']) ??
      getOptionalString(response, ['finish_reason', 'finishReason']) ??
      'stop',
    usage: mapUsage(usage)
  };
}

export function mapSessionCancelResult(value: unknown): SessionCancelResult {
  const record = asRecord(value);
  switch (record.status) {
    case 'completed':
    case 'not_found':
    case 'cancelled':
      return { status: record.status };
    default:
      return {
        status: record.cancelled === true ? 'cancelled' : 'cancelled'
      };
  }
}

export function mapSessionRetryResult(value: unknown): SessionRetryResult {
  const record = asRecord(value);
  const response = asRecord(record.response);
  const route = asRecord(response.route);
  const completion = mapChatCompletionResponse(record);
  const rawStatus = record.status ?? response.status;
  const resolution = normalizeRetryResolution(rawStatus);

  return {
    messageId: getString(record, ['message_id', 'messageId']),
    status: normalizeRetryExecutionStatus(rawStatus),
    resolution,
    answer: completion.answer,
    finishReason: completion.finishReason,
    agentName:
      getOptionalString(record, ['agent_name', 'agentName']) ??
      getOptionalString(route, ['primary_agent', 'primaryAgent']) ??
      getOptionalString(record, ['next_agent', 'nextAgent']) ??
      getOptionalString(response, ['next_agent', 'nextAgent']),
    toolCalls: completion.toolCalls,
    citations: completion.citations,
    actionRequired: mapRetryActionRequired(resolution, completion.answer)
  };
}

function normalizeActionRequiredType(
  value: unknown,
  fallback: ChatActionRequiredPayload['type']
): ChatActionRequiredPayload['type'] {
  switch (value) {
    case 'manual_intervention':
    case 'clarification':
    case 'permission':
      return value;
    default:
      return fallback;
  }
}

function mapActionRequiredTypeFromAction(
  action: ReturnType<typeof extractUserActionHintAction>
): ChatActionRequiredPayload['type'] | undefined {
  switch (action) {
    case 'collect-auth-context':
      return 'permission';
    case 'clarify-tool-input':
      return 'clarification';
    case 'user-confirmation':
      return 'manual_intervention';
    default:
      return undefined;
  }
}

function hasMissingFieldHints(payload: unknown): boolean {
  return (extractApiErrorDetails(payload)?.missingFields.length ?? 0) > 0;
}

function resolveStreamActionRequiredType(
  payload: unknown
): ChatActionRequiredPayload['type'] | undefined {
  const action = extractUserActionHintAction(payload);
  const actionType = mapActionRequiredTypeFromAction(action);
  if (actionType) {
    return actionType;
  }

  const kind = classifyApiError(payload);
  const code = extractEnvelopeCode(payload);
  const errorDetails = extractApiErrorDetails(payload);

  if (
    kind === 'unauthorized' ||
    kind === 'forbidden' ||
    (errorDetails?.requiredPermissions.length ?? 0) > 0 ||
    (errorDetails?.missingAuthContext.length ?? 0) > 0
  ) {
    return 'permission';
  }

  if (
    kind === 'validation' ||
    code === 'CHAT_CONTINUATION_NOT_AVAILABLE' ||
    code === 4092106 ||
    code === '4092106' ||
    code === 5002104 ||
    code === '5002104' ||
    hasMissingFieldHints(payload)
  ) {
    return 'clarification';
  }

  return undefined;
}

function mapStreamErrorMessage(rawData: unknown, payload: unknown): string {
  if (typeof rawData === 'string' && rawData.trim()) {
    return rawData.trim();
  }

  return extractEnvelopeMessage(payload, 'stream error');
}

function buildStreamActionRequiredPayload(
  payload: unknown,
  rawData: unknown
): ChatActionRequiredPayload {
  const record = asRecord(payload);
  const action = extractUserActionHintAction(record);
  const details = extractApiErrorDetails(record);
  const data: ChatActionRequiredPayload = {
    code: extractEnvelopeCode(record) ?? 'CHAT_ACTION_REQUIRED',
    message: mapStreamErrorMessage(rawData, record),
    type: normalizeActionRequiredType(
      record.type,
      mapActionRequiredTypeFromAction(action) ??
        resolveStreamActionRequiredType(record) ??
        'manual_intervention'
    )
  };

  if (action) {
    data.action = action;
  }

  const toolName = getOptionalString(record, ['tool_name', 'toolName']);
  if (toolName?.trim()) {
    data.toolName = toolName;
  }

  const toolCallId = getOptionalString(record, ['tool_call_id', 'toolCallId']);
  if (toolCallId?.trim()) {
    data.toolCallId = toolCallId;
  }

  const agent = getOptionalString(record, ['agent']);
  if (agent?.trim()) {
    data.agent = agent;
  }

  if (details) {
    data.details = details;
  }

  return data;
}

export function buildSessionListQuery(query: SessionListQuery): string {
  const params = new URLSearchParams();

  if (query.page) params.set('page', String(query.page));
  if (query.pageSize) params.set('page_size', String(query.pageSize));
  if (query.scene) params.set('scene', query.scene);
  if (query.status) params.set('status', query.status);
  if (query.keyword) params.set('keyword', query.keyword);

  const encoded = params.toString();
  return encoded ? `?${encoded}` : '';
}

function withRetryHint(events: ChatStreamEvent[], retry: number | undefined): ChatStreamEvent[] {
  if (retry === undefined) {
    return events;
  }

  return events.map((event) => ({
    ...event,
    retry
  }));
}

export function mapChatStreamEvents(raw: RawSseEvent): ChatStreamEvent[] {
  const record = asRecord(raw.data);

  switch (raw.event) {
    case 'meta':
    case 'message.started':
      return withRetryHint([
        {
          event: 'meta',
          data: {
            conversationId: getString(record, ['conversation_id', 'conversationId']),
            messageId: getString(record, ['message_id', 'messageId']),
            traceId: getString(record, ['trace_id', 'traceId']),
            agent: getString(record, ['agent', 'to_agent', 'toAgent'], 'Orchestrator')
          }
        }
      ], raw.retry);
    case 'reasoning':
      return withRetryHint([
        {
          event: 'reasoning',
          data: {
            agent: getString(record, ['agent'], 'Orchestrator'),
            summary: getString(record, ['summary']),
            step: getNumber(record, ['step'], 1)
          }
        }
      ], raw.retry);
    case 'agent.routed':
    case 'route':
      return withRetryHint([
        {
          event: 'route',
          data: {
            fromAgent: getString(record, ['from_agent', 'fromAgent'], 'Orchestrator'),
            toAgent: getString(record, ['to_agent', 'toAgent'], 'Orchestrator'),
            reason: getString(record, ['reason'], '发生了 Agent 路由。')
          }
        }
      ], raw.retry);
    case 'tool_call':
      return withRetryHint([{ event: 'tool_call', data: mapToolCallRecord(record) }], raw.retry);
    case 'tool.started':
      return withRetryHint([
        {
          event: 'tool_call',
          data: {
            toolName: getString(record, ['tool_name', 'toolName'], 'tool.unknown'),
            toolCallId: getString(record, ['tool_call_id', 'toolCallId'], 'tc_unknown'),
            status: 'running',
            dataPreview: buildToolDataPreview(record)
          }
        }
      ], raw.retry);
    case 'tool_result':
      return withRetryHint([{ event: 'tool_result', data: mapToolCallRecord(record) }], raw.retry);
    case 'tool.finished':
      return withRetryHint([
        {
          event: 'tool_result',
          data: {
            toolName: getString(record, ['tool_name', 'toolName'], 'tool.unknown'),
            toolCallId: getString(record, ['tool_call_id', 'toolCallId'], 'tc_unknown'),
            status: normalizeToolStatus(record.status ?? 'success'),
            latencyMs: getOptionalNumber(record, ['latency_ms', 'latencyMs']),
            dataPreview: buildToolDataPreview(record)
          }
        }
      ], raw.retry);
    case 'retrieval':
      return withRetryHint([
        {
          event: 'retrieval',
          data: {
            query: getString(record, ['query']),
            topK: getNumber(record, ['top_k', 'topK'], 5),
            sources: Array.isArray(record.sources)
              ? record.sources.map((item) => {
                  const source = asRecord(item);
                  return {
                    docId: getString(source, ['doc_id', 'docId']),
                    chunkId: getString(source, ['chunk_id', 'chunkId']),
                    score: getNumber(source, ['score']),
                    title: getString(source, ['title'], '引用资料')
                  };
                })
              : []
          }
        }
      ], raw.retry);
    case 'delta':
    case 'message.delta':
      return withRetryHint([
        {
          event: 'delta',
          data: {
            content: getString(record, ['content', 'delta'])
          }
        }
      ], raw.retry);
    case 'citation':
      return withRetryHint([
        {
          event: 'citation',
          data: {
            citations: Array.isArray(record.citations) ? record.citations.map(mapCitation) : []
          }
        }
      ], raw.retry);
    case 'citation.delta':
      return withRetryHint([
        {
          event: 'citation',
          data: {
            citations: [mapCitation(record)]
          }
        }
      ], raw.retry);
    case 'done':
    case 'message.completed': {
      const completionEvents: ChatStreamEvent[] = [];
      const citations = Array.isArray(record.citations) ? record.citations.map(mapCitation) : [];
      const toolCalls = Array.isArray(record.tool_calls)
        ? record.tool_calls.map(mapToolCallRecord)
        : Array.isArray(record.toolCalls)
          ? record.toolCalls.map(mapToolCallRecord)
          : [];

      if (citations.length) {
        completionEvents.push({
          event: 'citation',
          data: {
            citations
          }
        });
      }

      for (const toolCall of toolCalls) {
        completionEvents.push({
          event: 'tool_result',
          data: toolCall
        });
      }

      completionEvents.push({
        event: 'done',
        data: {
          finishReason: getString(record, ['finish_reason', 'finishReason'], 'stop'),
          usage: isRecord(record.usage)
            ? mapUsage(record.usage)
            : { promptTokens: 0, completionTokens: 0, totalTokens: 0 }
        }
      });

      return withRetryHint(completionEvents, raw.retry);
    }
    case 'action_required':
    case 'message.action_required': {
      return withRetryHint([
        {
          event: 'action_required',
          data: buildStreamActionRequiredPayload(record, raw.data)
        }
      ], raw.retry);
    }
    case 'error':
    case 'message.error': {
      const events: ChatStreamEvent[] = [];
      const actionRequiredType = resolveStreamActionRequiredType(record);

      if (actionRequiredType) {
        events.push({
          event: 'action_required',
          data: buildStreamActionRequiredPayload(
            {
              ...record,
              type: record.type ?? actionRequiredType
            },
            raw.data
          )
        });
      }

      events.push({
        event: 'error',
        data: {
          code: extractEnvelopeCode(record) ?? 'WEB_STREAM_ERROR',
          message: mapStreamErrorMessage(raw.data, record)
        }
      });

      return withRetryHint(events, raw.retry);
    }
    case 'ping':
    case 'heartbeat':
      return withRetryHint([{ event: 'ping', data: {} }], raw.retry);
    default:
      return [];
  }
}

export function mapRetryActionRequired(
  resolution: 'success' | 'handoff' | 'need_user_input' | 'failed' | undefined,
  answer?: string
): ChatActionRequiredPayload | undefined {
  if (resolution === 'need_user_input') {
    return {
      code: 'CHAT_RETRY_NEED_USER_INPUT',
      message: answer ?? '需要补充更多信息后再继续重试。',
      type: 'clarification'
    };
  }

  if (resolution === 'handoff') {
    return {
      code: 'CHAT_RETRY_HANDOFF',
      message: answer ?? '当前问题建议转人工或切换到其他 Agent 继续处理。',
      type: 'manual_intervention'
    };
  }

  return undefined;
}
