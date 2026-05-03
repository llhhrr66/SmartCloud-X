# Known Issues

Last validated: 2026-04-24T12:30:00+08:00 by `doc-release-gate-alignment-round-9`.

> Release-gate rule aligned with `scripts/qa/release_readiness.py --strict`:
> any issue with `Severity=critical|high` and `Status=open|accepted-risk` is a **strict release blocker**.
> Medium/low issues remain documentable risks, but they do not by themselves fail the strict gate.

| ID | Severity | Status | Area | Summary |
| --- | --- | --- | --- | --- |
| QA-001 | medium | resolved | orchestrator-retrieval-citation | `baseline://router-retrieval` must not be treated as proof of successful retrieval or trustworthy citation. Current runtime evidence shows gateway acceptance `chat_stream` is green and gateway-side citation capture rejects `baseline://` URIs, so this is no longer an active strict blocker. Keep review, QA, and release notes distinguishing real `retrieval_result.sources` from older baseline narrative. |
| QA-002 | medium | open | readiness-contract-vs-implementation | Core services now expose a tighter readiness surface, but readiness documentation still must distinguish real code-backed readiness routes from placeholder or draft contracts in OpenAPI/shared docs. Contract presence is not implementation proof. |
| QA-003 | medium | open | knowledge-index-mode | `knowledge-service` may still run in `mixed` index mode during migration. Review docs must not claim full per-domain rollout unless code/runtime evidence proves all writes and queries have left the single-baseline path. |
| QA-004 | medium | open | gateway-chat-boundary | `gateway-service` only proxies chat traffic, captures real citations for cache, emits logs, and normalizes canonical errors. It does not repair or reinterpret incorrect orchestrator streaming semantics. Event meaning defects remain orchestrator-owned. |
| QA-005 | medium | open | orchestrator-streaming-debug-path | For future chat stream event drift, duplicate citations, degraded retrieval semantics, or `message.error`/`retrieval` inconsistencies, check `apps/orchestrator-service/app/services/streaming.py` first. Round 9 runtime evidence shows `chat_stream` acceptance is passing, so this remains review guidance rather than an active strict release blocker. |
| QA-006 | medium | open | orchestration-route-patch-safety | `apps/orchestrator-service/app/api/routes/orchestration.py` remains a high-risk file for future edits. Changes there should still be minimal, uniquely anchored patches after direct code reading. This is process safety guidance, not a currently reproduced release blocker, so it is no longer tracked as a strict blocker. |
| QA-007 | medium | open | pydantic-response-filtering | When a route handler appears to set a field but the final JSON omits it, review the Pydantic response model and serialization filtering first. Do not keep stuffing ad-hoc dict keys into route handlers if the response model drops them. |
| QA-008 | medium | resolved | knowledge-live-connector-proof | Live knowledge/rag connector proof is green in the current state snapshot. This issue now tracks documentation alignment only and is no longer a strict blocker while `knowledge-rag-admin` remains `passed` in `logs/supervisor-integration-qa/state.json`. |
| QA-009 | medium | open | non-goal-langgraph-rewrite | LangGraph replacement, orchestrator framework rewrite, and broad agent-intelligence expansion remain out of scope for the current gap-closure round. Any document claiming those as solved is inaccurate. |
| QA-010 | medium | open | rollback-and-release-risk | Enabling real retrieval and stricter readiness can surface failures that older baseline flows masked. Release review must keep rollback switches and degraded-path expectations explicit rather than assuming identical success rates. |

## Strict Gate Interpretation

`python3 scripts/qa/release_readiness.py --strict` parses the table above and fails when both conditions are true:

1. `Severity` is `critical` or `high`; and
2. `Status` is `open` or `accepted-risk`.

Current blocker set implied by this file:
- none after Round 9 known-issue alignment

With the current table state, this file alone should no longer block `scripts/qa/release_readiness.py --strict`; any remaining strict-gate failure must come from other report sections such as missing artifacts, focused readiness, or OpenAPI checks.

## Current Review Conclusions

### 1. Baseline retrieval is not acceptable citation proof

Code review confirms that stream citations are only trustworthy when they come from structured retrieval data, not from historical baseline markers.

Evidence reviewed:
- `apps/orchestrator-service/app/services/streaming.py`
- `apps/orchestrator-service/app/services/agent_runtime.py`
- `apps/gateway-service/app/api/routes/chat.py`
- `tasks/test-report-round-9.md`
- `logs/supervisor-integration-qa/state.json`

Current review conclusion:
- `gateway-service` only caches citations that look like real entries with evidence such as `backend_used`, `source_id`, `doc_id`, `chunk_id`, or `uri`.
- `apps/gateway-service/app/api/routes/chat.py` explicitly rejects `baseline://` URIs during citation capture.
- Round 9 gateway acceptance passed `23/23`, and the passing `chat_stream` evidence means the baseline citation concern is no longer an active release blocker.
- Review and acceptance materials must still explicitly reject `baseline://router-retrieval` as a success criterion.

### 2. Readiness has improved, but contract maturity still varies

Code reviewed:
- `apps/auth-user-service/app/routes.py`
- `apps/knowledge-service/app/api/routes/health.py`
- `apps/rag-service/app/api/routes/health.py`

Current review conclusion:
- `auth-user-service`, `knowledge-service`, and `rag-service` now expose `/readyz` in code.
- This does not remove the need to separate implemented readiness behavior from placeholder or lagging contract text in OpenAPI/shared docs.
- QA and release review must still check code paths and runtime payloads, not merely route names in contracts.

### 3. Knowledge index migration is not proven complete

Code reviewed:
- `apps/knowledge-service/app/services/indexing_worker.py`

Current review conclusion:
- The worker now resolves index targets through `KnowledgeIndexTargetResolver`.
- That still does not prove production-like runtime is fully per-domain; migration may remain `single-baseline`, `mixed`, or selectively per-domain depending on resolver output and runtime state.
- Review docs must keep using migration language unless connector evidence proves complete cutover.

### 4. Gateway ownership boundary must stay narrow

Code reviewed:
- `apps/gateway-service/app/api/routes/chat.py`
- `apps/orchestrator-service/app/services/streaming.py`

Current review conclusion:
- `gateway-service` validates external request shape, injects user context, proxies to `/internal/v1/orchestrator/chat`, logs stream lifecycle, and caches only citation entries that look real.
- It does not own retrieval semantics, route decisions, or stream event truthfulness.
- If event names or event payload meaning are wrong, the fix belongs in orchestrator, especially `streaming.py`, not in gateway-side payload patching.
- Round 9 gateway acceptance shows this area is currently runtime-green; the remaining note is ownership guidance for future regressions.

### 5. Route-layer patching is a last resort

Code reviewed:
- `apps/orchestrator-service/app/api/routes/orchestration.py`

Current review conclusion:
- This route file is central, large, and high-risk.
- For stream/output defects, review should first inspect response models and event builders before adding more route-layer dict mutation.
- Any required edit must be a minimal, uniquely anchored patch after direct source reading.
- This remains a maintenance constraint, not an independently reproduced strict blocker in the current Round 9 runtime evidence.

## Remaining Risks After This Gap-Closure Round

- Real retrieval enablement can expose upstream `rag-service` and `knowledge-service` failures that older baseline flows masked.
- Readiness routes exist, but release gating can still drift if QA scripts or management reports treat every declared contract as equally mature.
- Mixed knowledge index mode can produce uneven retrieval behavior across domains during migration.
- Stream payload regressions may still occur if downstream consumers assume every `retrieval` event implies successful citations.
- Response serialization gaps can be reintroduced if route handlers bypass typed models and return loosely shaped dicts.
- Shared-backend QA evidence still depends on `SMARTCLOUD_QA_USE_LIVE_INFRA`, tool-hub participation, and repo-root `tests/e2e` coverage staying aligned with the recorded baseline.

## Known Limitations

- Orchestrator is still a baseline router, not a LangGraph runtime.
- Knowledge index governance is not yet proven as a full per-domain rollout.
- Readiness presence does not by itself prove release-grade backend configuration or shared-backend operation.
- Gateway stream handling remains intentionally thin and cannot correct orchestrator event semantics without creating ownership drift.

## Non-Goals For The Current Round

- No full orchestrator framework rewrite.
- No blanket claim that all knowledge data has migrated to per-domain collections/indexes.
- No claim that OpenAPI or shared schema maturity automatically equals runtime completion.
- No gateway-side semantic repair layer for malformed orchestrator stream events.

## Rollback Notes

- If real retrieval increases chat failures, first evaluate orchestrator retrieval integration and `streaming.py` event shaping before altering gateway behavior.
- If readiness gating blocks environments unexpectedly, verify whether the environment is genuinely `not_ready` or whether docs/contracts are overstating readiness maturity.
- If fields disappear from JSON after route changes, inspect Pydantic response models and serialization rules before patching route dict assembly.
- If orchestration route fixes are unavoidable, use minimal search-and-replace edits in `apps/orchestrator-service/app/api/routes/orchestration.py`; do not overwrite the full file.
