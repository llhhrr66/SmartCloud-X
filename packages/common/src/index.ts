export type ServiceOwningSupervisorName =
  | 'supervisor-foundation'
  | 'supervisor-web-user'
  | 'supervisor-orchestrator'
  | 'supervisor-knowledge-rag'
  | 'supervisor-auth-marketing-research';

export type SharedScopeSupervisorName =
  | 'supervisor-frontend-sdk'
  | 'supervisor-integration-qa';

export type SupervisorName = ServiceOwningSupervisorName | SharedScopeSupervisorName;

export type ServiceName =
  | 'web-user'
  | 'web-admin'
  | 'orchestrator-service'
  | 'rag-service'
  | 'knowledge-service'
  | 'tool-hub-service'
  | 'business-tools-service';

export type ContractPlaceholderServiceName =
  | 'auth-user-service'
  | 'marketing-service'
  | 'research-service';
export type ReservedPlatformServiceName = 'gateway-service';
export type PlatformServiceName =
  | ServiceName
  | ContractPlaceholderServiceName
  | ReservedPlatformServiceName;
export type InternalCallerServiceName = PlatformServiceName;

export const serviceOwningSupervisorNames = [
  'supervisor-foundation',
  'supervisor-web-user',
  'supervisor-orchestrator',
  'supervisor-knowledge-rag',
  'supervisor-auth-marketing-research'
] as const satisfies readonly ServiceOwningSupervisorName[];

export const sharedScopeSupervisorNames = [
  'supervisor-frontend-sdk',
  'supervisor-integration-qa'
] as const satisfies readonly SharedScopeSupervisorName[];

export const supervisorNames = [
  ...serviceOwningSupervisorNames,
  ...sharedScopeSupervisorNames
] as const satisfies readonly SupervisorName[];

export interface ServiceDescriptor {
  name: ServiceName;
  displayName: string;
  workspacePath: string;
  defaultApiBasePath?: string;
  legacyApiBasePaths?: string[];
  internalApiBasePaths?: string[];
  ownerSupervisor: ServiceOwningSupervisorName;
  contractScope: 'external' | 'internal' | 'hybrid';
}

export interface PlatformServiceDescriptor
  extends Omit<ServiceDescriptor, 'name' | 'workspacePath' | 'ownerSupervisor'> {
  name: PlatformServiceName;
  workspacePath?: string;
  ownerSupervisor?: ServiceOwningSupervisorName;
  lifecycle: 'assigned' | 'contract-placeholder' | 'reserved-platform';
}

export const foundationServices: ServiceDescriptor[] = [
  {
    name: 'web-user',
    displayName: 'Web User',
    workspacePath: 'apps/web-user',
    ownerSupervisor: 'supervisor-web-user',
    contractScope: 'external'
  },
  {
    name: 'web-admin',
    displayName: 'Web Admin',
    workspacePath: 'apps/web-admin',
    ownerSupervisor: 'supervisor-knowledge-rag',
    contractScope: 'external'
  },
  {
    name: 'orchestrator-service',
    displayName: 'Orchestrator Service',
    workspacePath: 'apps/orchestrator-service',
    defaultApiBasePath: '/api/v1',
    legacyApiBasePaths: ['/api/orchestrator/v1'],
    internalApiBasePaths: ['/internal/v1'],
    ownerSupervisor: 'supervisor-orchestrator',
    contractScope: 'hybrid'
  },
  {
    name: 'rag-service',
    displayName: 'RAG Service',
    workspacePath: 'apps/rag-service',
    defaultApiBasePath: '/api/rag/v1',
    ownerSupervisor: 'supervisor-knowledge-rag',
    contractScope: 'internal'
  },
  {
    name: 'knowledge-service',
    displayName: 'Knowledge Service',
    workspacePath: 'apps/knowledge-service',
    defaultApiBasePath: '/api/knowledge/v1',
    ownerSupervisor: 'supervisor-knowledge-rag',
    contractScope: 'internal'
  },
  {
    name: 'tool-hub-service',
    displayName: 'Tool Hub Service',
    workspacePath: 'apps/tool-hub-service',
    defaultApiBasePath: '/api/v1',
    legacyApiBasePaths: ['/api/tool-hub/v1'],
    internalApiBasePaths: ['/internal/v1', '/tools'],
    ownerSupervisor: 'supervisor-orchestrator',
    contractScope: 'internal'
  },
  {
    name: 'business-tools-service',
    displayName: 'Business Tools Service',
    workspacePath: 'apps/business-tools',
    defaultApiBasePath: '/internal/v1',
    ownerSupervisor: 'supervisor-orchestrator',
    contractScope: 'internal'
  }
];

export const contractPlaceholderServiceNames = [
  'auth-user-service',
  'marketing-service',
  'research-service'
] as const satisfies readonly ContractPlaceholderServiceName[];

export const reservedPlatformServiceNames = ['gateway-service'] as const satisfies readonly ReservedPlatformServiceName[];

export const platformServiceDescriptors: PlatformServiceDescriptor[] = [
  ...foundationServices.map((service) => ({
    ...service,
    lifecycle: 'assigned' as const
  })),
  {
    name: 'auth-user-service',
    displayName: 'Auth User Service',
    workspacePath: 'apps/auth-user-service',
    defaultApiBasePath: '/api/v1',
    internalApiBasePaths: ['/internal/v1'],
    ownerSupervisor: 'supervisor-auth-marketing-research',
    contractScope: 'hybrid',
    lifecycle: 'contract-placeholder'
  },
  {
    name: 'marketing-service',
    displayName: 'Marketing Service',
    workspacePath: 'apps/marketing-service',
    defaultApiBasePath: '/api/v1/marketing',
    ownerSupervisor: 'supervisor-auth-marketing-research',
    contractScope: 'external',
    lifecycle: 'contract-placeholder'
  },
  {
    name: 'research-service',
    displayName: 'Research Service',
    workspacePath: 'apps/research-service',
    defaultApiBasePath: '/api/v1/research',
    ownerSupervisor: 'supervisor-auth-marketing-research',
    contractScope: 'external',
    lifecycle: 'contract-placeholder'
  },
  {
    name: 'gateway-service',
    displayName: 'Gateway Service',
    defaultApiBasePath: '/api/v1',
    contractScope: 'hybrid',
    lifecycle: 'reserved-platform'
  }
];

export const platformServiceNames: PlatformServiceName[] = platformServiceDescriptors.map(
  (service) => service.name
);

export const sharedRequestHeaderNames = {
  requestId: 'X-Request-Id',
  traceId: 'X-Trace-Id',
  conversationId: 'X-Conversation-Id',
  tenantId: 'X-Tenant-Id',
  callerService: 'X-Caller-Service',
  toolCallId: 'X-Tool-Call-Id',
  idempotencyKey: 'Idempotency-Key',
  operatorReason: 'X-Operator-Reason'
} as const;

export const sharedResponseHeaderNames = {
  requestId: 'X-Request-Id',
  traceId: 'X-Trace-Id',
  appName: 'X-App-Name',
  appVersion: 'X-App-Version',
  responseTime: 'X-Response-Time'
} as const;

export const sharedHeaderNames = {
  ...sharedRequestHeaderNames,
  ...sharedResponseHeaderNames
} as const;

export const sharedRuntimeEnvKeys = {
  env: 'SMARTCLOUD_ENV',
  logLevel: 'SMARTCLOUD_LOG_LEVEL',
  timezone: 'SMARTCLOUD_TIMEZONE',
  defaultLocale: 'SMARTCLOUD_DEFAULT_LOCALE',
  corsAllowedOrigins: 'SMARTCLOUD_CORS_ALLOWED_ORIGINS',
  apiPrefix: 'SMARTCLOUD_API_PREFIX',
  apiVersion: 'SMARTCLOUD_API_VERSION',
  authIssuer: 'SMARTCLOUD_AUTH_ISSUER',
  authAudience: 'SMARTCLOUD_AUTH_AUDIENCE',
  internalAuthAudience: 'SMARTCLOUD_INTERNAL_AUTH_AUDIENCE',
  jwtAlgorithm: 'SMARTCLOUD_JWT_ALGORITHM',
  jwtSecret: 'SMARTCLOUD_JWT_SECRET',
  tokenTtlMinutes: 'SMARTCLOUD_TOKEN_TTL_MINUTES',
  requestTimeoutMs: 'SMARTCLOUD_REQUEST_TIMEOUT_MS',
  sseHeartbeatIntervalSeconds: 'SMARTCLOUD_SSE_HEARTBEAT_INTERVAL_SECONDS',
  allowedInternalCallers: 'ALLOWED_INTERNAL_CALLERS',
  businessToolsInternalApiPrefix: 'BUSINESS_TOOLS_INTERNAL_API_PREFIX',
  toolHubInternalApiPrefix: 'TOOL_HUB_INTERNAL_API_PREFIX',
  traceEnabled: 'SMARTCLOUD_TRACE_ENABLED',
  requestIdHeader: 'SMARTCLOUD_REQUEST_ID_HEADER',
  traceIdHeader: 'SMARTCLOUD_TRACE_ID_HEADER',
  conversationIdHeader: 'SMARTCLOUD_CONVERSATION_ID_HEADER',
  tenantIdHeader: 'SMARTCLOUD_TENANT_ID_HEADER',
  callerServiceHeader: 'SMARTCLOUD_CALLER_SERVICE_HEADER',
  toolCallIdHeader: 'SMARTCLOUD_TOOL_CALL_ID_HEADER',
  idempotencyKeyHeader: 'SMARTCLOUD_IDEMPOTENCY_KEY_HEADER',
  operatorReasonHeader: 'SMARTCLOUD_OPERATOR_REASON_HEADER',
  langsmithEnabled: 'SMARTCLOUD_LANGSMITH_ENABLED',
  langsmithProject: 'SMARTCLOUD_LANGSMITH_PROJECT',
  phoenixEnabled: 'SMARTCLOUD_PHOENIX_ENABLED',
  phoenixCollectorEndpoint: 'SMARTCLOUD_PHOENIX_COLLECTOR_ENDPOINT'
} as const;

export const foundationFrozenPaths = [
  'packages/common',
  'packages/common-schemas',
  'packages/common-auth',
  'docs/contracts',
  'openapi',
  '.env.example'
] as const;

export const internalCallerServiceNames: InternalCallerServiceName[] = [...platformServiceNames];

const foundationServiceMap = new Map(
  foundationServices.map((service) => [service.name, service])
);
const platformServiceMap = new Map(
  platformServiceDescriptors.map((service) => [service.name, service])
);
const serviceOwningSupervisorNameSet = new Set<string>(serviceOwningSupervisorNames);
const sharedScopeSupervisorNameSet = new Set<string>(sharedScopeSupervisorNames);
const supervisorNameSet = new Set<string>(supervisorNames);
const internalCallerNameSet = new Set<string>(internalCallerServiceNames);

export function getServiceDescriptor(serviceName: ServiceName): ServiceDescriptor {
  const descriptor = foundationServiceMap.get(serviceName);
  if (!descriptor) {
    throw new Error(`Unknown SmartCloud-X service: ${serviceName}`);
  }

  return descriptor;
}

export function isServiceName(value: string): value is ServiceName {
  return foundationServiceMap.has(value as ServiceName);
}

export function getPlatformServiceDescriptor(
  serviceName: PlatformServiceName
): PlatformServiceDescriptor {
  const descriptor = platformServiceMap.get(serviceName);
  if (!descriptor) {
    throw new Error(`Unknown SmartCloud-X platform service: ${serviceName}`);
  }

  return descriptor;
}

export function isPlatformServiceName(value: string): value is PlatformServiceName {
  return platformServiceMap.has(value as PlatformServiceName);
}

export function isServiceOwningSupervisorName(
  value: string
): value is ServiceOwningSupervisorName {
  return serviceOwningSupervisorNameSet.has(value);
}

export function isSharedScopeSupervisorName(value: string): value is SharedScopeSupervisorName {
  return sharedScopeSupervisorNameSet.has(value);
}

export function isSupervisorName(value: string): value is SupervisorName {
  return supervisorNameSet.has(value);
}

export function isInternalCallerServiceName(value: string): value is InternalCallerServiceName {
  return internalCallerNameSet.has(value);
}

export function getServiceApiBasePaths(serviceName: ServiceName): string[] {
  const descriptor = getServiceDescriptor(serviceName);

  return [
    ...(descriptor.defaultApiBasePath ? [descriptor.defaultApiBasePath] : []),
    ...(descriptor.legacyApiBasePaths ?? []),
    ...(descriptor.internalApiBasePaths ?? [])
  ];
}

export function getPlatformServiceApiBasePaths(serviceName: PlatformServiceName): string[] {
  const descriptor = getPlatformServiceDescriptor(serviceName);

  return [
    ...(descriptor.defaultApiBasePath ? [descriptor.defaultApiBasePath] : []),
    ...(descriptor.legacyApiBasePaths ?? []),
    ...(descriptor.internalApiBasePaths ?? [])
  ];
}
