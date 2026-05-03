# Supervisor SiliconFlow Embedding Status

- 更新时间：2026-04-24
- 范围：`apps/knowledge-service/` embedding provider 代码路径、`/api/knowledge/v1/embedding:test` 运行探针、SiliconFlow `BAAI/bge-m3` 补充验证结论沉淀
- 结论摘要：**`knowledge-service` 代码已具备 OpenAI-compatible embedding 接入路径；但当前 running live `knowledge-service` 未被独立复核为已切换到 SiliconFlow `BAAI/bge-m3`。当前仓库不得把 live SiliconFlow 切换写成既成事实。**

## 代码已确认的事实

### OpenAI-compatible embedding 代码路径已存在
- `apps/knowledge-service/app/services/embeddings.py`
  - `build_embedding_provider(settings)` 在 `SMARTCLOUD_EMBEDDING_PROVIDER=openai-compatible` 时构造 `FallbackEmbeddingProvider(OpenAICompatibleEmbeddingProvider(settings), fallback)`。
  - `OpenAICompatibleEmbeddingProvider` 会校验：
    - `SMARTCLOUD_EMBEDDING_API_URL`
    - `SMARTCLOUD_EMBEDDING_API_KEY`
    - `SMARTCLOUD_EMBEDDING_MODEL`
  - 缺少任一配置会抛出 `EmbeddingConfigurationError`。
- `apps/knowledge-service/app/api/routes/knowledge.py`
  - `GET /api/knowledge/v1/embedding:test` 会调用实际 embedding provider。
  - 返回值包含 `provider`、`configuredProvider`、`sample`、`dimensions`。
  - 若 provider 是 `FallbackEmbeddingProvider`，还会返回 `fallbackActive`，并在有错误时返回 `providerError`。

### 这代表什么，不代表什么
- 这代表：仓库代码层面已经具备接入 OpenAI-compatible embedding 服务的实现基础。
- 这不代表：当前任意 running live `knowledge-service` 实例都已经实际切换到 SiliconFlow `BAAI/bge-m3`。

## 已沉淀的补充验证结论

以下结论用于替代工作区 `tasks/*.md` 作为正式文档引用锚点：

1. 独立补充验证已确认：**代码路径存在**，即仓库能够通过 OpenAI-compatible 协议接入外部 embedding provider。
2. 独立补充验证同时确认：**当前 running live `knowledge-service` 未被独立复核为已切换到 SiliconFlow `BAAI/bge-m3`**。
3. 补充验证记录的 live 现象为：
   - running 容器内未确认已注入 `SMARTCLOUD_EMBEDDING_PROVIDER`
   - running 容器内未确认已注入 `SMARTCLOUD_EMBEDDING_API_URL`
   - running 容器内未确认已注入 `SMARTCLOUD_EMBEDDING_API_KEY`
   - running 容器内未确认已注入 `SMARTCLOUD_EMBEDDING_MODEL`
   - live `GET /api/knowledge/v1/embedding:test` 返回的关键信号为：
     - `provider=HashEmbeddingProvider`
     - `configuredProvider=hash-baseline`
     - `dimensions=32`

## 运行口径

### 当前允许陈述
- 可以陈述：`knowledge-service` 代码已支持 `openai-compatible` embedding provider 接入路径。
- 可以陈述：`/api/knowledge/v1/embedding:test` 是当前仓库中的 embedding 运行探针。
- 可以陈述：当前正式仓库文档保留的独立补充验证结论显示，running live `knowledge-service` **未被独立复核为已切换**到 SiliconFlow `BAAI/bge-m3`。

### 当前禁止陈述
- 不得陈述：当前 running live `knowledge-service` 已经完成 SiliconFlow `BAAI/bge-m3` 切换。
- 不得陈述：当前 release gate 的通过，已经证明 live SiliconFlow embedding 处于激活状态。
- 不得把“代码支持”直接写成“当前 live 已切换成功”。

## 与 release gate 的关系
- 当前仓库已记录 Round 9 gateway acceptance 与 Round 11 strict release gate 的通过证据。
- 这些通过证据与 SiliconFlow live 切换并不是同一个结论层级。
- 当前已通过的 release gate **并不等于** running live `knowledge-service` 已被独立复核为 SiliconFlow `BAAI/bge-m3`。
- 因此二者可以同时成立：
  - 仓库级 release gate 证据为 green；
  - running live SiliconFlow 切换仍未被独立复核证实。

## 后续若要声明 live 已切换，至少需要补齐的证据
1. running 容器环境中已确认注入：
   - `SMARTCLOUD_EMBEDDING_PROVIDER=openai-compatible`
   - `SMARTCLOUD_EMBEDDING_API_URL`
   - `SMARTCLOUD_EMBEDDING_API_KEY`
   - `SMARTCLOUD_EMBEDDING_MODEL`
2. fresh `GET /api/knowledge/v1/embedding:test` 输出不再是 `hash-baseline` / `HashEmbeddingProvider` / `32` 的基线路径信号。
3. 必要时补充 ingest/search 侧的运行证据，证明外部 embedding provider 不只是配置存在，而是实际参与了索引与检索流程。
