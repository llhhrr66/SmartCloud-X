# Web Admin

SmartCloud-X 的中文测试后台与运营控制台，面向 `knowledge-service` / `rag-service` 的真实联调能力重构。

## 当前定位

这不是纯开发调试面板，也不是虚构能力的后台原型。

当前页面按测试人员真实操作顺序组织：

1. 测试入口层
2. 知识库与文档主工作区
3. 导入与上传
4. 搜索、诊断与回答验证
5. 审计与活动记录
6. 系统状态层
7. 高级调试层

## 真实能力边界

- 浏览器会同时访问两类接口：
  - canonical admin 路由：`/api/v1/admin/**`
  - owner-local 路由：`/api/knowledge/v1/**`、`/api/rag/v1/**`
- 页面会明确区分 contract-facing 与 owner-local 现实，不把 fallback、file-backed、degraded 状态包装成“已工业化”能力。
- 当前前端支持三类资料进入方式：
  - 本地目录预览与批量导入
  - 已有 `file_id` / `source_uri` 的对象存储引用建文档
  - owner-local 直接文本录入
- 当前前端没有直接接入 owner-local 上传生命周期；如果需要上传到对象存储，仍需借助后端或脚本先拿到 `file_id`。

## 主要功能

- 中文化测试入口与下一步建议
- 知识库选择、设置更新、新建知识库
- 文档列表、文档详情、最近后台任务、分块预览
- 本地目录预览、批量导入、引用建文档、直接文本录入
- 知识搜索预览、Admin 搜索预览、RAG 诊断、Admin 诊断、回答预览
- 审计记录、导入活动、运行快照导出
- 健康状态、总览库存、连接器与异步索引状态、运行真相面板

## 运行

```bash
cd apps/web-admin
npm install
npm run dev -- --host 0.0.0.0 --port 8050
```

## 验证

```bash
npm run build
npm run check:owner
```

`check:owner` 是当前窗口 owner 维护的轻量验证入口，用来锁定：

- runtime truth 推断逻辑
- canonical admin / owner-local 路由差异提示
- request-id-aware 错误解释

## 环境变量

- `VITE_KNOWLEDGE_SERVICE_BASE_URL` 默认：`http://localhost:8030/api/knowledge/v1`
- `VITE_RAG_SERVICE_BASE_URL` 默认：`http://localhost:8040/api/rag/v1`
- `VITE_OPERATOR_REASON_HEADER` 默认：`X-Operator-Reason`

## Gateway 联调

如果希望 canonical admin 路由也经由 gateway，而不是直接命中知识库 / RAG 服务：

```bash
VITE_KNOWLEDGE_SERVICE_BASE_URL=http://localhost:8000/api/knowledge/v1
VITE_RAG_SERVICE_BASE_URL=http://localhost:8000/api/rag/v1
```

此时 `createWebAdminApi()` 会把 `/api/v1/admin/**` 一并切到 `gateway-service`。

## 备注

- 浏览器联调前，需要 `knowledge-service` 和 `rag-service` 允许当前 origin 通过 CORS。
- 运行真相面板里的标签，例如 `owner-local`、`file-backed`、`degraded`，都只基于前端当前可见的 health / snapshot / request 结果推断，不代表隐藏后端路径已经全部完成。
