# Supervisor Orchestrator Status

## Status
- phase: completed-runtime-readiness-probes
- result: owned middleware-backed runtime paths now surface strict `/readyz` readiness across orchestrator, tool-hub, and business-tools, including live downstream HTTP dependency checks for the orchestrator -> tool-hub -> business-tools chain, and full owned validation is green

## Completed
- added additive `GET /readyz` routes across `apps/orchestrator-service`, `apps/tool-hub-service`, and `apps/business-tools` so degraded runtime backends and unavailable downstream HTTP dependencies now return explicit 503 readiness failures
- extended orchestrator and tool-hub `/healthz` runtime payloads with nested `dependencyReadiness` metadata for the `toolHubTransport` and `businessToolsTransport` sections, backed by real short-timeout downstream readiness probes
- kept lazy local business-tools fallback behavior intact by treating inactive local runtimes as acceptable on the HTTP mainline while still failing readiness when the required downstream service is unreachable or not ready
- added readiness/client regression coverage across owned services and revalidated the full owned pytest suites plus compileall
- performed self-review, fixed a review-found per-request orchestrator health client instantiation inefficiency by reusing a module-level `ToolHubClient`, and filed `docs/contracts/change-requests/2026-04-16-runtime-readiness-health-baseline.md` for frozen follow-up

## Validation
- `apps/orchestrator-service`: `PYTHONPATH=. /home/ljr/SmartCloud-X/.venv/bin/pytest tests/test_tool_hub_client.py tests/test_api.py -q` -> `60 passed`
- `apps/tool-hub-service`: `PYTHONPATH=. /home/ljr/SmartCloud-X/.venv/bin/pytest tests/test_business_tools_client.py tests/test_api.py -q` -> `57 passed`
- `apps/business-tools`: `PYTHONPATH=src /home/ljr/SmartCloud-X/.venv/bin/pytest tests/test_service_app.py -q` -> `29 passed`
- `apps/orchestrator-service`: `PYTHONPATH=. /home/ljr/SmartCloud-X/.venv/bin/pytest tests -q` -> `153 passed`
- `apps/tool-hub-service`: `PYTHONPATH=. /home/ljr/SmartCloud-X/.venv/bin/pytest tests -q` -> `82 passed`
- `apps/business-tools`: `PYTHONPATH=src /home/ljr/SmartCloud-X/.venv/bin/pytest tests -q` -> `83 passed`
- owned services: `/home/ljr/SmartCloud-X/.venv/bin/python -m compileall apps/orchestrator-service/app apps/tool-hub-service/app apps/business-tools/src` -> passed

## Blockers / Risks
- no blocking implementation issue remains in owned scope
- orchestrator/tool-hub `/readyz` now intentionally returns 503 in HTTP mode when `tool-hub-service` or `business-tools-service` is absent or not ready, so single-service bring-up must switch transport to `local` or accept failing readiness until dependencies are started
- backend recovery still happens lazily on the next owned operation or health probe with a short retry backoff, so operators need readiness polling or real traffic after infra restoration to repromote runtime authority
- degraded local state is only re-imported under the stores' existing freshness or append-safe merge rules; semantically conflicting multi-writer fallback snapshots still require operator review
- additive `/readyz` routes and nested transport `dependencyReadiness` metadata are pending frozen promotion via `docs/contracts/change-requests/2026-04-16-runtime-readiness-health-baseline.md`
- `BUSINESS_TOOLS_REDIS_NAMESPACE` discoverability in the frozen runtime-config baseline is pending foundation review of `docs/contracts/change-requests/2026-04-16-business-tools-redis-namespace-alignment.md`
- operator-managed MySQL/Redis availability, schema migration, namespace cleanup, and degraded spool retention remain pending outside owned service code

## Integration Points
- orchestrator-service `/healthz` now reports downstream `toolHubTransport.dependencyReadiness`, and `/readyz` fails when orchestrator middleware or the required tool-hub HTTP dependency is not ready
- tool-hub-service `/healthz` now reports downstream `businessToolsTransport.dependencyReadiness`, and `/readyz` fails when tool-hub MySQL audit storage or the required business-tools HTTP dependency is not ready
- business-tools-service `/readyz` now turns Redis idempotency/query-cache degradation into an explicit readiness failure for downstream callers and load balancers
- `docs/contracts/change-requests/2026-04-16-runtime-readiness-health-baseline.md` and `docs/contracts/change-requests/2026-04-16-business-tools-redis-namespace-alignment.md` are the current outstanding frozen-contract follow-ups for the owned runtime/health work
