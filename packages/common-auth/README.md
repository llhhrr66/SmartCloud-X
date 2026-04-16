# @smartcloud-x/common-auth

Foundation-owned authentication contract placeholders.

Current baseline:
- shared roles and starter permission codes
- canonical admin RBAC starter permissions aligned with spec section 20.14, including `admin:kb.*`, `admin:ticket.*`, `admin:refund.*`, `admin:prompt.*`, `admin:eval.*`, and `admin:job.read`
- expanded end-user/business permissions aligned with the current web-user spec baseline:
  - `user:order.read`
  - `user:ticket.read`
  - `user:ticket.write`
  - `user:icp.read`
  - `user:icp.write`
  - `user:marketing.read`
  - `user:marketing.write`
  - `user:research.read`
  - `user:research.write`
- JWT issuer/audience defaults aligned with `.env.example`
- helpers for Bearer parsing, internal caller header construction, permission alias normalization, and permission checks
- contract-only access-state markers for auth/bootstrap routes: `anonymous`, `authenticated:user`, `authenticated:admin`
- `buildInternalAuthHeaders(...)` now preserves optional `X-Tool-Call-Id`, `Idempotency-Key`, and `X-Operator-Reason` propagation fields
- internal caller names sourced from `@smartcloud-x/common` so all in-repo services, contract-placeholder services, and the reserved gateway identity stay aligned with frozen contracts
- legacy `admin:knowledge.read/write` permissions are normalized to canonical `admin:kb.read/write` so older downstream consumers remain compatible during migration

Any non-trivial auth flow changes should come through `docs/contracts/change-requests/` first.
