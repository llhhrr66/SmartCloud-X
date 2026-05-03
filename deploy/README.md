# Deploy Baseline

This directory contains the current runnable deployment baseline for SmartCloud-X local integration. The baseline is centered on `deploy/docker-compose/docker-compose.yml`, the QA scripts under `scripts/qa/`, and the runtime readiness contracts implemented by the backend services.

## Included
- `docker-compose/docker-compose.yml`: local stack for gateway-service, web-user, auth-user-service, marketing-service, `marketing-worker`, research-service, business-tools-service, tool-hub-service, orchestrator-service, knowledge-service, `knowledge-indexer`, rag-service, web-admin, Redis, MySQL, MongoDB, Qdrant, OpenSearch, MinIO, Phoenix, Prometheus, Grafana, and cAdvisor
- `docker-compose/.env.example`: local stack variables for the compose baseline
- `docker-compose/smoke-test.py`: compose-level smoke validation
- `docker-compose/trace-smoke.py`: OTLP trace smoke validation for `knowledge-service` and `rag-service`
- `k8s/README.md`: next-step notes for Kubernetes mapping

## Canonical host ports

| Service | Host URL | Notes |
| --- | --- | --- |
| `gateway-service` | `http://localhost:8000` | unified user-facing API entry |
| `auth-user-service` | `http://localhost:8001` | login / token validation |
| `marketing-service` | `http://localhost:8002` | campaigns / poster workflow |
| `research-service` | `http://localhost:8003` | research task workflow |
| `orchestrator-service` | `http://localhost:8010` | chat orchestration + SSE |
| `tool-hub-service` | `http://localhost:8020` | tool discovery / invoke |
| `business-tools-service` | `http://localhost:8030` | orders / refunds / tickets / ICP |
| `knowledge-service` | `http://localhost:8031` | host port is `8031`; container listens on `8030` |
| `rag-service` | `http://localhost:8040` | retrieval / answer / diagnostics |
| `web-admin` | `http://localhost:8050` | direct to knowledge/rag |
| `web-user` | `http://localhost:3100` | should call gateway |
| `Phoenix` | `http://localhost:6006` | tracing UI |
| `Prometheus` | `http://localhost:9090` | metrics |
| `Grafana` | `http://localhost:3000` | dashboards |
| `MinIO console` | `http://localhost:9001` | object storage console |

## Startup order

Bring services up in this order when debugging manually. The compose file already encodes most of this through `depends_on` and healthchecks.

1. Infrastructure: `mysql`, `mongo`, `redis`, `minio`, `qdrant`, `opensearch`, `phoenix`
2. Base business services: `auth-user-service`, `business-tools-service`
3. Mid-tier services: `tool-hub-service`, `knowledge-service`, `marketing-service`, `research-service`
4. Orchestration and retrieval: `orchestrator-service`, `rag-service`
5. Entry and frontends: `gateway-service`, `web-admin`, `web-user`
6. Workers: `marketing-worker`, `knowledge-indexer`

A container being `running` is not enough. Use `/readyz` and the smoke scripts as the real gate.

## Environment variable layers

### 1. Required for runnable compose / release-candidate style validation

These variables are the minimum runtime baseline that materially affects readiness and acceptance:

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

Compose defaults many of these for local use, but release-candidate environments must provide real values instead of relying on local fallback semantics.

### 2. Optional enhancement

These enable richer runtime behavior but are not required for the compose baseline to start:

- `SMARTCLOUD_RAG_CACHE_ENABLED`
- `SMARTCLOUD_RAG_CACHE_TTL_SECONDS`
- `SMARTCLOUD_CONNECTOR_TIMEOUT_MS`
- `SMARTCLOUD_INDEX_WORKER_POLL_SECONDS`
- `SMARTCLOUD_INDEX_WORKER_BATCH_SIZE`
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

If an enhancement is enabled, missing companion variables must still fail clearly at runtime.

### 3. Observability only

These control tracing and telemetry rather than business readiness:

- `SMARTCLOUD_TRACE_ENABLED`
- `SMARTCLOUD_PHOENIX_COLLECTOR_ENDPOINT`
- `OTEL_EXPORTER_OTLP_ENDPOINT`
- `OTEL_EXPORTER_OTLP_PROTOCOL`
- `LANGSMITH_TRACING`
- `LANGSMITH_ENDPOINT`
- `LANGSMITH_PROJECT`
- `LANGSMITH_API_KEY`

### 4. Frontend build variables

`web-user`:
- `VITE_API_BASE_URL=http://localhost:8000`
- `VITE_USE_MOCK_API=false`

`web-admin`:
- `VITE_KNOWLEDGE_SERVICE_BASE_URL=http://localhost:8031/api/knowledge/v1`
- `VITE_RAG_SERVICE_BASE_URL=http://localhost:8040/api/rag/v1`
- `VITE_OPERATOR_REASON_HEADER=X-Operator-Reason`

## Port and base-URL alignment rules

These values must stay aligned with the current code:

- `knowledge-service` host port is `8031`; do not point host-side clients at `http://localhost:8030` for knowledge.
- `knowledge-service` still listens on `8030` inside the compose network.
- `rag-service` host-side upstream to knowledge should be `KNOWLEDGE_SERVICE_BASE_URL=http://localhost:8031` when run outside containers.
- `rag-service` container-side upstream to knowledge should be `KNOWLEDGE_SERVICE_BASE_URL=http://knowledge-service:8030` when run inside compose.
- `web-admin` knowledge base URL default must be `http://localhost:8031/api/knowledge/v1`.

## Standard compose flow

```bash
cp deploy/docker-compose/.env.example deploy/docker-compose/.env
docker compose -f deploy/docker-compose/docker-compose.yml up --build
python3 deploy/docker-compose/smoke-test.py
python3 scripts/qa/gateway_acceptance_probe.py --base-url http://127.0.0.1:8000
```

Optional stronger validation:

```bash
python3 deploy/docker-compose/trace-smoke.py
SMARTCLOUD_QA_RUN_COMPOSE=1 SMARTCLOUD_QA_RUN_TRACE=1 scripts/qa/run_full_stack_validation.sh
python3 scripts/qa/release_readiness.py --strict
```

## Acceptance order

### Main chain
1. Check service `/readyz` endpoints.
2. Check `gateway-service /readyz` and verify required upstreams are all on the `readyz` contract.
3. Log in through `POST /api/v1/auth/login`.
4. Run `scripts/qa/gateway_acceptance_probe.py`.
5. Verify chat/session/SSE, marketing, research, and business-tools paths through gateway.

### Admin chain
1. Verify `knowledge-service /readyz` and `rag-service /readyz`.
2. Open `web-admin` on `http://localhost:8050`.
3. Validate knowledge-base list/create/update.
4. Validate upload lifecycle: `upload init -> upload content -> upload complete -> create document`.
5. Validate reindex, diagnose, answer preview, admin jobs, and audit queries.

## Release-style commands

Use the repository QA entrypoints as the final gate:

```bash
scripts/qa/run_full_stack_validation.sh
python3 scripts/qa/release_readiness.py --strict
```

`--strict` fails whenever `docs/reviews/known-issues.md` still contains `critical/high` issues in `open` or `accepted-risk` state.

## Readiness behavior
- Compose healthchecks use `/readyz` semantics for most services and should be read together with direct runtime probes.
- `knowledge-service` readiness covers repository/runtime state plus connector availability.
- `rag-service` readiness depends on live knowledge readiness, not just process liveness.
- `gateway-service /readyz` is the traffic gate for the system view; fallback to `/healthz` is not release-ready evidence.
