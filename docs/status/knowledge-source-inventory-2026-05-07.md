# Knowledge Source Inventory

更新时间：2026-05-07  
适用范围：`apps/knowledge-service/data/knowledge-store.json` 当前运行时知识源盘点  
维护目标：区分正式可用知识源与测试残留知识源，便于后续检索治理、清理和扩充

## 0. 启动、配置与基础使用说明

### 0.1 服务启动方式

知识库相关运行时数据当前由 `apps/knowledge-service` 负责管理。

本地启动方式：

```bash
cd /home/ljr/SmartCloud-X/apps/knowledge-service
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8030
```

如果使用仓库根目录已有虚拟环境，也可直接在仓库根执行：

```bash
cd /home/ljr/SmartCloud-X
/home/ljr/SmartCloud-X/.venv/bin/python -m uvicorn apps.knowledge-service.app.main:app --reload --port 8030
```

说明：

- 默认知识库运行时文件位于 `apps/knowledge-service/data/knowledge-store.json`
- 默认文件导入根目录位于 `apps/knowledge-service/data/imports`
- 当前维护中的 starter 文档目录位于 `apps/knowledge-service/data/imports/starter`

### 0.2 关键环境变量

后续维护知识库时，最常用到的配置项如下：

- `SMARTCLOUD_KNOWLEDGE_DATA_PATH`
  - 运行时知识库 JSON 路径
  - 默认值：`apps/knowledge-service/data/knowledge-store.json`

- `SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT`
  - 文件导入根目录
  - 默认值：`apps/knowledge-service/data/imports`

- `SMARTCLOUD_KNOWLEDGE_STARTER_CATALOG_PATH`
  - starter catalog 种子文件路径
  - 默认值：`apps/knowledge-service/data/starter-catalog.json`

- `SMARTCLOUD_CHUNK_STRATEGY`
  - 分块策略
  - 可选值：`fixed` / `paragraph`

- `SMARTCLOUD_EMBEDDING_PROVIDER`
  - 向量化 provider
  - 默认离线值：`hash-baseline`
  - 如需联接外部 embedding 服务，可改为 `openai-compatible`

- `SMARTCLOUD_QDRANT_URL`
- `SMARTCLOUD_OPENSEARCH_URL`
- `SMARTCLOUD_REDIS_URL`
  - 用于远程向量检索、BM25 和缓存链路
  - 不配置时，本地仍可走降级检索

### 0.3 常用 API

知识库维护最常用的接口如下：

- `GET /api/knowledge/v1/sources`
  - 查看当前所有 source

- `GET /api/knowledge/v1/documents`
  - 查看文档列表
  - 可带 `sourceId`

- `GET /api/knowledge/v1/chunks`
  - 查看 chunk 列表
  - 可带 `documentId` 或 `sourceId`

- `GET /api/knowledge/v1/overview`
  - 查看整体统计

- `GET /api/knowledge/v1/snapshot`
  - 查看完整快照

- `GET /api/knowledge/v1/imports:preview`
  - 预览待导入文件

- `POST /api/knowledge/v1/files:ingest`
  - 批量导入 markdown/text 文件

- `POST /api/knowledge/v1/documents:ingest`
  - 直接导入单文档

- `POST /api/knowledge/v1/search`
  - 执行检索验证

### 0.4 基础维护流程

后续推荐按下面的顺序维护知识库：

1. 在 `apps/knowledge-service/data/imports/starter/` 编写或更新 Markdown 文档
2. 先用 `imports:preview` 检查会导入哪些文件
3. 再执行 `files:ingest` 导入目标 source
4. 导入后用 `search` 做定向检索验证
5. 确认命中质量后，再决定是否清理旧 source 或测试 source

### 0.5 简单测试流程

推荐至少做以下 3 轮最小验证：

#### 第一步：检查 source

目标：

- 确认目标 source 是否存在
- 确认文档数、chunk 数是否符合预期

可用方式：

- `GET /api/knowledge/v1/sources`
- `GET /api/knowledge/v1/overview`

#### 第二步：检查导入结果

目标：

- 确认新增文档已写入
- 确认 chunk 已生成

可用方式：

- `GET /api/knowledge/v1/documents?sourceId=<source-id>`
- `GET /api/knowledge/v1/chunks?sourceId=<source-id>`

#### 第三步：检查检索效果

目标：

- 用真实自然语言问法验证召回
- 观察首条命中是否落在正确主题文档

推荐测试问法：

- `我想部署一个中小型网站，云服务器怎么选规格`
- `为什么 nvidia-smi 正常但是容器里识别不到 GPU`
- `ICP备案一般多久能下来，需要什么材料`
- `删了实例为什么还在扣费，是不是数据盘还在收费`
- `活动二维码扫进去没有优惠页了，应该怎么排查`

### 0.6 当前维护结论

当前知识库已经清理过测试源与联调源，后续建议直接围绕优化版主 source 维护：

- `src-54013d183526`
- `SmartCloud Optimized Knowledge Base`

## 1. 当前正式源清单

以下 source 建议视为正式或半正式可维护知识源。

### 1.1 `src-54013d183526`

- 名称：`SmartCloud Optimized Knowledge Base`
- 类型：`manual`
- 文档数：`16`
- 分块数：`159`
- 标签：`knowledge-base, optimized, smartcloud, starter, v2`
- URI：`kb://smartcloud-optimized-knowledge-base-v2`
- 状态：`当前建议主用`
- 说明：
  - 这是目前整理过、补充了元信息头、FAQ、检索关键词扩展、快速结论块的优化版 starter 知识库。
  - 后续如果要继续扩展知识库内容，建议优先在这套文档基础上演进。
  - 检索验证时，应优先限定到这个 source 进行效果测试。

### 1.2 `src-af070f7ff74c`

- 名称：`产品技术知识库`
- 类型：`manual`
- 文档数：`2`
- 分块数：`15`
- 标签：`gpu, ops, product`
- URI：`starter://product-tech`
- 状态：`正式旧基线`
- 说明：
  - 这是旧的产品技术 starter 内容。
  - 内容较少，但仍可保留作为对照基线。
  - 若后续确认 `SmartCloud Optimized Knowledge Base` 已完全覆盖其用途，可考虑归档或停用该旧基线。

### 1.3 `src-0eb302438b0f`

- 名称：`备案与合规指南`
- 类型：`policy`
- 文档数：`1`
- 分块数：`1`
- 标签：`compliance, icp, policy`
- URI：`starter://icp-policy`
- 状态：`正式旧基线`
- 说明：
  - 属于早期单文档合规基线。
  - 已被优化版 source 中更完整的备案流程和驳回原因文档覆盖大部分用途。
  - 暂时保留不影响运行，但后续可以考虑归档。

### 1.4 `src-1689c30c037b`

- 名称：`财务与订单 FAQ`
- 类型：`faq`
- 文档数：`1`
- 分块数：`1`
- 标签：`billing, finance, invoice`
- URI：`starter://finance-faq`
- 状态：`正式旧基线`
- 说明：
  - 属于早期财务 starter 内容。
  - 已被优化版 source 中的 `计费模式与价格说明`、`退款与发票处理流程` 基本覆盖。
  - 建议保留一段时间后视情况归档。

## 2. 当前测试源清单

当前运行时知识库中，测试源已经清理完成。

说明：

- 早期存在的 `QA Smoke Import`、`QA Smoke KB` 已移除
- 早期联调验证源 `siliconflow-live-source` 已移除
- 当前运行时知识库只剩正式业务 source

以下内容作为历史记录保留，便于后续排查和审计。

### 2.1 `src-36ecdbfdf6ae`

- 名称：`QA Smoke Import`
- 类型：`manual`
- 文档数：`2`
- 分块数：`2`
- 标签：`filesystem, starter`
- URI：`无`
- 状态：`测试源`
- 说明：
  - 来自文件导入 smoke 测试。
  - 文档内容与正式知识部分重合，但规模更小，保留价值有限。

### 2.2 `QA Smoke KB` 系列

这些 source 都属于同一类测试残留，名称相同，仅 ID 不同：

- `src-2ee5039b7712`
- `src-3e0658a2eaa5`
- `src-4f7dc69af66c`
- `src-59e08a6693f1`
- `src-606fb6ec5a53`
- `src-7128a3281d0e`
- `src-8a9ec0265319`
- `src-b7201c44db28`
- `src-f559cc92d2ad`

共同特征：

- 名称：`QA Smoke KB`
- 类型：`product`
- 文档数：各 `1`
- 分块数：各 `1`
- 标签：`product, zh-cn`
- URI：`kb://qa-smoke-*`
- 状态：`测试源`
- 说明：
  - 这些大概率来自重复的 smoke / e2e / admin import 验证过程。
  - 保留它们会污染检索结果，使同类测试内容反复命中。
  - 如果目标是让知识库更接近正式环境，优先建议清理这一组。

## 3. 当前维护建议

### 3.1 推荐作为主检索源

当前建议主用：

- `src-54013d183526`

推荐原因：

- 文档内容最完整
- 结构最统一
- 已补充 FAQ、关键词扩展和快速结论
- 已完成实际检索验证

### 3.2 推荐保留但降低优先级的源

建议暂时保留：

- `src-af070f7ff74c`
- `src-0eb302438b0f`
- `src-1689c30c037b`

保留原因：

- 可以作为历史基线或联调样本
- 当前不会影响 source 级定向检索

但应注意：

- 如果不做 source 过滤，旧基线和联调源仍会参与全库检索
- 长期看应决定是否归档或隔离

### 3.3 推荐优先清理的测试源

优先建议清理：

- `src-36ecdbfdf6ae`
- 所有 `QA Smoke KB` source

清理收益：

- 降低检索噪音
- 减少重复命中
- 让知识库更接近正式生产数据状态

### 3.4 后续新增知识的写入原则

建议后续新增正式知识时遵循以下原则：

1. 新文档优先进入 `SmartCloud Optimized Knowledge Base`
2. 不再把正式知识写入旧 starter source
3. 每次导入前确认目标 source，避免重复导入到错误 source
4. 导入完成后，做一次定向 source 检索验证
5. 定期复盘测试源是否需要删除

## 4. 建议的后续动作

建议按优先顺序执行：

1. 清理 `QA Smoke Import` 和全部 `QA Smoke KB` 测试源
2. 保留 `SmartCloud Optimized Knowledge Base` 作为主知识库
3. 视需要归档旧的 `产品技术知识库`、`备案与合规指南`、`财务与订单 FAQ`
4. 为正式 source 建立固定维护入口，例如统一从 `apps/knowledge-service/data/imports/starter/` 演进
5. 每轮更新后记录 source 变更摘要和检索验证结果

## 5. 一句话结论

当前最适合作为正式主知识源的是：

- `src-54013d183526` `SmartCloud Optimized Knowledge Base`

当前测试源和联调验证源已经完成清理。
