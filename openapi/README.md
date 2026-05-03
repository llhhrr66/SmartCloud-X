# OpenAPI Contract Maturity Guide

Foundation owns this directory as the landing zone for shared and service-level API specifications.

## Why this README exists

These files are **contract artifacts**, not implementation proof.

A route or schema can exist in OpenAPI while the live code is still:
- not implemented,
- implemented only as a baseline,
- implemented in one service but not yet frozen across shared schemas,
- or still owned by a downstream service that has not promoted field-level details into foundation-owned contract space.

Always separate two questions:

1. **Contract maturity**: how stable and explicit the OpenAPI/shared-schema contract is.
2. **Implementation completion**: whether real code, tests, and runtime evidence prove the behavior is delivered.

Do **not** treat `draft`, `placeholder`, or `baseline` OpenAPI text as evidence that a feature is complete.

## Maturity labels used in this repo

### `implemented`
Meaning: the contract item is backed by current code and has direct implementation evidence, typically including route code and tests.

Use when:
- the path/schema is live in code, and
- the documented behavior is constrained to what code and tests actually prove.

Important: `implemented` here describes **contract alignment with live code**, not necessarily “product fully finished”. A contract can be implemented while the broader feature remains limited or below target architecture.

### `placeholder`
Meaning: a reserved path/component/DTO shell exists, but the spec intentionally does not claim field-complete or behavior-complete implementation.

Use when:
- the route family is known,
- the owner service may have code, but
- this OpenAPI file is still a draft landing zone, incomplete schema, or route reservation.

A `placeholder` contract must never be read as “already delivered”.

### `baseline`
Meaning: the contract describes a currently used minimal or compatibility surface, but not the final target architecture or final semantics.

Use when:
- a route/DTO exists and is useful today,
- but semantics are still compatibility-oriented, migration-oriented, or intentionally narrow.

`baseline` is stronger than `placeholder`, but weaker than `frozen`.

### `owner-defined`
Meaning: the route family is known, but field-level payload ownership still sits with the downstream service owner rather than a foundation-frozen shared contract.

Use when:
- this directory points to a live owner-owned surface,
- but the exact DTO shape remains downstream-owned,
- and shared/common-schemas have not yet promoted the field set into a foundation-frozen artifact.

### `frozen`
Meaning: the contract shape is intentionally stable and should be reused rather than redefined in parallel.

Use when:
- the field set is shared across services/SDK/QA,
- the schema is published in `components.openapi.yaml` and/or `packages/common-schemas`, and
- changes should go through change review.

`frozen` is still **not** the same as “fully implemented everywhere”. It only means the contract is stable.

## Contract maturity vs implementation completion

Use the following decision grid when reading any file in this directory:

| Question | What to check | What not to assume |
| --- | --- | --- |
| Is the contract mature? | OpenAPI text, shared components, common schema presence, README/schema-catalog notes | That mature contract text proves the runtime exists |
| Is the implementation complete? | Route code, tests, status docs, runbooks, release evidence | That draft/placeholder/baseline contracts equal shipped functionality |

Examples:
- A path can be **`placeholder` contract maturity** while the downstream service already has partial code.
- A schema can be **`frozen` contract maturity** while some services still lag in adopting it.
- A route can be **`implemented` contract maturity** but still only represent a **baseline** product capability.

## Current directory baseline

Current baseline now includes:
- `components.openapi.yaml` for shared headers, response headers, reusable responses, shared internal schemas, canonical external envelope schemas, and pagination parameters
- route baselines for orchestrator, tool-hub, business-tools, auth-user, knowledge, rag, marketing, and research service surfaces
- current health/runtime route documentation, including services that now expose `/healthz` and `/readyz` in code
- admin and user-facing placeholder/baseline specs where the path family is known but field ownership or implementation maturity still varies by service

These files are still **draft contracts overall**, but they are no longer empty stubs. Downstream supervisors should extend them through the change-request workflow instead of maintaining parallel contract definitions elsewhere.

## Readiness contract maturity map

### Foundation-frozen shared readiness schemas
Prefer reusing the existing root-level shared schemas under `packages/common-schemas/src/schemas/`:
- `runtime-readiness-status.schema.json` — **frozen** shared readiness body
- `runtime-dependency-readiness.schema.json` — **frozen** shared downstream dependency readiness body
- `runtime-health-status.schema.json` — **baseline** shared health payload
- `health-status.schema.json` — **baseline** generic liveness/degraded status

Do **not** create parallel readiness schema families when these root-level files already cover the concern.

### Service OpenAPI readiness maturity

| Surface | Contract maturity | Implementation completion note |
| --- | --- | --- |
| gateway `/readyz` aggregation | implemented | Backed by live route code and tests; still only reports upstream probe truth, not product completion. |
| orchestrator `/readyz` | implemented | Backed by live route code and readiness tests. |
| auth-user `/readyz` | implemented | Live route now exists in `apps/auth-user-service/app/routes.py`; completion must still be judged from code/tests/runtime evidence, not path presence alone. |
| knowledge `/readyz` | implemented | Live route now exists in `apps/knowledge-service/app/api/routes/health.py`; does not by itself prove full per-domain backend readiness. |
| rag `/readyz` | implemented | Live route now exists in `apps/rag-service/app/api/routes/health.py`; readiness still depends on actual upstream/runtime state. |
| Older service-level OpenAPI health text that still reads like guidance or liveness-only notes | placeholder or baseline | Must not be read as proof that release-grade readiness semantics are complete. |

Evidence basis for the implemented readiness entries above:
- route code: `apps/auth-user-service/app/routes.py`, `apps/knowledge-service/app/api/routes/health.py`, `apps/rag-service/app/api/routes/health.py`, `apps/gateway-service/app/api/routes/health.py`, `apps/orchestrator-service/app/api/routes/health.py`
- gateway readiness aggregation test: `apps/gateway-service/tests/test_gateway_api.py::test_healthz_and_readyz_summarize_upstreams`
- orchestrator readiness tests: `apps/orchestrator-service/tests/test_api.py::test_readyz_reports_ready_when_runtime_is_healthy` and related `not_ready` cases
- status/review alignment: `docs/reviews/known-issues.md`, `docs/runbooks/release-readiness.md`

## Retrieval contract maturity map

### Shared/common-schema retrieval artifacts
Current real shared schema locations:
- `packages/common-schemas/src/schemas/internal/rag/retrieval-result.schema.json` — **baseline** shared retrieval result contract for internal rag → orchestrator exchange
- `packages/common-schemas/src/schemas/internal/orchestrator/stream-retrieval-event-data.schema.json` — **baseline** shared orchestrator retrieval stream event contract
- `packages/common-schemas/src/schemas/internal/orchestrator/stream-retrieval-source.schema.json` — **baseline** shared retrieval source item contract
- `packages/common-schemas/src/schemas/external/admin/retrieval-diagnostics-data.schema.json` — **baseline** admin diagnostics DTO
- `packages/common-schemas/src/schemas/external/admin/retrieval-search-preview-data.schema.json` — **baseline** admin preview DTO
- `packages/common-schemas/src/schemas/external/admin/retrieval-search-source.schema.json` — **baseline** admin retrieval source DTO

These are **not** proof that the entire product retrieval chain is at target-state maturity. They only describe the currently promoted contract surface.

### Service OpenAPI retrieval maturity

| Surface | Contract maturity | Implementation completion note |
| --- | --- | --- |
| orchestrator internal retrieval/citation stream fields | implemented + baseline | Live code and tests prove real retrieval/citation behavior now exists, but orchestrator remains a baseline router rather than a final intelligent orchestration core. |
| rag internal retrieve DTO | baseline | Shared schema exists and live behavior is test-backed for degraded/no-citation semantics, but additive fields remain possible and owner evolution still exists. |
| knowledge/rag admin retrieval diagnostics | baseline | Useful and live in current service surfaces, but not equivalent to end-user chat-chain completion. |
| any retrieval DTO section still described as opaque/downstream-owned in service specs | owner-defined | Do not infer field completeness from route presence alone. |

Evidence basis for retrieval maturity notes:
- orchestrator tests: `apps/orchestrator-service/tests/test_api.py::test_internal_orchestrator_chat_uses_real_rag_citations_on_success`, `::test_internal_orchestrator_chat_marks_degraded_retrieval_without_baseline_placeholder`, `::test_internal_orchestrator_chat_returns_failed_when_rag_hard_failure_occurs`, `::test_orchestrate_message_stream_emits_spec_like_events`
- shared schema files listed above
- status alignment: `docs/status/supervisor-orchestrator-status.md`, `docs/status/supervisor-knowledge-rag-status.md`

## Explicit non-claims required by review and QA

The following statements are intentionally **not** allowed in this directory:

- Do not describe `baseline://router-retrieval` as valid retrieval success evidence or trustworthy citation proof.
- Do not describe knowledge indexing as fully per-domain unless runtime evidence proves the single-baseline path is gone.
- Do not describe gateway as repairing or redefining orchestrator event meaning; gateway proxies and normalizes, but event semantics remain orchestrator-owned.
- Do not describe readiness route presence as equivalent to release-grade shared-backend completion.

These limits align with:
- `docs/status/supervisor-orchestrator-status.md`
- `docs/status/supervisor-knowledge-rag-status.md`
- `docs/reviews/known-issues.md`
- `docs/runbooks/release-readiness.md`

## Change policy

When updating these specs:
- label major route families or component groups with one of: `implemented`, `placeholder`, `baseline`, `owner-defined`, `frozen`
- explicitly say whether you are talking about **contract maturity** or **implementation completion**
- cite code/tests/status evidence before upgrading a readiness or retrieval item to `implemented`
- prefer existing root-level readiness schemas over adding parallel equivalents
- do not promote owner-defined payloads into frozen shared contract space until field ownership is actually reviewed and aligned
