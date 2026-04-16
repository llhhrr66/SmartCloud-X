# LangSmith Placeholder

LangSmith is part of the SmartCloud-X target observability shape, but the current knowledge and RAG baseline does not invoke LangChain or remote model providers yet.

## Current state
- compose reserves `LANGSMITH_TRACING`, `LANGSMITH_ENDPOINT`, `LANGSMITH_PROJECT`, and `LANGSMITH_API_KEY` in `knowledge-service` and `rag-service`
- the default local stack keeps `LANGSMITH_TRACING=false`, so operators do not need a cloud credential just to run the baseline
- Prometheus, Grafana, and Phoenix are the active local observability path today; LangSmith remains deferred until the services start using LangChain or external model providers that warrant LangSmith-native traces and evaluations

## Next step
- enable `LANGSMITH_TRACING=true` in compose or deployment environments once a service starts using LangChain components that emit useful traces
- keep the project name stable across services so future multi-service conversations can be reviewed as one SmartCloud-X trace set
