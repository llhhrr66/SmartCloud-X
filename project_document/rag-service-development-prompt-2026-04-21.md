# RAG Service Development Prompt

You are working inside the `SmartCloud-X` repository. Continue improving `apps/rag-service` based on the current implementation, status files, and development documents. Do not rebuild the service from scratch.

## Required reading

Read these files first:

- `/home/ljr/SmartCloud/开发文档拆分版/03-RAG编排与事务补偿设计.md`
- `/home/ljr/SmartCloud/开发文档拆分版/04-数据存储与检索设计.md`
- `/home/ljr/SmartCloud-X/docs/status/supervisor-knowledge-rag-status.md`
- `/home/ljr/SmartCloud-X/apps/rag-service/README.md`
- `/home/ljr/SmartCloud-X/apps/rag-service/app/main.py`
- `/home/ljr/SmartCloud-X/apps/rag-service/app/core/config.py`
- `/home/ljr/SmartCloud-X/apps/rag-service/app/api/dependencies.py`
- `/home/ljr/SmartCloud-X/apps/rag-service/app/api/routes/rag.py`
- `/home/ljr/SmartCloud-X/apps/rag-service/app/api/routes/admin.py`
- `/home/ljr/SmartCloud-X/apps/rag-service/app/api/routes/health.py`
- `/home/ljr/SmartCloud-X/apps/rag-service/app/models/rag.py`
- `/home/ljr/SmartCloud-X/apps/rag-service/app/models/admin.py`
- `/home/ljr/SmartCloud-X/apps/rag-service/app/models/common.py`
- `/home/ljr/SmartCloud-X/apps/rag-service/app/services/retrieval.py`
- `/home/ljr/SmartCloud-X/apps/rag-service/app/services/query_rewriter.py`
- `/home/ljr/SmartCloud-X/apps/rag-service/app/services/answer.py`
- `/home/ljr/SmartCloud-X/apps/rag-service/app/services/knowledge_client.py`
- `/home/ljr/SmartCloud-X/apps/rag-service/app/services/cache.py`
- `/home/ljr/SmartCloud-X/apps/rag-service/app/services/health.py`
- `/home/ljr/SmartCloud-X/apps/rag-service/app/services/providers.py`
- `/home/ljr/SmartCloud-X/apps/rag-service/app/core/metrics.py`
- `/home/ljr/SmartCloud-X/apps/rag-service/app/core/tracing.py`
- `/home/ljr/SmartCloud-X/apps/rag-service/tests/test_retrieval.py`

## Original service responsibilities

According to the development document (03-RAG编排与事务补偿设计), rag-service owns the retrieval chain:

1. **Query Rewrite** — normalize, tokenize, synonym-expand user queries
2. **Hybrid Search** — L1 Redis cache + L2 Hybrid (Qdrant vector + OpenSearch BM25) via knowledge-service
3. **Rerank** — score and reorder candidates by relevance
4. **Context Build** — assemble a token-aware, deduplicated context window for the target agent
5. **Citation Pack** — produce structured citations with source, score, and reasoning

The current implementation covers query rewrite (keyword+synonym), retrieval via knowledge-service proxy, deterministic reranking, template-based answer composition, Redis+memory cache, Prometheus metrics, OpenTelemetry tracing, upstream degradation, and admin diagnostics. Tests pass at 61 (knowledge+rag combined).

## First step: gap analysis

Before coding, produce a short gap report covering:

- whether query rewrite handles multi-turn conversation context or only single-turn
- whether rerank scoring is only the hardcoded `0.68*score + 0.22*density + 0.1*keyword + title_boost` formula, or has any configurable or agent-specific weighting
- whether context building includes token-aware window management (max tokens, dedup, compression) or only takes raw top-k snippets
- whether the L1 cache key pattern matches the documented `smartcloud:chat:l1:{hash}` convention from doc 04
- whether there is any agent-specific or knowledge-base routing (e.g., product_docs vs billing_docs per agent)
- whether the synonym map is extensible or hardcoded only
- whether README, status file, and tests still match current route behavior
- whether there are missing tests around cache invalidation, multi-turn context, large candidate lists, or tokenization edge cases

Do not skip this analysis.

## Main objectives for this round

### P1. Context building enhancement

The current implementation takes raw top-k snippets from retrieval. Improve context building:

- Add a `ContextBuilder` service that:
  - accepts retrieval citations and builds a context string for LLM consumption
  - respects a configurable `max_context_tokens` budget (default 3000)
  - deduplicates overlapping chunks from the same document
  - orders context by relevance score, not insertion order
  - includes source attribution markers (`[来源: {documentTitle}]`) for each chunk
  - returns a `ContextBuildResult` with `context_text`, `token_estimate`, `included_count`, `truncated_count`
- Wire `ContextBuilder` into the `/answer` route so the answer composer receives a properly bounded context
- Add a `POST /api/rag/v1/context` endpoint that returns the built context without answer composition, for orchestrator consumption
- Keep backward compatibility: `/retrieve` and `/diagnose` should not change behavior

### P2. Query rewrite improvement

Current query rewrite is single-turn keyword+synonym only. Improve it:

- Accept an optional `conversation_context` field (list of recent messages) in `RetrieveRequest`
- When conversation context is provided, extract key entities from recent messages and merge them into the rewrite
- Make the synonym map configurable via environment variable `SMARTCLOUD_RAG_SYNONYM_FILE` pointing to a JSON file, with fallback to the current hardcoded map
- Add more domain synonyms: `{"服务器": ["ecs", "云主机", "实例"], "域名": ["dns", "解析"], "ssl": ["证书", "https"], "cdn": ["加速", "分发"], "安全组": ["防火墙", "规则"]}`
- Add a `POST /api/rag/v1/rewrite` endpoint that exposes query rewriting independently for debugging

### P3. Rerank scoring improvement

Current reranking is a single formula. Make it more robust:

- Make rerank weights configurable via `Settings` (`rerank_score_weight`, `rerank_density_weight`, `rerank_keyword_weight`, `rerank_title_boost`)
- Add `source_type` scoring: if the query mentions a knowledge domain keyword (e.g., "账单", "备案"), boost candidates from the matching source
- Add `recency_boost`: if a candidate's `createdAt` is within the last 30 days, apply a small recency boost (configurable)
- Add minimum score threshold: filter out candidates below `min_rerank_score` (default 0.2) before citation building
- Keep the deterministic baseline — do not introduce ML dependencies

### P4. Cache strategy alignment

Current cache uses `smartcloud-x:rag:{payload}` keys. Align with documented conventions:

- Use key pattern `smartcloud:rag:l1:{query_hash}` for retrieval cache (matching doc 04's L1 convention)
- Add cache stats to the `/healthz` response: `cacheHitRate`, `cacheSize`, `lastPruneTime`
- Add a `POST /api/v1/admin/cache/clear` admin endpoint for manual cache invalidation
- Add a `DELETE /api/rag/v1/cache` internal endpoint for knowledge-service to trigger invalidation when documents change
- Track cache hit/miss ratio as a Prometheus gauge (`rag_cache_hit_ratio`)

### P5. Improve tests

Add or improve tests for:

- context building: token budget enforcement, deduplication, source attribution
- multi-turn query rewrite with conversation context
- rerank with configurable weights and source-type boosting
- rewrite with external synonym file
- cache key format validation
- cache invalidation endpoint
- `/context` endpoint happy path and edge cases
- `/rewrite` endpoint
- large candidate list handling (50+ candidates)
- tokenization edge cases: empty strings, pure punctuation, very long Chinese text, mixed CJK/Latin
- concurrent cache access (thread safety)
- admin cache clear endpoint

Use the existing test style in `apps/rag-service/tests/test_retrieval.py`.

### P6. Update docs if behavior changes

If you change behavior, update:
- `/home/ljr/SmartCloud-X/apps/rag-service/README.md`
- `/home/ljr/SmartCloud-X/docs/status/supervisor-knowledge-rag-status.md`

Documentation must clearly state:
- implemented retrieval chain stages and their current capabilities
- new endpoints added
- context building strategy and configuration
- cache key convention and invalidation contract
- synonym configuration approach
- known limitations (no ML rerank, no direct vector DB, no streaming retrieval)
- validation commands

## Coding constraints

- Do not redesign the whole retrieval pipeline.
- Do not replace knowledge-service integration with direct Qdrant/OpenSearch access.
- Do not introduce ML model dependencies (cross-encoder, sentence transformers, etc.).
- Do not break existing `/retrieve`, `/diagnose`, `/answer`, or `/healthz` contracts.
- Do not change the upstream header forwarding behavior.
- Keep Redis optional — all features must work with memory-only fallback.
- Prefer small, reviewable edits.
- Keep compatibility with existing tests.

## Required validation

Use the repository virtual environment and explicit PYTHONPATH.

### Unit tests
```bash
PYTHONPATH="/home/ljr/SmartCloud-X/apps/rag-service:/home/ljr/SmartCloud-X/apps:/home/ljr/SmartCloud-X/packages" \
/home/ljr/SmartCloud-X/.venv/bin/pytest \
/home/ljr/SmartCloud-X/apps/rag-service/tests/test_retrieval.py -q
```

### Compile check
```bash
cd /home/ljr/SmartCloud-X && \
/home/ljr/SmartCloud-X/.venv/bin/python -m compileall apps/rag-service/app
```

### Broader owned-scope validation if environment is ready
```bash
cd /home/ljr/SmartCloud-X && \
uv run --with-requirements apps/rag-service/requirements.txt --with httpx --with pytest \
python -m pytest apps/knowledge-service/tests apps/rag-service/tests -q
```

## Required final output

Provide:

1. file-by-file change summary
2. service duty completion table:

| Duty | Status | Notes |
|---|---|---|
| Query Rewrite | ... | ... |
| Hybrid Search | ... | ... |
| Rerank | ... | ... |
| Context Build | ... | ... |
| Citation Pack | ... | ... |

3. exact validation commands run
4. exact results
5. known limitations
6. whether the service is ready to hand back for review

## Relevant official documentation

FastAPI:
- https://fastapi.tiangolo.com/tutorial/bigger-applications/
- https://fastapi.tiangolo.com/tutorial/dependencies/
- https://fastapi.tiangolo.com/tutorial/testing/

Pydantic:
- https://docs.pydantic.dev/latest/concepts/models/
- https://docs.pydantic.dev/latest/concepts/validators/

HTTPX:
- https://www.python-httpx.org/async/
- https://www.python-httpx.org/advanced/timeouts/

Pytest:
- https://docs.pytest.org/en/stable/how-to/fixtures.html
- https://docs.pytest.org/en/stable/how-to/monkeypatch.html

Prometheus:
- https://prometheus.github.io/client_python/

OpenTelemetry:
- https://opentelemetry.io/docs/languages/python/

## 停止与上报规则

### 必须立即停止并上报的情况

1. **环境阻塞**：虚拟环境 `.venv` 缺少关键依赖（如 fastapi、httpx、pydantic）且安装失败时，停止编码，报告缺少的包和错误信息。
2. **编译失败**：`python -m compileall apps/rag-service/app` 报语法错误或导入错误时，停止后续开发，先修复编译问题。如果修复两轮仍然不通过，停止并上报。
3. **原有测试回归**：你的修改导致已有测试失败时，立即回退该修改并上报冲突原因。不允许删除或跳过已有测试来通过验证。
4. **合约冲突**：发现已有的公共路由名称（`/retrieve`、`/diagnose`、`/answer`、`/healthz`）需要改变请求或响应结构时，停止并上报，这些是冻结合约。
5. **上游依赖不可控**：需要修改 `knowledge-service` 的搜索接口才能完成本轮任务时，停止并上报为跨服务合约变更。
6. **循环失败**：同一问题修复超过 3 次仍然不通过时，停止并上报问题本身，不要继续尝试。

### 必须停止并输出交付物的情况

7. **全部 P1-P5 完成**：所有优先级任务完成且验证通过后，停止编码，输出完整的交付物（变更总结 + 完成度表格 + 验证结果 + 已知限制）。
8. **部分完成但无法继续**：如果某个优先级任务因外部原因无法完成，标记为 blocked，继续完成其他任务，最终交付时明确标注哪些已完成、哪些被阻塞及原因。

### 不允许的行为

- 不允许跳过验证命令直接报告"完成"
- 不允许用 `# type: ignore` 或 `noqa` 掩盖真实的类型或逻辑错误（已有合理标注的除外）
- 不允许在测试失败时删除或注释掉测试
- 不允许引入破坏性变更后不运行回归测试
- 不允许在遇到阻塞时静默继续下一个任务而不记录

### 上报格式

遇到需要上报的情况时，输出以下格式：

```
## BLOCKER REPORT
- 类型：[code | environment | dependency | contract | upstream]
- 服务：rag-service
- 问题描述：（一句话描述）
- 错误信息：（原始错误或日志）
- 已尝试修复：（列出已尝试的方案）
- 需要的下一步动作：（需要谁做什么）
- 当前完成状态：（已完成哪些 P 任务、哪些被阻塞）
```
