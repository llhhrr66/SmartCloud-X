# Local Validation

`supervisor-integration-qa` owns the repo-level validation entrypoints under `tests/`, `scripts/qa/`, `docs/runbooks/`, and `docs/reviews/`.

## Scope of this runbook

Use this runbook for the local execution order that matches the current repository scripts and runtime contracts:

1. prepare environment variables
2. start infra and services
3. verify service and gateway readiness
4. run main-chain acceptance
5. run admin-chain acceptance
6. run full-stack validation and strict release readiness when needed

## Current repository gate status

Current recorded repository evidence is green for the formal gates:

- Round 9 `python3 scripts/qa/gateway_acceptance_probe.py --base-url http://127.0.0.1:8000 --timeout 10` passed `23/23`
- Round 11 `python3 scripts/qa/release_readiness.py --strict` passed with `ok=true`

Use that as the latest repository baseline only. For any new local or candidate environment, rerun the scripts in this runbook instead of inheriting the historical pass result.

## Minimum environment variables by layer

### Required runtime baseline

These are the minimum variables that materially affect local compose and release-style readiness:

- `SMARTCLOUD_MYSQL_DSN`
- `SMARTCLOUD_MONGODB_URI`
- `SMARTCLOUD_MONGODB_DATABASE`
- `SMARTCLOUD_REDIS_URL`
- `SMARTCLOUD_MINIO_ENDPOINT`
- `SMARTCLOUD_MINIO_BUCKET`
- `SMARTCLOUD_MINIO_ACCESS_KEY`
- `SMARTCLOUD_MINIO_SECRET_KEY`
- `SMARTCLOUD_QDRANT_URL`
- `SMARTCLOUD_OPENSEARCH_URL`
- `SMARTCLOUD_JWT_SECRET`
- `VITE_API_BASE_URL`
- `VITE_USE_MOCK_API`
- `VITE_KNOWLEDGE_SERVICE_BASE_URL`
- `VITE_RAG_SERVICE_BASE_URL`
- `VITE_OPERATOR_REASON_HEADER`

### Optional enhancement

- `SMARTCLOUD_DIFY_EXTERNAL_KNOWLEDGE_API_KEY`
- `SMARTCLOUD_DIFY_DATASET_API_BASE_URL`
- `SMARTCLOUD_DIFY_DATASET_API_KEY`
- `SMARTCLOUD_DIFY_DATASET_ID`
- `SMARTCLOUD_EMBEDDING_PROVIDER`
- `SMARTCLOUD_EMBEDDING_API_URL`
- `SMARTCLOUD_EMBEDDING_API_KEY`
- `SMARTCLOUD_EMBEDDING_MODEL`
- `SMARTCLOUD_LLM_API_KEY`
- `SMARTCLOUD_LLM_BASE_URL`
- `SMARTCLOUD_LLM_MODEL`
- `SMARTCLOUD_RAG_CACHE_TTL_SECONDS`
- `SMARTCLOUD_CONNECTOR_TIMEOUT_MS`
- `SMARTCLOUD_INDEX_WORKER_POLL_SECONDS`
- `SMARTCLOUD_INDEX_WORKER_BATCH_SIZE`

- `apps/knowledge-service/app/services/embeddings.py` supports `SMARTCLOUD_EMBEDDING_PROVIDER=openai-compatible`
- when `openai-compatible` is selected, `SMARTCLOUD_EMBEDDING_API_URL`, `SMARTCLOUD_EMBEDDING_API_KEY`, and `SMARTCLOUD_EMBEDDING_MODEL` are all required
- `GET /api/knowledge/v1/embedding:test?text=...` is the runtime verification endpoint
- the stable repository-owned evidence anchor is `docs/status/supervisor-siliconflow-embedding-status.md`
- that document records the current boundary accurately: the code path exists, but the current running live `knowledge-service` has **not** been independently re-verified as switched to SiliconFlow `BAAI/bge-m3`
- therefore do not document the current live localhost service as SiliconFlow-backed unless fresh runtime evidence shows `configuredProvider=openai-compatible` and a non-baseline provider/dimension set

### Observability only

- `SMARTCLOUD_TRACE_ENABLED`
- `SMARTCLOUD_PHOENIX_COLLECTOR_ENDPOINT`
- `OTEL_EXPORTER_OTLP_ENDPOINT`
- `OTEL_EXPORTER_OTLP_PROTOCOL`
- `LANGSMITH_TRACING`
- `LANGSMITH_ENDPOINT`
- `LANGSMITH_PROJECT`
- `LANGSMITH_API_KEY`

### Frontend build variables

`web-user`
- `VITE_API_BASE_URL=http://localhost:8000`
- `VITE_USE_MOCK_API=false`

`web-admin`
- `VITE_KNOWLEDGE_SERVICE_BASE_URL=http://localhost:8031/api/knowledge/v1`
- `VITE_RAG_SERVICE_BASE_URL=http://localhost:8040/api/rag/v1`
- `VITE_OPERATOR_REASON_HEADER=X-Operator-Reason`

## Canonical local ports

| Service | URL |
| --- | --- |
| `gateway-service` | `http://localhost:8000` |
| `auth-user-service` | `http://localhost:8001` |
| `marketing-service` | `http://localhost:8002` |
| `research-service` | `http://localhost:8003` |
| `orchestrator-service` | `http://localhost:8010` |
| `tool-hub-service` | `http://localhost:8020` |
| `business-tools-service` | `http://localhost:8030` |
| `knowledge-service` | `http://localhost:8031` |
| `rag-service` | `http://localhost:8040` |
| `web-admin` | `http://localhost:8050` |
| `web-user` | `http://localhost:3100` |

Alignment rules:

- host-side `knowledge-service` is `http://localhost:8031`
- compose-network `knowledge-service` is `http://knowledge-service:8030`
- `apps/rag-service/app/core/config.py` defaults host-side `KNOWLEDGE_SERVICE_BASE_URL` to `http://localhost:8031`
- `apps/web-admin/src/lib/api.ts` defaults `VITE_KNOWLEDGE_SERVICE_BASE_URL` to `http://localhost:8031/api/knowledge/v1`

## Compose baseline

```bash
cp deploy/docker-compose/.env.example deploy/docker-compose/.env
docker compose -f deploy/docker-compose/docker-compose.yml up --build
```

Recommended validation after startup:

```bash
source scripts/qa/qa_env.sh
smartcloud_qa_init
export SMARTCLOUD_QA_USER_PASSWORD='<qa-user-password>'
export SMARTCLOUD_QA_ADMIN_PASSWORD='<qa-admin-password>'
python3 deploy/docker-compose/smoke-test.py
"${QA_PYTHON[@]}" scripts/qa/gateway_acceptance_probe.py --base-url http://127.0.0.1:8000
```

Optional stronger checks:

```bash
source scripts/qa/qa_env.sh
smartcloud_qa_init
export SMARTCLOUD_QA_USER_PASSWORD='<qa-user-password>'
export SMARTCLOUD_QA_ADMIN_PASSWORD='<qa-admin-password>'
SMARTCLOUD_QA_RUN_COMPOSE=1 SMARTCLOUD_QA_RUN_TRACE=1 scripts/qa/run_full_stack_validation.sh
```

If you need to override the default acceptance identities, also export:

```bash
export SMARTCLOUD_QA_USER_ACCOUNT='<qa-user-account>'
export SMARTCLOUD_QA_ADMIN_USERNAME='<qa-admin-username>'
```


## Manual startup order

Use this order when running services one by one instead of compose:

1. infrastructure: MySQL, MongoDB, Redis, MinIO, Qdrant, OpenSearch, Phoenix
2. base services: auth-user-service, business-tools-service
3. mid-tier: tool-hub-service, knowledge-service, marketing-service, research-service
4. orchestration/retrieval: orchestrator-service, rag-service
5. entry/frontends: gateway-service, web-admin, web-user
6. workers: marketing-worker, knowledge-indexer

## Readiness probe order

Always check service-local readiness before cross-service acceptance.

```bash
curl -sS http://127.0.0.1:8001/readyz | jq .
curl -sS http://127.0.0.1:8002/readyz | jq .
curl -sS http://127.0.0.1:8003/readyz | jq .
curl -sS http://127.0.0.1:8010/readyz | jq .
curl -sS http://127.0.0.1:8020/readyz | jq .
curl -sS http://127.0.0.1:8030/readyz | jq .
curl -sS http://127.0.0.1:8031/readyz | jq .
curl -sS http://127.0.0.1:8040/readyz | jq .
curl -sS http://127.0.0.1:8000/readyz | jq .
```

Interpretation:
- `200` + `status="ready"` means ready for traffic.
- `503` + `status="not_ready"` means blocked; inspect `not_ready_components` or gateway `not_ready_upstreams`.
- irrelevant query parameters must not change readiness semantics.
- for `orchestrator-service`, `GET /healthz` may legitimately report `status="degraded"` while `GET /readyz` remains `status="ready"` when the degraded item is the optional conversation document store (`runtime.conversationStore.documentStore`). In that case, treat `/readyz` as the traffic gate and `/healthz` as diagnostic evidence.

Example tolerance check:

```bash
curl -i "http://127.0.0.1:8031/readyz?probe=1&unused=yes"
```

Embedding-provider spot check when you intend to enable external vectors:

```bash
curl -sS 'http://127.0.0.1:8031/api/knowledge/v1/embedding:test?text=GPU%20probe' | jq .
```

Interpretation for that probe:
- `configuredProvider=hash-baseline` means you are still on the baseline provider
- `configuredProvider=openai-compatible` means the code path is configured for an external OpenAI-compatible provider
- if the current live environment still returns `HashEmbeddingProvider` / `hash-baseline` / `32`, do not claim SiliconFlow live cutover

## Main-chain acceptance order

1. `GET /readyz` on the gateway and verify required upstreams are present.
2. `POST /api/v1/auth/login`
3. `GET /api/v1/auth/me`
4. `POST /api/v1/chat/sessions`
5. `POST /api/v1/chat/completions` with `stream=true`
6. marketing path: `GET /api/v1/marketing/campaigns`
7. research path: `POST /api/v1/research/tasks`
8. tool path: orders / refunds / tickets / ICP / upload policy / complete

Repository probe:

```bash
python3 scripts/qa/gateway_acceptance_probe.py --base-url http://127.0.0.1:8000
```

That probe already asserts:
- gateway `/readyz` is `ready`
- required upstream contracts are `readyz`
- unauthorized chat returns `401`
- chat stream is SSE and does not contain `baseline://`

## Admin-chain acceptance order

Run this only after `knowledge-service` and `rag-service` are ready.

1. open `web-admin` with:
   - `VITE_KNOWLEDGE_SERVICE_BASE_URL=http://localhost:8031/api/knowledge/v1`
   - `VITE_RAG_SERVICE_BASE_URL=http://localhost:8040/api/rag/v1`
2. verify knowledge-base list
3. create and update a knowledge base
4. run `upload init -> upload content -> upload complete -> create document`
5. verify document detail and reindex
6. verify diagnose / answer preview
7. verify admin jobs and audit records

Important:
- admin writes should send `X-Operator-Reason`
- object storage failures should surface as readiness or API errors, not silent success

## Full-stack and release-style commands

Fast repository QA path:

```bash
source scripts/qa/qa_env.sh
smartcloud_qa_init
smartcloud_qa_assert_python_runtime
scripts/qa/run_smoke.sh
```

Full stack:

```bash
scripts/qa/run_full_stack_validation.sh
```

Enable optional phases when the environment supports them:

```bash
SMARTCLOUD_QA_RUN_COMPOSE=1 \
SMARTCLOUD_QA_RUN_TRACE=1 \
SMARTCLOUD_QA_RUN_BROWSER=1 \
scripts/qa/run_full_stack_validation.sh
```

Strict release gate:

```bash
python3 scripts/qa/release_readiness.py --strict
```

`--strict` fails when:
- required artifacts are missing
- focused readiness is not green
- OpenAPI verification is not green
- `docs/reviews/known-issues.md` still contains `critical/high` issues in `open` or `accepted-risk`

| Test name | Proof obligation |
|---|---|
| `test_degraded_response_marks_backend_and_citation_contract` | degraded retrieval response records `backend_used`, keeps `citations == []`, and preserves degraded evidence |
| `test_answer_falls_back_when_no_citations` | answer composition falls back to explicit no-citation guidance instead of fabricating citations |
| `test_retrieve_route_degrades_on_protocol_errors` | `/api/rag/v1/retrieve` stays `200` and marks `degraded=true` when knowledge-service returns a protocol-invalid payload |
| `test_answer_route_degrades_on_upstream_timeout` | `/api/rag/v1/answer` degrades gracefully on upstream timeout and returns explicit coverage notes |

### Mechanical acceptance points

- happy path is not required for this targeted subset; this subset is for degraded-path proof
- degraded retrieval must expose a backend identifier such as `knowledge-service-unavailable`
- protocol errors must not silently become successful citations
- upstream timeout must still produce a coherent degraded answer payload
- empty citation sets must result in fallback guidance, not placeholder citations

### Optional live probe

```bash
curl -sS http://127.0.0.1:8400/readyz | jq .
curl -sS http://127.0.0.1:8400/healthz | jq .
```

Use `/readyz` for traffic gating and `/healthz` for backend/cache diagnostics.

## Knowledge Mixed / Per-Domain Mode Diagnosis

`knowledge-service` exposes `/readyz` as raw readiness JSON and `/healthz` as an `ApiEnvelope`. The runbook goal here is diagnostic clarity, not to assume per-domain mode is always active.

### Mechanical probe

```bash
curl -sS http://127.0.0.1:8300/readyz | jq .
curl -sS http://127.0.0.1:8300/healthz | jq .
```

### What to inspect

- readiness: `status`, `service`, and `not_ready_components`
- runtime payload: repository/index/vector/bm25 connector state as surfaced by the service
- any `runtime.indexTargets`-style payload the service exposes for active target mode
- whether the service reports a mixed/per-domain/single-baseline operating mode in runtime diagnostics

### Interpretation rules

- `ready` does **not** by itself prove per-domain indexing is active.
- `mixed` mode means the service can operate with both baseline and per-domain targets during migration.
- `per-domain` mode means the service reports domain-scoped target selection as active.
- if only baseline targets are visible, record that as current reality rather than assuming the prompt target state is live.

### Release-note wording to reuse

When filing QA evidence, prefer wording like:

- `knowledge-service ready; runtime indicates mixed index target mode`
- `knowledge-service ready; runtime indicates single-baseline target mode`
- `knowledge-service not_ready; vectorStore and runtimeSync blocked`

Avoid wording like `per-domain indexing complete` unless the runtime payload actually proves it.

## Happy Path / Degraded / Not-Ready Mechanical Flow

Execute this sequence in order when preparing a release candidate.

### Step 1: service readiness gates

```bash
curl -fsS http://127.0.0.1:8200/readyz | jq .
curl -fsS http://127.0.0.1:8300/readyz | jq .
curl -fsS http://127.0.0.1:8400/readyz | jq .
curl -fsS http://127.0.0.1:8100/readyz | jq .
```

Pass criteria:

- auth, knowledge, rag, and orchestrator each return `200` with `status="ready"`
- any `503` must be recorded with `not_ready_components`

### Step 2: gateway aggregate gate

```bash
curl -sS http://127.0.0.1:8000/readyz | jq .
```

Pass criteria:

- `data.status == "ready"`
- `data.not_ready_upstreams == []`
- every critical upstream uses `contract == "readyz"`, or any `healthz-fallback` is recorded as an open contract gap

### Step 3: service-level evidence tests

Run the two required targeted pytest commands from the previous sections.

Pass criteria:

- orchestrator proves real citation / degraded / failed / missing-context / stream-event behavior
- rag proves degraded backend evidence / protocol error handling / timeout handling / empty-citation fallback

### Step 4: gateway chat edge checks

Use the gateway evidence tests to confirm external contract handling:

```bash
cd apps/gateway-service
../../.venv/bin/python -m pytest tests/test_gateway_api.py -v --tb=long -k 'test_healthz_and_readyz_summarize_upstreams or test_chat_stream_passthrough_preserves_event_stream_and_stores_citation or test_chat_completions_rejects_non_object_body_with_canonical_4001001 or test_gateway_missing_bearer_token_returns_canonical_401 or test_stream_logging_emits_lifecycle_events_without_payload_leak'
```

Pass criteria:

- SSE proxy keeps citation events and cache behavior intact
- missing bearer returns `401`
- non-object body returns canonical `4001001`
- stream lifecycle logging works without payload leakage

### Step 5: classify the run

Use the following mechanical classification:

- **happy path**: all targeted readiness checks are `ready`, gateway aggregate is `ready`, and targeted pytest evidence passes
- **degraded**: one or more health surfaces are `degraded`, or rag/orchestrator degraded-path tests are the only passing proof while readiness still allows traffic
- **not_ready**: any required service `/readyz` returns `503`, or gateway aggregate `/readyz` returns `503`

## Gateway Path

When the gateway stack is running locally, validate the user-facing unified entry with:

```bash
python scripts/qa/gateway_acceptance_probe.py
```

That probe expects:

- `gateway-service` on `http://127.0.0.1:8000`
- demo auth/admin accounts from `auth-user-service`
- gateway upstreams available for auth, orchestrator, business-tools, marketing, research, knowledge, and rag

## Live Shared-Backend Path

The official QA contract is still localhost/compose-backed shared infra:

```bash
docker compose -f deploy/docker-compose/docker-compose.yml up -d mysql redis minio qdrant opensearch
source scripts/qa/qa_env.sh
smartcloud_qa_init
smartcloud_qa_assert_python_runtime
export SMARTCLOUD_QA_USE_LIVE_INFRA=1
smartcloud_qa_configure_live_infra_env
"${QA_PYTHON[@]}" scripts/qa/project_smoke.py --scenario knowledge-rag-admin
```

Important:

- do not hardcode the external `45.207.220.216` middleware endpoints into repo defaults
- if you temporarily use an external override for diagnosis, document it as an override, not as the repo-owned default path
- `smartcloud_qa_configure_live_infra_env` still injects the canonical localhost defaults for `SMARTCLOUD_QA_SHARED_MYSQL_DSN`, `SMARTCLOUD_QA_SHARED_REDIS_URL`, `SMARTCLOUD_QA_SHARED_RAG_REDIS_URL`, `SMARTCLOUD_QA_SHARED_MINIO_ENDPOINT`, `SMARTCLOUD_QA_SHARED_MINIO_BUCKET`, `SMARTCLOUD_QA_SHARED_QDRANT_URL`, and `SMARTCLOUD_QA_SHARED_OPENSEARCH_URL`
- the SmartCloud MinIO host-port mapping remains `19000/19001`, and the default raw-object endpoint remains `http://127.0.0.1:19000` unless `SMARTCLOUD_MINIO_HOST_PORT` is explicitly overridden

Current workspace limitation:

- Docker Desktop/Linux engine is unavailable here, so the localhost live shared-backend reruns were not refreshed in this turn
- shell-only override reruns against `45.207.220.216` refreshed live `knowledge-rag-admin` successfully, but current live auth/tooling/orchestrator blockers remain real and non-owned

## Release Gate

Use these commands before promoting the current QA baseline:

```bash
"${QA_PYTHON[@]}" scripts/qa/check_release_readiness.py
"${QA_PYTHON[@]}" scripts/qa/release_readiness.py --strict
```

In this workspace, expect release readiness to stay blocked until:

- the live auth MySQL lock-wait / lost-connection failures are fixed by the owning window
- the live business-tools Redis degradation and live orchestrator billing follow-up drift are fixed by the owning window
