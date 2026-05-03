# Release Readiness Runbook

## Release gate definition

A SmartCloud-X build is release-ready only when all of the following are true:

1. `scripts/qa/verify_openapi_contracts.py` passes.
2. `scripts/qa/run_full_stack_validation.sh` passes.
3. `pytest tests -q` passes under the QA dependency set.
4. `scripts/qa/release_readiness.py --strict` passes.
5. `docs/reviews/known-issues.md` has no `critical/high` issue in `open` or `accepted-risk` state.
6. status and log artifacts reflect the actual script results.

## Current validated repository state

Latest repository-level gate evidence now shows:

- Round 9 `scripts/qa/gateway_acceptance_probe.py` passed `23/23`
- Round 11 `scripts/qa/release_readiness.py --strict` passed with `ok=true`
- strict output recorded `missingArtifacts=[]`, `focusedReadiness.ok=true`, `focusedReadiness.blockingFailures=[]`, `infraPersistence.summary.failed=0`, and `blockingKnownIssues=[]`

This means the repository currently has recorded passing evidence for both the gateway acceptance gate and the strict release gate. Future release claims must still be tied to fresh script output for the candidate environment being released.

## Current embedding / vector-provider posture

Repository release evidence and external embedding-provider validation are related but not identical:

- the repository gate is currently green based on the recorded Round 9 gateway acceptance result and Round 11 strict readiness result
- `knowledge-service` code does implement an `openai-compatible` embedding path through `apps/knowledge-service/app/services/embeddings.py`
- `GET /api/knowledge/v1/embedding:test` is the runtime probe for that path in `apps/knowledge-service/app/api/routes/knowledge.py`
- `SMARTCLOUD_EMBEDDING_PROVIDER=openai-compatible` requires `SMARTCLOUD_EMBEDDING_API_URL`, `SMARTCLOUD_EMBEDDING_API_KEY`, and `SMARTCLOUD_EMBEDDING_MODEL`; missing any of them raises `EmbeddingConfigurationError`

- `docs/status/supervisor-siliconflow-embedding-status.md` records the stable repository-owned embedding-provider evidence anchor
- that document confirms the code path exists for OpenAI-compatible embedding providers
- that document also records that the current running `knowledge-service` live environment has **not** been independently re-verified as switched to SiliconFlow `BAAI/bge-m3`
- the retained live rerun conclusion showed `SMARTCLOUD_EMBEDDING_PROVIDER/API_URL/API_KEY/MODEL` unset in the running container and `/api/knowledge/v1/embedding:test` returning `configuredProvider=hash-baseline`, `provider=HashEmbeddingProvider`, `dimensions=32`

Therefore:

- do **not** claim that the current live repository evidence proves SiliconFlow `BAAI/bge-m3` is active in the running `knowledge-service`
- do **not** treat the missing live SiliconFlow switch as a contradiction of the current release gate result
- the current release gate passed without requiring a successfully switched SiliconFlow live runtime
- any future claim that live SiliconFlow is enabled must be backed by fresh `/embedding:test`, ingest/search evidence, and the running container environment

## Health vs readiness interpretation note for orchestrator
Current orchestrator runtime evidence can show:
- `/healthz.status="degraded"`
- `/healthz.degraded_components=["conversationStore"]`
- `/readyz.status="ready"`
- `/readyz.not_ready_components=[]`

When this pattern is caused by `runtime.conversationStore.documentStore` being optional for the current environment, it is **not** a traffic-gate failure by itself. Release and QA interpretation must be:
- `/readyz` is the release traffic gate
- `/healthz` remains the diagnostic surface for optional backend degradation
- do not escalate this specific pattern to `not_ready` unless `/readyz` also fails or the document store is marked required for the environment


### Required runtime baseline

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

- `VITE_API_BASE_URL=http://localhost:8000`
- `VITE_USE_MOCK_API=false`
- `VITE_KNOWLEDGE_SERVICE_BASE_URL=http://localhost:8031/api/knowledge/v1`
- `VITE_RAG_SERVICE_BASE_URL=http://localhost:8040/api/rag/v1`
- `VITE_OPERATOR_REASON_HEADER=X-Operator-Reason`

Alignment rules that must be true before any release claim:

- host-side knowledge URL is `http://localhost:8031`
- compose-network knowledge URL is `http://knowledge-service:8030`
- `rag-service` host-side `KNOWLEDGE_SERVICE_BASE_URL` must resolve to `http://localhost:8031` when run outside compose
- `web-admin` knowledge base URL must resolve to `http://localhost:8031/api/knowledge/v1`

## Recommended execution order

Preferred wrapper:

```bash
scripts/qa/run_local_validation.sh
```

Release-style sequence:

```bash
source scripts/qa/qa_env.sh
smartcloud_qa_init
smartcloud_qa_assert_python_runtime
export SMARTCLOUD_QA_USER_PASSWORD='<qa-user-password>'
export SMARTCLOUD_QA_ADMIN_PASSWORD='<qa-admin-password>'
"${QA_PYTHON[@]}" scripts/qa/verify_openapi_contracts.py
scripts/qa/run_full_stack_validation.sh
"${QA_PYTEST[@]}" tests -q
"${QA_PYTHON[@]}" scripts/qa/release_readiness.py --strict
```

If you need non-default acceptance identities, also export:

```bash
export SMARTCLOUD_QA_USER_ACCOUNT='<qa-user-account>'
export SMARTCLOUD_QA_ADMIN_USERNAME='<qa-admin-username>'
```

Enable optional phases for supported environments:

```bash
source scripts/qa/qa_env.sh
smartcloud_qa_init
export SMARTCLOUD_QA_USER_PASSWORD='<qa-user-password>'
export SMARTCLOUD_QA_ADMIN_PASSWORD='<qa-admin-password>'
SMARTCLOUD_QA_RUN_COMPOSE=1 \
SMARTCLOUD_QA_RUN_TRACE=1 \
SMARTCLOUD_QA_RUN_BROWSER=1 \
scripts/qa/run_full_stack_validation.sh
```

## What `run_full_stack_validation.sh` actually runs

The script executes the following sequence:

1. focused smoke baseline via `scripts/qa/run_smoke.sh` with duplicate service-process scenarios disabled
2. service-process acceptance smoke via `scripts/qa/project_smoke.py`
3. optional compose smoke via `deploy/docker-compose/smoke-test.py` when `SMARTCLOUD_QA_RUN_COMPOSE=1`
4. optional trace smoke via `deploy/docker-compose/trace-smoke.py` when `SMARTCLOUD_QA_RUN_TRACE=1`
5. gateway acceptance probe via `scripts/qa/gateway_acceptance_probe.py` unless explicitly disabled
   - requires `SMARTCLOUD_QA_USER_PASSWORD` and `SMARTCLOUD_QA_ADMIN_PASSWORD` in the QA environment
6. optional browser smoke when `SMARTCLOUD_QA_RUN_BROWSER=1`
7. strict release readiness via `scripts/qa/release_readiness.py --strict`

## Main-chain acceptance order inside the release gate

1. gateway `/readyz`
2. auth login / me
3. chat session create
4. chat SSE completion
5. marketing path
6. research path
7. business-tools path: orders, refunds, tickets, ICP, file upload policy, file complete

The gateway acceptance probe now also asserts:
- all required upstreams are present in gateway `/readyz`
- each required upstream uses `contract="readyz"`
- unauthorized chat returns `401`
- chat SSE does not contain `baseline://`

## Admin-chain acceptance order

Run after `knowledge-service` and `rag-service` are both ready:

1. verify `GET /readyz` on knowledge and rag
2. verify `web-admin` base URLs
3. verify knowledge-base list/create/update
4. verify document upload lifecycle and document creation
5. verify reindex / diagnose / answer preview
6. verify admin job and audit lookup

## Minimum evidence to retain

- OpenAPI summary output from `scripts/qa/verify_openapi_contracts.py`
- full-stack output from `scripts/qa/run_full_stack_validation.sh`
- pytest result for `tests/`
- strict readiness JSON from `scripts/qa/release_readiness.py --strict`
- gateway acceptance output
- optional trace smoke output when enabled
- status/review/log updates that match the script outputs
- if external embeddings are claimed, retain `/api/knowledge/v1/embedding:test` output and sanitized runtime configuration evidence

## Strict failure rules

`python3 scripts/qa/release_readiness.py --strict` returns non-zero when any of the following is true:

- required artifacts are missing
- focused readiness is not `ok`
- OpenAPI verification is not `ok`
- `docs/reviews/known-issues.md` contains `critical/high` issues in `open` or `accepted-risk`

## Decision rules

- contract failures: stop and align implementation or frozen contracts
- gateway `/readyz` not ready: stop and treat as a traffic gate failure
- compose smoke / service-process smoke failures: stop and treat as real runtime drift
- missing localhost or live shared-backend proof: do not claim release readiness
- medium/low issues may remain documented, but they do not override strict script failures
- external embedding-provider experiments may remain un-switched in the current live environment without invalidating the already-recorded gate pass, as long as documentation does not misstate them as completed live facts
