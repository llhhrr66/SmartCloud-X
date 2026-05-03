# LangSmith Runtime Status

LangSmith is now wired to the `orchestrator-service` core message / tool path through the LangSmith Python SDK.

## Current state
- `apps/orchestrator-service` now configures `LANGSMITH_TRACING`, `LANGSMITH_ENDPOINT`, `LANGSMITH_PROJECT`, and `LANGSMITH_API_KEY` through `app.core.langsmith.configure_langsmith_env()`
- `apps/orchestrator-service/app/api/routes/orchestration.py` now opens a per-message `tracing_context(...)` and traces `_run_orchestration`
- `apps/orchestrator-service/app/services/tool_hub_client.py` now traces `invoke_plan` and `preflight`, so one core agent -> tool path can appear in LangSmith as nested runs
- compose now passes the same `LANGSMITH_*` variables into `orchestrator-service`
- Phoenix / Prometheus / Grafana remain active local observability paths; LangSmith is now integration-ready on a real orchestrator path instead of env-only placeholder wiring

## Current blocker
- the current workstation / repo environment does not expose `LANGSMITH_API_KEY`, so this thread cannot complete a live trace upload proof yet
- without a real API key, the correct current state is `blocked-external` rather than `completed`

## Next step
- export:
  - `LANGSMITH_TRACING=true`
  - `LANGSMITH_ENDPOINT=https://api.smith.langchain.com`
  - `LANGSMITH_PROJECT=smartcloud-x`
  - `LANGSMITH_API_KEY=<real key>`
- start `orchestrator-service` and issue one real message flow that reaches tool-hub
- verify the resulting run tree in LangSmith contains:
  - parent message trace
  - nested `orchestrator.run_orchestration`
  - nested `orchestrator.tool_hub.invoke_plan`
