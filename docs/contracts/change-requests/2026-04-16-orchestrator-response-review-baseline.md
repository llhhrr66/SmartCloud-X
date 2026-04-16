# Change Request

## Summary
- requester: supervisor-orchestrator
- date: 2026-04-16
- affected frozen path: `docs/contracts/shared/schema-catalog.md` and related frozen orchestrator schemas/OpenAPI placeholders
- blocking: no

## Background
Owned orchestrator code now materializes the spec's `review_answer` phase as a lightweight response-review baseline. The orchestrator computes a structured review result after agent/tool execution, persists that review into the session snapshot, and can force `retry-or-escalate` when a response violates basic guard conditions such as missing citations on retrieval-required routes, missing handoff reasons, or agent tool-policy violations.

## Current Gap
Frozen shared contracts do not yet describe:
- additive orchestrator response/state fields such as `review.status`, `review.summary`, `review.issues[]`, and `review.requires_escalation`
- additive execution event `review_result`
- the additive `review-answer` checkpoint name used by the current orchestrator baseline

Without promotion, owned services can emit the new review metadata immediately, but shared schema/OpenAPI validation cannot treat it as a documented cross-service baseline.

## Proposed Change
Promote additive orchestrator review metadata into frozen shared schemas/OpenAPI:
1. add a reusable `ResponseReview` / `ResponseReviewIssue` schema family
2. allow additive `review` blocks on orchestrator response payloads and session-state snapshots
3. document the additive `review_result` execution-event variant and `review-answer` checkpoint name
4. note that the current baseline only enforces lightweight policy checks and is not yet a full human-approval workflow

## Impacted Consumers
- supervisor(s): supervisor-orchestrator, supervisor-foundation
- service(s) or surface(s): orchestrator-service, gateway-service, admin/debug consumers of session state
- required follow-up work: foundation promotion into frozen schemas/OpenAPI once the additive review metadata is accepted

## Compatibility
- breaking or non-breaking: non-breaking additive
- fallback or migration plan: consumers may ignore the new `review` metadata until they are ready to surface it
- temporary workaround already in use: owned orchestrator routes and state snapshots emit the new metadata app-locally without editing frozen files

## Evidence
- code reference(s):
  - `apps/orchestrator-service/app/services/review.py`
  - `apps/orchestrator-service/app/api/routes/orchestration.py`
  - `apps/orchestrator-service/app/models/orchestration.py`
- mock/example/stub reference(s):
  - `apps/orchestrator-service/tests/test_review.py`
  - `apps/orchestrator-service/tests/test_api.py`
- log or failing validation reference(s):
  - current frozen contract/OpenAPI coverage does not mention review metadata even though the owned orchestrator baseline now persists it

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - added reusable shared `ResponseReview` / `ResponseReviewIssue` schema and TypeScript baselines under `packages/common-schemas`
  - promoted additive `review` fields onto shared orchestrator response, state-snapshot, and internal-chat contracts plus the `review_result` execution-event variant
  - documented the current `review-answer` checkpoint marker in frozen schema/OpenAPI/docs coverage and hardened validator enforcement so the review baseline cannot silently regress
