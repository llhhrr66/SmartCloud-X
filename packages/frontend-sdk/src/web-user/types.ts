import type { SceneName } from '@smartcloud-x/common-schemas';
import type { ApiErrorDetailsInfo, ApiUserActionKind } from '../core/envelope';

export type LoginType = 'password' | 'sms' | 'email_code';
export type AuthCodeScene = 'login' | 'reset_password';
export type AccountType = 'mobile' | 'email';
export type Scene = SceneName;
export type ConversationStatus = 'active' | 'running' | 'closed' | 'archived' | 'deleted' | 'expired';
export type MessageRole = 'system' | 'user' | 'assistant' | 'tool' | 'agent';
export type MessageType = 'text' | 'markdown' | 'image' | 'file' | 'event';
export type MessageStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'handoff'
  | 'need_user_input'
  | 'failed'
  | 'cancelled'
  | 'error';
export type ToolCallStatus = 'pending' | 'running' | 'success' | 'failed' | 'timeout' | 'cancelled';

export interface CurrentUser {
  userId: string;
  tenantId: string;
  name: string;
  email: string;
  mobile: string;
  avatarUrl?: string;
  locale: string;
  timeZone: string;
  permissions: string[];
}

export interface AuthSession {
  accessToken: string;
  refreshToken: string;
  expiresIn: number;
  expiresAt: string;
  user: CurrentUser;
}

export interface LoginRequest {
  loginType: LoginType;
  account: string;
  password?: string;
  verificationCode?: string;
  captchaToken?: string;
}

export interface SendCodeRequest {
  scene: AuthCodeScene;
  account: string;
  accountType: AccountType;
  captchaToken?: string;
}

export interface SendCodeResponse {
  scene: AuthCodeScene;
  maskedAccount: string;
  expireIn: number;
}

export interface ForgotPasswordChallengeRequest {
  account: string;
  accountType: AccountType;
  verificationCode: string;
}

export interface ForgotPasswordChallenge {
  challengeId: string;
  expireIn: number;
}

export interface ResetPasswordRequest {
  challengeId: string;
  account: string;
  verificationCode: string;
  newPassword: string;
  confirmPassword: string;
}

export interface UserProfileUpdateRequest {
  name?: string;
  avatarUrl?: string;
  locale?: string;
  timeZone?: string;
}

export interface ChangePasswordRequest {
  oldPassword: string;
  newPassword: string;
  confirmPassword: string;
}

export interface Citation {
  id: string;
  title: string;
  sourceType: string;
  docId: string;
  chunkId: string;
  url?: string;
}

export interface ToolCallRecord {
  toolName: string;
  toolCallId: string;
  status: ToolCallStatus;
  arguments?: Record<string, unknown>;
  latencyMs?: number;
  dataPreview?: Record<string, unknown>;
}

export interface ConversationSummary {
  conversationId: string;
  title: string;
  scene: Scene;
  status: ConversationStatus;
  createdAt: string;
  currentAgent: string;
  updatedAt: string;
  lastMessageAt: string;
  summary: string;
  messageCount: number;
  totalTokens?: number;
  totalCost?: string;
}

export interface ChatMessage {
  id: string;
  messageId: string;
  conversationId: string;
  role: MessageRole;
  messageType: MessageType;
  content: string;
  createdAt: string;
  parentMessageId?: string;
  agentName?: string;
  status: MessageStatus;
  citations?: Citation[];
  toolCalls?: ToolCallRecord[];
  documentRefs?: FaqDocumentRef[];
  finishReason?: string;
  updatedAt?: string;
}

export interface ChatAttachment {
  fileId: string;
  fileName: string;
  mimeType: string;
  size: number;
}

export interface ChatCompletionRequest {
  conversationId: string;
  messageId: string;
  userInput: string;
  stream: boolean;
  scene: Scene;
  attachments: ChatAttachment[];
  context: {
    userId: string;
    tenantId: string;
    channel: 'web';
    locale: string;
  };
  options: {
    useRag: boolean;
    useTools: boolean;
    maxHistoryTurns: number;
    agentHint?: string;
  };
}

export interface ChatCompletionResponse {
  answer?: string;
  citations: Citation[];
  toolCalls: ToolCallRecord[];
  finishReason: string;
  usage: {
    promptTokens: number;
    completionTokens: number;
    totalTokens: number;
  };
}

export interface RetrievalSource {
  docId: string;
  chunkId: string;
  score: number;
  title: string;
}

export interface FaqDocumentRef {
  docId: string;
  title: string;
  url?: string;
}

export interface FaqEventPayload {
  category?: string | null;
  prerequisites?: string[];
  documentRefs?: FaqDocumentRef[];
  relatedTopics?: string[];
  matchReason?: string | null;
  tokenSaved?: number;
}

export interface ChatMetaPayload {
  conversationId: string;
  messageId: string;
  traceId: string;
  agent: string;
}

export interface ChatReasoningPayload {
  agent: string;
  summary: string;
  step: number;
}

export interface ChatRoutePayload {
  fromAgent: string;
  toAgent: string;
  reason: string;
}

export interface ChatRetrievalPayload {
  query: string;
  topK: number;
  sources: RetrievalSource[];
}

export interface ChatDeltaPayload {
  content: string;
}

export interface ChatCitationPayload {
  citations: Citation[];
}

export interface ChatDonePayload {
  finishReason: string;
  usage: {
    promptTokens: number;
    completionTokens: number;
    totalTokens: number;
  };
}

export interface ChatErrorPayload {
  code: number | string;
  message: string;
}

export interface ChatActionRequiredPayload {
  code: number | string;
  message: string;
  type: 'manual_intervention' | 'clarification' | 'permission';
  action?: ApiUserActionKind;
  toolName?: string;
  toolCallId?: string;
  agent?: string;
  details?: ApiErrorDetailsInfo;
}

export interface SharedStreamRetryHint {
  retry?: number;
}

type SharedChatStreamEvent<TEvent extends string, TData> = SharedStreamRetryHint & {
  event: TEvent;
  data: TData;
};

export type ChatStreamEvent =
  | SharedChatStreamEvent<'meta', ChatMetaPayload>
  | SharedChatStreamEvent<'reasoning', ChatReasoningPayload>
  | SharedChatStreamEvent<'route', ChatRoutePayload>
  | SharedChatStreamEvent<'tool_call', ToolCallRecord>
  | SharedChatStreamEvent<'tool_result', ToolCallRecord>
  | SharedChatStreamEvent<'retrieval', ChatRetrievalPayload>
  | SharedChatStreamEvent<'delta', ChatDeltaPayload>
  | SharedChatStreamEvent<'citation', ChatCitationPayload>
  | SharedChatStreamEvent<'faq', FaqEventPayload>
  | SharedChatStreamEvent<'done', ChatDonePayload>
  | SharedChatStreamEvent<'error', ChatErrorPayload>
  | SharedChatStreamEvent<'action_required', ChatActionRequiredPayload>
  | SharedChatStreamEvent<'ping', Record<string, never>>;

export interface SessionListQuery {
  page?: number;
  pageSize?: number;
  scene?: Scene;
  status?: ConversationStatus;
  keyword?: string;
}

export interface SessionCreateRequest {
  scene: Scene;
  title: string;
  initialContext?: string;
}

export interface PaginatedResult<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
}

export interface SessionCancelResult {
  status: 'cancelled' | 'completed' | 'not_found';
}

export interface SessionRetryResult {
  messageId: string;
  status: 'queued' | 'running' | 'completed';
  resolution?: 'success' | 'handoff' | 'need_user_input' | 'failed';
  answer?: string;
  finishReason?: string;
  agentName?: string;
  toolCalls?: ToolCallRecord[];
  citations?: Citation[];
  actionRequired?: ChatActionRequiredPayload;
}

export interface MarketingCampaign {
  campaignId: string;
  name: string;
  productType: string;
  status: 'published' | 'draft' | 'expired';
  startAt: string;
  endAt: string;
  landingPageUrl: string;
  highlights: string[];
}

export interface MarketingCopyRequest {
  campaignId: string;
  topic: string;
  audience: string;
  tone: 'professional' | 'growth' | 'launch';
  keywords: string[];
}

export interface MarketingCopyResult {
  copyId: string;
  campaignId: string;
  campaignName: string;
  topic: string;
  audience: string;
  tone: MarketingCopyRequest['tone'];
  headline: string;
  summary: string;
  body: string;
  callToAction: string;
  keywords: string[];
  landingPageUrl?: string;
  createdAt: string;
}

export interface PosterTask {
  taskId: string;
  campaignId: string;
  campaignName: string;
  theme: string;
  slogan: string;
  size: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  createdAt: string;
  estimatedSeconds: number;
  imageUrl?: string;
  errorMessage?: string;
  updatedAt: string;
}

export interface CreatePosterTaskRequest {
  campaignId: string;
  theme: string;
  slogan: string;
  size: string;
}

export interface ResearchTask {
  taskId: string;
  topic: string;
  scope: string;
  depth: 'lite' | 'standard' | 'deep';
  outputFormat: 'markdown' | 'pdf';
  status: 'queued' | 'running' | 'completed' | 'failed';
  progress: number;
  summary: string;
  createdAt: string;
  reportFileId?: string;
  startedAt?: string;
  finishedAt?: string;
  errorMessage?: string;
  updatedAt: string;
  referenceUrls: string[];
}

export interface CreateResearchTaskRequest {
  topic: string;
  scope: string;
  depth: 'lite' | 'standard' | 'deep';
  outputFormat: 'markdown' | 'pdf';
  referenceUrls: string[];
}
