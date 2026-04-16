import {
  sharedRequestHeaderNames,
  type InternalCallerServiceName
} from '@smartcloud-x/common';

export type SmartCloudRole =
  | 'user'
  | 'admin'
  | 'agent'
  | 'service'
  | 'support_agent'
  | 'ops_admin';

export type SmartCloudPermission =
  | 'user:chat.use'
  | 'user:billing.read'
  | 'user:order.read'
  | 'user:ticket.read'
  | 'user:ticket.write'
  | 'user:icp.read'
  | 'user:icp.write'
  | 'user:marketing.read'
  | 'user:marketing.write'
  | 'user:research.read'
  | 'user:research.write'
  | 'admin:agent.read'
  | 'admin:agent.write'
  | 'admin:audit.read'
  | 'admin:conversation.read'
  | 'admin:eval.read'
  | 'admin:eval.write'
  | 'admin:icp.read'
  | 'admin:icp.write'
  | 'admin:job.read'
  | 'admin:kb.read'
  | 'admin:kb.write'
  | 'admin:knowledge.read'
  | 'admin:knowledge.write'
  | 'admin:marketing.read'
  | 'admin:marketing.write'
  | 'admin:ops.read'
  | 'admin:ops.write'
  | 'admin:prompt.publish'
  | 'admin:prompt.read'
  | 'admin:prompt.write'
  | 'admin:refund.read'
  | 'admin:refund.write'
  | 'admin:role.read'
  | 'admin:role.write'
  | 'admin:ticket.read'
  | 'admin:ticket.write'
  | 'admin:user.read'
  | 'admin:user.write'
  | 'service:internal.call';

export type InternalCallerService = InternalCallerServiceName;
export type AuthStateRequirement = 'anonymous' | 'authenticated:user' | 'authenticated:admin';

export interface AuthContext {
  subject: string;
  role: SmartCloudRole;
  roles?: SmartCloudRole[];
  permissions?: SmartCloudPermission[];
  issuer: string;
  audience: string;
  tenantId?: string;
  tokenId?: string;
}

export interface JwtConfig {
  issuer: string;
  audience: string;
  internalAudience: string;
  algorithm: 'HS256' | 'RS256';
  tokenTtlMinutes: number;
}

export interface InternalAuthHeadersOptions {
  token: string;
  callerService: InternalCallerService;
  requestId: string;
  traceId: string;
  tenantId?: string;
  conversationId?: string;
  toolCallId?: string;
  idempotencyKey?: string;
  operatorReason?: string;
}

export interface ParsedAuthorizationHeader {
  scheme: 'Bearer';
  token: string;
}

export const authStateRequirements = [
  'anonymous',
  'authenticated:user',
  'authenticated:admin'
] as const satisfies readonly AuthStateRequirement[];

export const permissionAliasMap = {
  'admin:knowledge.read': 'admin:kb.read',
  'admin:knowledge.write': 'admin:kb.write'
} as const satisfies Partial<Record<SmartCloudPermission, SmartCloudPermission>>;

export const defaultJwtConfig: JwtConfig = {
  issuer: 'smartcloud-x',
  audience: 'smartcloud-x-clients',
  internalAudience: 'smartcloud-x-internal',
  algorithm: 'HS256',
  tokenTtlMinutes: 120
};

export const foundationPermissions: SmartCloudPermission[] = [
  'user:chat.use',
  'user:billing.read',
  'user:order.read',
  'user:ticket.read',
  'user:ticket.write',
  'user:icp.read',
  'user:icp.write',
  'user:marketing.read',
  'user:marketing.write',
  'user:research.read',
  'user:research.write',
  'admin:agent.read',
  'admin:agent.write',
  'admin:audit.read',
  'admin:conversation.read',
  'admin:eval.read',
  'admin:eval.write',
  'admin:icp.read',
  'admin:icp.write',
  'admin:job.read',
  'admin:kb.read',
  'admin:kb.write',
  'admin:knowledge.read',
  'admin:knowledge.write',
  'admin:marketing.read',
  'admin:marketing.write',
  'admin:ops.read',
  'admin:ops.write',
  'admin:prompt.publish',
  'admin:prompt.read',
  'admin:prompt.write',
  'admin:refund.read',
  'admin:refund.write',
  'admin:role.read',
  'admin:role.write',
  'admin:ticket.read',
  'admin:ticket.write',
  'admin:user.read',
  'admin:user.write',
  'service:internal.call'
];

export const defaultRolePermissions: Record<SmartCloudRole, SmartCloudPermission[]> = {
  user: [
    'user:chat.use',
    'user:billing.read',
    'user:order.read',
    'user:ticket.read',
    'user:ticket.write',
    'user:icp.read',
    'user:icp.write',
    'user:marketing.read',
    'user:marketing.write',
    'user:research.read',
    'user:research.write'
  ],
  admin: [
    'admin:agent.read',
    'admin:agent.write',
    'admin:conversation.read',
    'admin:kb.read',
    'admin:kb.write',
    'admin:knowledge.read',
    'admin:knowledge.write',
    'admin:ops.read'
  ],
  agent: ['service:internal.call'],
  service: ['service:internal.call'],
  support_agent: [
    'admin:conversation.read',
    'admin:ticket.read',
    'admin:ticket.write',
    'admin:icp.read',
    'admin:icp.write'
  ],
  ops_admin: [
    'admin:audit.read',
    'admin:job.read',
    'admin:marketing.read',
    'admin:marketing.write',
    'admin:ops.read',
    'admin:ops.write',
    'admin:refund.read',
    'admin:refund.write'
  ]
};

export function buildAuthorizationHeader(token: string): `Bearer ${string}` {
  return `Bearer ${token}`;
}

export function parseAuthorizationHeader(
  headerValue: string | null | undefined
): ParsedAuthorizationHeader | null {
  if (!headerValue) {
    return null;
  }

  const [scheme, token] = headerValue.trim().split(/\s+/, 2);
  if (scheme !== 'Bearer' || !token) {
    return null;
  }

  return {
    scheme: 'Bearer',
    token
  };
}

export function normalizePermissionCode(permission: string): string {
  return permissionAliasMap[permission as keyof typeof permissionAliasMap] ?? permission;
}

export function normalizePermissions(permissions: readonly string[] | null | undefined): string[] {
  return [...new Set((permissions ?? []).map((permission) => normalizePermissionCode(permission)))];
}

export function getMissingPermissions(
  grantedPermissions: readonly string[] | null | undefined,
  requiredPermissions: readonly SmartCloudPermission[] | readonly string[]
): string[] {
  const granted = new Set(normalizePermissions(grantedPermissions));
  const required = [...new Set(requiredPermissions.map((permission) => normalizePermissionCode(permission)))];
  return required.filter((permission) => !granted.has(permission));
}

export function hasAllPermissions(
  grantedPermissions: readonly string[] | null | undefined,
  requiredPermissions: readonly SmartCloudPermission[] | readonly string[]
): boolean {
  return getMissingPermissions(grantedPermissions, requiredPermissions).length === 0;
}

export function buildInternalAuthHeaders(
  options: InternalAuthHeadersOptions
): Record<string, string> {
  const headers: Record<string, string> = {
    Authorization: buildAuthorizationHeader(options.token),
    [sharedRequestHeaderNames.callerService]: options.callerService,
    [sharedRequestHeaderNames.requestId]: options.requestId,
    [sharedRequestHeaderNames.traceId]: options.traceId
  };

  if (options.tenantId) {
    headers[sharedRequestHeaderNames.tenantId] = options.tenantId;
  }

  if (options.conversationId) {
    headers[sharedRequestHeaderNames.conversationId] = options.conversationId;
  }

  if (options.toolCallId) {
    headers[sharedRequestHeaderNames.toolCallId] = options.toolCallId;
  }

  if (options.idempotencyKey) {
    headers[sharedRequestHeaderNames.idempotencyKey] = options.idempotencyKey;
  }

  if (options.operatorReason) {
    headers[sharedRequestHeaderNames.operatorReason] = options.operatorReason;
  }

  return headers;
}

export function isSmartCloudRole(value: string): value is SmartCloudRole {
  return (
    value === 'user' ||
    value === 'admin' ||
    value === 'agent' ||
    value === 'service' ||
    value === 'support_agent' ||
    value === 'ops_admin'
  );
}

export function isSmartCloudPermission(value: string): value is SmartCloudPermission {
  return foundationPermissions.includes(value as SmartCloudPermission);
}
