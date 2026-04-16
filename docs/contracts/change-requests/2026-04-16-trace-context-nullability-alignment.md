# Trace Context Nullability Alignment

## Summary
- requester: supervisor-integration-qa
- date: 2026-04-16
- affected frozen path: `packages/common-schemas/src/schemas/trace-context.schema.json`, `openapi/components.openapi.yaml`, `docs/contracts/shared/api-conventions.md`
- blocking: yes

## Background
The repo-owned heavier QA path now runs subprocess service-stack validation via `scripts/qa/project_smoke.py` and `scripts/qa/run_full_stack_validation.sh` in addition to focused in-process pytest smoke.

During the `knowledge-rag-admin` scenario, QA validates the live `POST /api/knowledge/v1/catalog:bootstrap` response against the frozen shared `TraceContext` contract referenced by the knowledge-service OpenAPI envelope.

## Current Gap
The live knowledge-service bootstrap response currently returns optional trace fields as explicit `null` values when no conversation or caller context exists:

```json
{
  "trace": {
    "requestId": "6e0e0c5b-af7f-4322-885b-45103788869f",
    "traceId": "6e0e0c5b-af7f-4322-885b-45103788869f",
    "conversationId": null,
    "tenantId": null,
    "callerService": null
  }
}
```

The frozen `TraceContext` schema currently allows these optional members only as strings. That causes the full-stack QA contract validation failure:

- `POST /api/knowledge/v1/catalog:bootstrap 200 failed contract validation at trace.conversationId: None is not of type 'string'`

Because the schema is shared/frozen, QA cannot fix the contract locally and cannot make the heavier full-stack validation path green without a frozen-space alignment.

## Proposed Change
Promote additive nullability alignment for optional response trace-context members:

1. allow `conversationId` to be omitted or `null` when no conversation scope exists
2. allow `userId` to be omitted or `null` when no authenticated user scope exists
3. allow `tenantId` to be omitted or `null` when tenant scope is unknown/not attached
4. allow `callerService` to be omitted or `null` when the response was not produced from an internal caller chain
5. allow `toolCallId`, `idempotencyKey`, and `operatorReason` to remain omitted or `null` when not applicable
6. align the shared OpenAPI/component/docs examples so downstream validators and consumers treat missing and explicit `null` as equivalent “unknown context” states for optional trace fields

## Impacted Consumers
- supervisor(s): `supervisor-foundation`, `supervisor-integration-qa`, `supervisor-knowledge-rag`, `supervisor-orchestrator`
- service(s) or surface(s): shared API envelope consumers, knowledge-service responses, any other service that emits `trace` with optional unset fields
- required follow-up work:
  - foundation to update the frozen schema/OpenAPI/docs
  - QA to rerun `scripts/qa/project_smoke.py --scenario knowledge-rag-admin` and `scripts/qa/run_full_stack_validation.sh`

## Compatibility
- breaking or non-breaking: non-breaking additive alignment
- fallback or migration plan: consumers may treat missing and `null` optional trace fields as equivalent unknown-context states until the frozen contract is updated
- temporary workaround already in use: focused in-process smoke avoids the strict live contract check on this knowledge bootstrap response, but the heavier subprocess full-stack path remains blocked

## Evidence
- code reference(s):
  - `packages/common-schemas/src/schemas/trace-context.schema.json`
  - `openapi/components.openapi.yaml#/components/schemas/TraceContext`
  - `scripts/qa/project_smoke.py` (`knowledge-rag-admin` scenario contract validation)
- mock/example/stub reference(s):
  - live QA capture from `POST /api/knowledge/v1/catalog:bootstrap` showing `trace.conversationId = null`, `trace.tenantId = null`, `trace.callerService = null`
- log or failing validation reference(s):
  - `./scripts/qa/run_full_stack_validation.sh` on 2026-04-16 failed in the service-process phase with `trace.conversationId: None is not of type 'string'`

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - aligned the shared `TraceContext` JSON Schema and TypeScript interface so optional scope members (`conversationId`, `userId`, `tenantId`, `callerService`, `toolCallId`, `idempotencyKey`, `operatorReason`) may now be omitted or explicit `null`
  - documented the nullability rule in shared API/foundation docs and added a bootstrap-response OpenAPI example in the knowledge-service placeholder baseline showing `trace` optional fields as explicit `null`
  - hardened foundation validation so the promoted trace-schema nullability cannot silently regress
- deferred:
  - no route-specific payload DTOs were promoted beyond the shared trace-context alignment; owner-local bootstrap body fields remain downstream-owned
- rationale:
  - the live knowledge-service baseline already emits explicit `null` optional trace fields, so frozen shared validation needed to reflect repo reality to unblock QA without forcing owner-local serialization changes
