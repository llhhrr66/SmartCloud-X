# @smartcloud-x/common

Foundation-owned shared constants and lightweight cross-project helpers.

Current baseline:
- service ownership descriptors with workspace paths, canonical API base paths, and legacy/internal aliases where they exist
- platform service descriptors for active services, contract-placeholder services with assigned owner metadata (`auth-user-service`, `marketing-service`, `research-service` -> `supervisor-auth-marketing-research`), and the reserved `gateway-service` identity
- shared supervisor helpers aligned with the current seven-supervisor workspace model:
  - `serviceOwningSupervisorNames` for the five service-owning delivery supervisors
  - `sharedScopeSupervisorNames` for `supervisor-frontend-sdk` and `supervisor-integration-qa`
  - `SupervisorName` / `supervisorNames` / type guards covering the full ownership registry
- internal caller names for all in-repo service identities plus the gateway entrypoint
- shared request and response header names used across internal contracts, including tool-call propagation headers and the admin operator-reason audit header
- frozen-path and shared env-key constants for downstream integration checks, including configurable tool-call/idempotency/operator-reason header names, provider-backed internal prefix override keys, and the shared browser CORS allow-list key
- root-level import aliases reserved via `tsconfig.base.json`

This package stays intentionally lightweight. Domain DTOs belong in `@smartcloud-x/common-schemas`.
