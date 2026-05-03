# SmartCloud-X Research Service

- FastAPI baseline for user-facing research task creation, polling, observability, real markdown export artifacts, and placeholder/HTTP-agent-backed report results.
+ FastAPI baseline for user-facing research task creation, polling, observability, real markdown export artifacts, topic/scope/reference-sensitive report generation, and placeholder/HTTP-agent-backed report results.

## Gap analysis
- Task lifecycle: still not a real deep-research pipeline. This round keeps the existing auto-complete demo mode for local/test compatibility, but adds an agent provider abstraction so task completion can be driven by a pluggable provider instead of only time-based simulation.
- Report generation: placeholder content was previously hardcoded in `_build_result()`. It now routes through `ResearchAgentProvider` and produces topic/scope/reference-sensitive summaries, sections, citations, and metadata instead of one fixed template.
- MongoDB runtime: previously only mirrored placeholder payloads. It now stores richer agent result structures when available, but it still does not persist true external-search evidence unless a real agent provides it.
- Idempotency concurrency: previously guarded mainly by in-process `RLock`. This round keeps the unique database constraint and adds retry handling for concurrent insert collisions, but true cross-process exactly-once guarantees still depend on the backing database behavior.
- Auth validation: local JWT checks already covered malformed/expired/wrong-audience tokens. Strict mode still depends on upstream `auth-user-service` state and does not itself own revoked-token storage.
- Observability: previously missing. This round adds OpenTelemetry hooks, Prometheus metrics, `/metrics`, and `/readyz`.
- README/tests/routes consistency: updated for new endpoints and lifecycle behavior.
- Missing tests: added coverage for metrics, capabilities, cancellation, deletion, readiness, concurrent-idempotency path, large topic/scope validation, auth edge cases, Mongo fallback behavior, rendered markdown export artifacts, and non-template report generation variance.

## Implemented routes
- `GET /healthz`
- `GET /readyz`
- `GET /metrics`
- `GET /api/v1/research/tasks`
- `POST /api/v1/research/tasks`
- `GET /api/v1/research/tasks/{task_id}`
- `GET /api/v1/research/tasks/{task_id}/status`
- `GET /api/v1/research/tasks/{task_id}/result`
- `GET /api/v1/research/tasks/{task_id}/report`
- `GET /api/v1/research/capabilities`
- `POST /api/v1/research/tasks/{task_id}/cancel`
- `DELETE /api/v1/research/tasks/{task_id}`

## Runtime notes
- Primary runtime persistence uses `RESEARCH_SERVICE_DATABASE_URL` with shared `SMARTCLOUD_MYSQL_DSN` fallback; local/test runs may still point that setting at SQLite.
- `RESEARCH_SERVICE_BOOTSTRAP_PATH` (legacy alias: `RESEARCH_SERVICE_DATA_PATH`) is migration/bootstrap input only, not the authoritative runtime store.
- Uses shared `SMARTCLOUD_JWT_SECRET`, `SMARTCLOUD_AUTH_ISSUER`, and `SMARTCLOUD_AUTH_AUDIENCE` so access tokens from `auth-user-service` are accepted here.
- Optional strict current-state validation is available via `RESEARCH_SERVICE_AUTH_VALIDATION_MODE=strict` plus `RESEARCH_SERVICE_AUTH_VALIDATE_TOKEN_URL`.
- Async task creation still requires `Idempotency-Key`; duplicate submissions replay the original accepted task id/status while conflicting payload reuse returns `4090001`.
- Tenant/user scoping remains enforced for list/detail/result/cancel/delete.
- `RESEARCH_SERVICE_AUTO_COMPLETE_SECONDS=0` still keeps demo mode in instant-complete behavior for local smoke tests. Positive values still expose `queued -> running -> completed` lifecycle for tasks that do not yet have an agent result.

## Research agent provider configuration
- `RESEARCH_AGENT_PROVIDER=placeholder|http` (default `placeholder`)
+ `RESEARCH_AGENT_PROVIDER=placeholder|http|http_stub` (default `placeholder`)
- `RESEARCH_AGENT_API_URL`
- `RESEARCH_AGENT_API_KEY`
- `RESEARCH_AGENT_TIMEOUT_SECONDS`
- `GET /api/v1/research/capabilities` returns the active provider capabilities and config state.
+ `RESEARCH_AGENT_API_URL`
+ `RESEARCH_AGENT_API_KEY`
+ `RESEARCH_AGENT_TIMEOUT_SECONDS`
+ `RESEARCH_EXTERNAL_SEARCH_PROVIDER=disabled|http_stub`
+ `RESEARCH_EXTERNAL_SEARCH_API_URL`
+ `RESEARCH_EXTERNAL_SEARCH_API_KEY`
+ `RESEARCH_EXTERNAL_SEARCH_TIMEOUT_SECONDS`
+ `GET /api/v1/research/capabilities` returns the active provider capabilities and config state, including the minimal external-search adapter state.

## Tracing configuration
- `SMARTCLOUD_TRACE_ENABLED=1`
- `OTEL_EXPORTER_OTLP_ENDPOINT=http://host:4318` or grpc endpoint
- `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf|grpc`
- `OTEL_SERVICE_NAME=research-service`
- Tracing excludes `/healthz`, `/readyz`, and `/metrics`.
- When tracing is enabled, the service propagates incoming trace context, returns `X-Trace-Id`, and emits a W3C `traceparent` response header derived from the active span context.

## Metrics available
- `research_requests_total{operation,status,depth}`
- `research_request_duration_seconds{operation}`
- `research_tasks_created_total`
- `research_tasks_completed_total`
- `research_idempotency_replays_total`
- `research_upstream_errors_total{backend,error_type}`
- `research_readiness_state`
- `research_mongo_operations_total{operation,status}`
- `task_cancelled_total`

## Task lifecycle states
- `queued`: task row created
- `running`: demo auto-progress path when `RESEARCH_SERVICE_AUTO_COMPLETE_SECONDS > 0`
- `completed`: agent result stored or demo mode auto-completed
- `failed`: agent execution or dependency failure
- `cancelled`: user cancelled task before terminal completion
- `DELETE /api/v1/research/tasks/{task_id}` archives only terminal tasks via `deleted_at`

## Known limitations
- Deep Research Agent is still placeholder by default; HTTP provider is only a stub contract.
- No real external search implementation yet.
- PDF output now writes a minimal valid PDF wrapper and embeds a UTF-8 JSON payload containing the rendered markdown, so the export is a real file and the report body remains stably recoverable even when built-in PDF text rendering is limited.
- No webhook/callback completion notification yet.
- Auto-complete demo mode still exists for local/test compatibility.

## Validation commands
```bash
PYTHONPATH="/home/ljr/SmartCloud-X/apps/research-service:/home/ljr/SmartCloud-X/apps:/home/ljr/SmartCloud-X/packages" \
/home/ljr/SmartCloud-X/.venv/bin/pytest \
/home/ljr/SmartCloud-X/apps/research-service/tests -q

cd /home/ljr/SmartCloud-X && \
/home/ljr/SmartCloud-X/.venv/bin/python -m compileall apps/research-service/app
```
