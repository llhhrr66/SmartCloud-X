# Shared Auth Contract

## Baseline assumptions
- token transport: `Authorization: Bearer <token>`
- shared issuer: `smartcloud-x`
- shared audience: `smartcloud-x-clients`
- shared internal audience: `smartcloud-x-internal`
- supported starter algorithms: `HS256` and `RS256`

## Shared roles
- `user`
- `admin`
- `agent`
- `service`
- `support_agent`
- `ops_admin`

Note:
- the primary spec sometimes describes user-surface access as `end_user`
- the current frozen shared role name for that persona remains `user`
- owner services may expose `end_user` in human-facing docs, but shared code/constants should continue to use `user` until a deliberate rename or alias proposal is accepted

## Starter permission codes
### User surface
- `user:chat.use`
- `user:billing.read`
- `user:order.read`
- `user:ticket.read`
- `user:ticket.write`
- `user:icp.read`
- `user:icp.write`
- `user:marketing.read`
- `user:marketing.write`
- `user:research.read`
- `user:research.write`

### Admin / platform surface
- `admin:agent.read`
- `admin:agent.write`
- `admin:audit.read`
- `admin:conversation.read`
- `admin:eval.read`
- `admin:eval.write`
- `admin:icp.read`
- `admin:icp.write`
- `admin:job.read`
- `admin:kb.read`
- `admin:kb.write`
- `admin:marketing.read`
- `admin:marketing.write`
- `admin:ops.read`
- `admin:ops.write`
- `admin:prompt.publish`
- `admin:prompt.read`
- `admin:prompt.write`
- `admin:refund.read`
- `admin:refund.write`
- `admin:role.read`
- `admin:role.write`
- `admin:ticket.read`
- `admin:ticket.write`
- `admin:user.read`
- `admin:user.write`
- `service:internal.call`

Legacy compatibility aliases still accepted by `@smartcloud-x/common-auth`:
- `admin:knowledge.read` -> `admin:kb.read`
- `admin:knowledge.write` -> `admin:kb.write`

## Contract-only access-state markers
For auth/bootstrap routes whose access rule is defined by subject state instead of RBAC, foundation publishes these markers for OpenAPI `x-permission-code` use only:
- `anonymous`
- `authenticated:user`
- `authenticated:admin`

## Internal service-caller baseline
- internal service calls must also send `X-Caller-Service`
- reserved caller names currently include all in-repo services plus `gateway-service`; the frozen shared registry also keeps assigned owner metadata for the current auth/marketing/research contract-placeholder services under `supervisor-auth-marketing-research`
- `packages/common-auth` publishes `buildInternalAuthHeaders(...)`, `normalizePermissionCode(...)`, `getMissingPermissions(...)`, and `hasAllPermissions(...)`
- `buildInternalAuthHeaders(...)` now also forwards optional `X-Tool-Call-Id`, `Idempotency-Key`, and `X-Operator-Reason` values when present
- internal allow-lists remain service-local; for example orchestrator internal chat currently validates caller names against its own configured allow-list

## Published auth route baseline
- `openapi/auth-user-service.openapi.yaml` now freezes the minimum user login/account routes, admin auth bootstrap routes, and internal token-validation/permission-check/cache-invalidation routes expected by spec sections `20.13`, `20.14`, and `20.17`
- additive auth compatibility aliases are also published for `/api/v1/auth/profile`, `/api/v1/auth/change-password`, `/api/v1/auth/forgot-password`, and `/api/v1/auth/reset-password` alongside the existing `/api/v1/users/me*` and `/api/v1/auth/password/*` baselines
- public auth/account routes keep the canonical external envelope; internal auth routes keep `ApiEnvelope<T>`
- `AuthUserProfile.avatar_url` may be omitted or `null` when no avatar is configured; populated values remain non-empty strings

## Notes for downstream supervisors
- route-level permission matrices stay within each owned app or service initially
- if multiple supervisors converge on the same claims structure, submit a change request for promotion into `packages/common-auth`
- do not silently widen shared roles or permission names in app-local code; propose them through frozen-space workflow
