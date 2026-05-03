# Knowledge Service Development Prompt

You are working inside the `SmartCloud-X` repository. Continue improving `apps/knowledge-service` based on the current implementation, status files, and development documents. Do not rebuild the service from scratch.

## Required reading

Read these files first:

- `/home/ljr/SmartCloud/开发文档拆分版/03-RAG编排与事务补偿设计.md`
- `/home/ljr/SmartCloud/开发文档拆分版/04-数据存储与检索设计.md`
- `/home/ljr/SmartCloud-X/docs/status/supervisor-knowledge-rag-status.md`
- `/home/ljr/SmartCloud-X/apps/knowledge-service/README.md`
- `/home/ljr/SmartCloud-X/apps/knowledge-service/app/main.py`
- `/home/ljr/SmartCloud-X/apps/knowledge-service/app/core/config.py`
- `/home/ljr/SmartCloud-X/apps/knowledge-service/app/services/store.py`
- `/home/ljr/SmartCloud-X/apps/knowledge-service/app/services/search.py`
- `/home/ljr/SmartCloud-X/apps/knowledge-service/app/services/ingestion.py`
- `/home/ljr/SmartCloud-X/apps/knowledge-service/app/services/indexing_worker.py`
- `/home/ljr/SmartCloud-X/apps/knowledge-service/app/services/metadata_backend.py`
- `/home/ljr/SmartCloud-X/apps/knowledge-service/app/services/admin.py`
- `/home/ljr/SmartCloud-X/apps/knowledge-service/app/services/file_import.py`
- `/home/ljr/SmartCloud-X/apps/knowledge-service/app/services/snapshot.py`
- `/home/ljr/SmartCloud-X/apps/knowledge-service/app/services/health.py`
- `/home/ljr/SmartCloud-X/apps/knowledge-service/app/services/dify_external.py`
- `/home/ljr/SmartCloud-X/apps/knowledge-service/app/services/dify_dataset_sync.py`
- `/home/ljr/SmartCloud-X/apps/knowledge-service/app/services/runtime_sync.py`
- `/home/ljr/SmartCloud-X/apps/knowledge-service/app/services/analytics.py`
- `/home/ljr/SmartCloud-X/apps/knowledge-service/app/services/admin_audit.py`
- `/home/ljr/SmartCloud-X/apps/knowledge-service/app/api/routes/knowledge.py`
- `/home/ljr/SmartCloud-X/apps/knowledge-service/app/api/routes/admin.py`
- `/home/ljr/SmartCloud-X/apps/knowledge-service/app/api/routes/health.py`
- `/home/ljr/SmartCloud-X/apps/knowledge-service/app/api/routes/dify.py`
- `/home/ljr/SmartCloud-X/apps/knowledge-service/app/models/knowledge.py`
- `/home/ljr/SmartCloud-X/apps/knowledge-service/app/models/admin.py`
- `/home/ljr/SmartCloud-X/apps/knowledge-service/app/models/runtime.py`
- `/home/ljr/SmartCloud-X/apps/knowledge-service/app/models/dify.py`
- `/home/ljr/SmartCloud-X/apps/knowledge-service/app/worker.py`
- `/home/ljr/SmartCloud-X/apps/knowledge-service/tests/test_ingestion.py`

## Original service responsibilities

According to the development document (04-数据存储与检索设计), knowledge-service owns:

1. **知识源管理** — source registration, KB profiles, catalog persistence
2. **文档摄入与处理** — ingestion pipeline: upload → clean → chunk → metadata extract → MinIO → MySQL → Qdrant → OpenSearch → sync
3. **向量与BM25索引** — maintain Qdrant collections and OpenSearch indices per domain
4. **搜索** — hybrid search (Qdrant vector + OpenSearch BM25 + local keyword fallback) for RAG consumers
5. **管理后台** — admin KB/document CRUD, reindex, upload lifecycle, diagnostics
6. **Dify 集成** — external knowledge adapter + dataset sync

Current implementation: source/doc/chunk CRUD, ingestion with chunking and keyword extraction, hybrid search (OpenSearch + Qdrant + local fallback), MySQL runtime backend, JSON fallback, indexing worker, admin endpoints, Dify adapter, audit trail, snapshot export, health diagnostics, OTLP tracing, Prometheus metrics. Status: 61 tests passing.

## First step: gap analysis

Before coding, produce a short gap report covering:

- whether the embedding model is real ML embedding or still the SHA256-hash baseline (`_build_embedding` in search.py)
- whether Qdrant uses a single `knowledge_chunks` collection or separate domain collections as doc 11.1 specifies (`product_docs`, `billing_docs`, `icp_docs`, `marketing_docs`, `research_docs`)
- whether OpenSearch uses a single `knowledge_chunks` index or separate indices as doc 11.2 specifies (`product_bm25`, `billing_bm25`, etc.)
- whether the text cleaning step in the processing pipeline is adequate (beyond `strip()`)
- whether token estimation (`len(content) // 4`) is accurate enough for Chinese text
- whether keyword extraction handles Chinese text properly or relies only on stopword filtering
- whether Redis key patterns match the documented conventions from doc 10.3
- whether the chunk overlap strategy produces semantically coherent chunks
- whether README, status file, and tests still match current behavior
- whether there are missing tests around embedding quality, multi-backend search merge, concurrent ingestion, large document chunking

Do not skip this analysis.

## Main objectives for this round

### P1. Embedding interface abstraction

Current vector search uses `_build_embedding()` which produces SHA256-based hash vectors — not real semantic embeddings. This blocks Qdrant from delivering meaningful similarity results.

Improve:
- Create an `EmbeddingProvider` protocol with a `embed(texts: list[str]) -> list[list[float]]` method
- Implement `HashEmbeddingProvider` (current baseline, for tests and cold environments)
- Implement `OpenAICompatibleEmbeddingProvider` that calls an OpenAI-compatible embedding API when configured (`SMARTCLOUD_EMBEDDING_API_URL`, `SMARTCLOUD_EMBEDDING_API_KEY`, `SMARTCLOUD_EMBEDDING_MODEL`)
- Wire the provider into both ingestion (chunk indexing) and search (query embedding)
- Add `embedding_provider` field to Settings, default to `hash-baseline`
- Keep SHA256 hash as the fallback when no embedding API is configured
- Add a `GET /api/knowledge/v1/embedding:test` debug endpoint that shows which provider is active and a sample embedding for a given text

### P2. Text cleaning and metadata extraction improvement

Current ingestion does minimal text cleaning (`strip()`) and keyword extraction (regex + stopwords). Improve:

- Add a `TextProcessor` service with:
  - `clean(text: str) -> str`: normalize whitespace, remove zero-width chars, normalize CJK punctuation, strip markdown headers/links while keeping content
  - `extract_metadata(text: str) -> dict`: extract language, domain hints (billing/ICP/marketing/product), entity mentions, estimated reading time
  - `extract_keywords(text: str, max_keywords: int) -> list[str]`: improve current keyword extraction with TF-IDF-like scoring against the corpus, better Chinese word boundary handling
- Wire into `IngestionService.ingest_document()` so documents are cleaned before chunking and metadata is attached to chunks
- Keep backward compatibility: existing documents should not be affected

### P3. Chunk quality improvement

Current chunking is simple character-count split with overlap. Improve:

- Add `chunk_strategy` setting: `"fixed"` (current) or `"paragraph"` (split on paragraph/section boundaries first, then fall back to character split)
- In paragraph mode: split on `\n\n`, markdown headers (`## ...`), and horizontal rules (`---`) first, then merge short paragraphs and split long ones
- Improve token estimation: use a better heuristic for Chinese text (1 CJK char ≈ 1.5 tokens, 1 English word ≈ 1 token)
- Add chunk quality metrics to ingestion response: `avgChunkTokens`, `maxChunkTokens`, `minChunkTokens`
- Keep `max_chunk_chars` and `chunk_overlap_chars` configurable

### P4. Search quality hardening

Current search works but has edge cases:

- When both OpenSearch and Qdrant return results, the merge uses `max(lexical_score, 0.62*remote + 0.38*lexical)` — make these weights configurable via Settings
- Add score normalization for OpenSearch BM25 scores (currently raw, can be very large) — the `_normalize_remote_score` function exists but may not handle all BM25 score ranges well
- Add a `search_min_score` threshold (default 0.1) to filter out noise results before returning
- Add `backend_used` field to `SearchResponse` so consumers know which path was taken (local-keyword, opensearch-only, qdrant-only, hybrid-live-backends)
- Ensure `_coerce_chunk` handles all field name variations from both OpenSearch and Qdrant consistently

### P5. Improve tests

Add or improve tests for:

- embedding provider protocol: hash baseline and mock OpenAI-compatible provider
- text cleaning: whitespace normalization, CJK punctuation, markdown stripping
- metadata extraction: language detection, domain hints
- paragraph-aware chunking vs fixed chunking
- token estimation accuracy for Chinese vs English text
- search score normalization for large BM25 scores
- search merge behavior when only one backend returns results
- concurrent ingestion of the same document (duplicate protection under race)
- large document chunking (10000+ chars)
- chunk overlap correctness verification
- indexing worker batch processing edge cases
- Dify adapter with real search results (not just disabled/auth paths)

Use the existing test style in `apps/knowledge-service/tests/test_ingestion.py`.

### P6. Update docs if behavior changes

If you change behavior, update:
- `/home/ljr/SmartCloud-X/apps/knowledge-service/README.md`
- `/home/ljr/SmartCloud-X/docs/status/supervisor-knowledge-rag-status.md`

Documentation must clearly state:
- embedding strategy and configuration
- text processing pipeline
- chunking strategy options
- search backend priority and score merging
- new configuration environment variables
- known limitations (hash embedding baseline, single collection/index)
- validation commands

## Coding constraints

- Do not redesign the whole knowledge service.
- Do not replace the MySQL/JSON dual-persistence model.
- Do not remove the local keyword fallback search.
- Do not break existing admin, search, ingestion, or health contracts.
- Do not change the indexing worker outbox lifecycle.
- Do not remove Dify adapter or dataset sync.
- Keep SHA256 hash embedding as the default fallback — all features must work without an external embedding API.
- Prefer small, reviewable edits.
- Keep compatibility with existing tests.

## Required validation

Use the repository virtual environment and explicit PYTHONPATH.

### Unit tests
```bash
PYTHONPATH="/home/ljr/SmartCloud-X/apps/knowledge-service:/home/ljr/SmartCloud-X/apps:/home/ljr/SmartCloud-X/packages" \
/home/ljr/SmartCloud-X/.venv/bin/pytest \
/home/ljr/SmartCloud-X/apps/knowledge-service/tests/test_ingestion.py -q
```

### Compile check
```bash
cd /home/ljr/SmartCloud-X && \
/home/ljr/SmartCloud-X/.venv/bin/python -m compileall apps/knowledge-service/app
```

### Broader owned-scope validation if environment is ready
```bash
cd /home/ljr/SmartCloud-X && \
uv run --with-requirements apps/knowledge-service/requirements.txt --with httpx --with pytest \
python -m pytest apps/knowledge-service/tests apps/rag-service/tests -q
```

## Required final output

Provide:

1. file-by-file change summary
2. service duty completion table:

| Duty | Status | Notes |
|---|---|---|
| 知识源管理 | ... | ... |
| 文档摄入与处理 | ... | ... |
| 向量与BM25索引 | ... | ... |
| 搜索 | ... | ... |
| 管理后台 | ... | ... |
| Dify 集成 | ... | ... |

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

SQLAlchemy:
- https://docs.sqlalchemy.org/en/20/orm/quickstart.html

HTTPX:
- https://www.python-httpx.org/async/
- https://www.python-httpx.org/advanced/timeouts/

Qdrant:
- https://qdrant.tech/documentation/concepts/search/
- https://qdrant.tech/documentation/concepts/filtering/

OpenSearch:
- https://opensearch.org/docs/latest/query-dsl/full-text/multi-match/

Pytest:
- https://docs.pytest.org/en/stable/how-to/fixtures.html
- https://docs.pytest.org/en/stable/how-to/monkeypatch.html

## 停止与上报规则

### 必须立即停止并上报的情况

1. **环境阻塞**：虚拟环境 `.venv` 缺少关键依赖（如 fastapi、httpx、pydantic、sqlalchemy）且安装失败时，停止编码，报告缺少的包和错误信息。
2. **编译失败**：`python -m compileall apps/knowledge-service/app` 报语法错误或导入错误时，停止后续开发，先修复编译问题。如果修复两轮仍然不通过，停止并上报。
3. **原有测试回归**：你的修改导致已有测试失败时，立即回退该修改并上报冲突原因。不允许删除或跳过已有测试来通过验证。
4. **合约冲突**：发现已有的公共路由名称或搜索响应结构需要改变时，停止并上报，这些是冻结合约。
5. **上游依赖不可控**：需要修改 `rag-service` 的搜索消费接口才能完成本轮任务时，停止并上报为跨服务合约变更。
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
- 服务：knowledge-service
- 问题描述：（一句话描述）
- 错误信息：（原始错误或日志）
- 已尝试修复：（列出已尝试的方案）
- 需要的下一步动作：（需要谁做什么）
- 当前完成状态：（已完成哪些 P 任务、哪些被阻塞）
```
