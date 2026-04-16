# Phoenix Placeholder

Phoenix is included in the Compose baseline as the tracing UI for the current knowledge and RAG flows.

## Current state
- the service is started so local operators have a reserved endpoint at `http://localhost:6006`
- `knowledge-service` emits OTLP spans for request handling plus ingestion, bootstrap, search, and filesystem-import child operations when `SMARTCLOUD_TRACE_ENABLED=true`
- `rag-service` emits OTLP spans for request handling plus retrieval orchestration, outbound `knowledge-service` search calls, and answer composition when `SMARTCLOUD_TRACE_ENABLED=true`
- compose passes `SMARTCLOUD_PHOENIX_COLLECTOR_ENDPOINT`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_PROTOCOL`, and `SMARTCLOUD_TRACE_ENABLED` into the backend containers so tracing is active by default in the local stack
- `/healthz` and `/metrics` are intentionally excluded from tracing so Phoenix stays focused on operator and retrieval flows rather than probe traffic

## Practical usage
- start the compose stack and exercise `web-admin` or `deploy/docker-compose/smoke-test.py`
- open Phoenix at `http://localhost:6006`
- filter for service names `smartcloud-x-knowledge-service` and `smartcloud-x-rag-service` to inspect the cross-service trace path
- when you want a collector-level QA check before opening Phoenix, run `python3 deploy/docker-compose/trace-smoke.py`; it uses a temporary OTLP collector and fails if ingestion/answer flows do not emit trace batches

## Next step
- add model-provider or LangChain spans once the baseline moves beyond deterministic answer composition
- promote any consistently useful Phoenix attributes into shared observability guidance after the broader platform agrees on naming
