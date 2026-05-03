# SmartCloud-X Marketing Service

FastAPI marketing service for campaign browsing, copy generation, promotion links, poster tasks, admin campaign CRUD, tracing, and metrics.

## Implemented routes
- `GET /healthz`
- `GET /readyz`
- `GET /metrics`
- `GET /api/v1/marketing/capabilities`
- `GET /api/v1/marketing/campaigns`
- `POST /api/v1/marketing/copy/generate`
- `GET /api/v1/marketing/copies`
- `GET /api/v1/marketing/copies/{copy_id}`
- `POST /api/v1/marketing/promotion-links/generate`
- `GET /api/v1/marketing/promotion-links`
- `GET /api/v1/marketing/promotion-links/{link_id}`
- `GET /api/v1/marketing/posters`
- `POST /api/v1/marketing/posters`
- `GET /api/v1/marketing/posters/{task_id}`
- `GET /api/v1/marketing/posters/{task_id}/result`
- `GET /api/v1/marketing/admin/campaigns`
- `POST /api/v1/marketing/admin/campaigns`
- `PUT /api/v1/marketing/admin/campaigns/{campaign_id}`
- `DELETE /api/v1/marketing/admin/campaigns/{campaign_id}`

## Tracing
- Enable with `SMARTCLOUD_TRACE_ENABLED=true`
- OTLP exporter endpoint: `OTEL_EXPORTER_OTLP_ENDPOINT`
- Incoming `traceparent` and `X-Trace-Id` are propagated into request tracing
- `/healthz`, `/readyz`, `/metrics` are excluded from tracing

## Metrics
- `marketing_requests_total{operation,status,resource_type}`
- `marketing_request_duration_seconds{operation}`
- `marketing_posters_created_total`
- `marketing_posters_completed_total`
- `marketing_copies_generated_total`
- `marketing_links_generated_total`
- `marketing_idempotency_replays_total`
- `marketing_upstream_errors_total{backend,error_type}`
- `marketing_minio_operations_total{operation,status}`
- `marketing_mongodb_operations_total{operation,status}`
- `marketing_celery_operations_total{operation,status}`
- `marketing_auth_validation_total{status}`
- `marketing_readiness_state`

## Provider configuration
- Copy provider: `MARKETING_COPY_GENERATOR_PROVIDER=template|llm`
- LLM settings: `MARKETING_LLM_API_URL`, `MARKETING_LLM_API_KEY`, `MARKETING_LLM_MODEL`
- Poster provider: `MARKETING_POSTER_GENERATOR_PROVIDER=placeholder|image-service`
- Image settings: `MARKETING_IMAGE_API_URL`, `MARKETING_IMAGE_API_KEY`
- `GET /api/v1/marketing/capabilities` returns active provider information

## Admin vs user routes
- User routes keep published + active campaign visibility only
- Admin routes require `admin:marketing.read` / `admin:marketing.write` and admin subject tokens
- Admin delete is soft-delete via `deleted_at`

## Known limitations
- Template copy remains the default and fallback when LLM config is absent
- Placeholder poster remains the default and fallback when image API config is absent
- `/readyz` now performs live probes for database, MinIO bucket access, MongoDB ping, and Celery broker connectivity; unconfigured backends are reported as disabled and configured-but-unreachable backends degrade readiness with HTTP 503
- Existing architecture still uses a simple store layer and not a scalable query/index redesign

## Validation commands
```bash
PYTHONPATH="/home/ljr/SmartCloud-X/apps/marketing-service:/home/ljr/SmartCloud-X/apps:/home/ljr/SmartCloud-X/packages" /home/ljr/SmartCloud-X/.venv/bin/pytest /home/ljr/SmartCloud-X/apps/marketing-service/tests -q

cd /home/ljr/SmartCloud-X && /home/ljr/SmartCloud-X/.venv/bin/python -m compileall apps/marketing-service/app
```
