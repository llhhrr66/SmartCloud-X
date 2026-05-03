# SmartCloud-X

SmartCloud-X 是一个企业级智能云服务平台，提供云产品咨询、账单查询、ICP备案、营销运营和技术调研等多场景 AI Agent 服务。

## 架构概览

```
用户请求
  │
  ▼
Gateway (API 网关)
  │
  ▼
Orchestrator (编排引擎)
  ├── Router：关键词路由 → Agent 分配
  ├── LLM Tool-Calling Loop：LLM 驱动工具选择（主路径）
  ├── Keyword Fallback：关键词工具推荐（备用路径）
  └── Agent Answer Generator：LLM 最终回答生成
  │
  ▼
Tool-Hub → Business-Tools（产品目录 / 账单 / ICP / 营销 / 调研 / 工单）
  │
  ▼
支撑服务：Knowledge / RAG / Auth / Marketing / Research
```

## 微服务

| 服务 | 端口 | 说明 |
|------|------|------|
| gateway-service | 8050 | API 网关，认证、限流、路由 |
| orchestrator-service | 8000 | Agent 编排、LLM 工具调用、会话管理 |
| tool-hub-service | 8006 | 工具注册中心、预检、调用代理 |
| business-tools | 8007 | 业务工具实现（产品/账单/ICP/营销/调研/工单） |
| knowledge-service | 8003 | 知识库管理、文档导入、索引 |
| rag-service | 8004 | 检索增强生成 |
| auth-user-service | 8001 | 用户认证、账户管理 |
| marketing-service | 8002 | 营销活动、海报生成、推广链接 |
| research-service | 8005 | 技术调研、报告生成 |
| web-user | 3000 | 用户端 Web 界面 |
| web-admin | 3100 | 管理后台 Web 界面 |

## AI Agent

| Agent | 职责 |
|-------|------|
| product_tech_agent | 云产品咨询、实例推荐、规格对比 |
| finance_order_agent | 账单查询、退款申请、发票开具 |
| icp_service_agent | ICP 备案咨询、材料提交、进度查询 |
| ops_marketing_agent | 营销活动查询、海报/文案生成、推广链接 |
| deep_research_agent | 技术选型分析、行业调研、报告生成 |

## LLM 驱动工具调用

Orchestrator 采用 LLM Function Calling 模式选择和调用业务工具：

1. 将 Agent 可用工具的 JSON Schema 传入 LLM `tools=` 参数
2. LLM 返回 `tool_calls`，决定调用哪些工具
3. 执行工具调用，将结果作为 `tool` 消息回传 LLM
4. 循环直到 LLM 不再请求工具，生成最终回答
5. 高风险工具自动降级为 `preview` 模式，需确认后执行

关键词路由作为备用路径，在 LLM 不可用时自动切换。

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- Docker & Docker Compose

### 本地开发

```bash
# 1. 安装依赖
pip install -e apps/orchestrator-service
cd apps/web-user && npm install && cd ../..
cd apps/web-admin && npm install && cd ../..

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 LLM API Key、数据库连接等

# 3. 启动服务
docker compose -f deploy/docker-compose/docker-compose.yml up -d
```

### 运行测试

```bash
# Orchestrator 单元测试
cd apps/orchestrator-service && python -m pytest tests/ -v

# 工具 Schema 适配器测试
python -m pytest tests/test_tool_schema_adapter.py -v

# LLM 工具调用循环测试
python -m pytest tests/test_llm_tool_call_loop.py -v
```

## 关键配置

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| TOOL_CALL_ENABLED | true | 启用 LLM 工具调用（关闭则走关键词路径） |
| MAX_TOOL_CALL_ROUNDS | 5 | LLM 工具调用最大轮次 |
| SMARTCLOUD_LLM_API_KEY | - | LLM API 密钥 |
| SMARTCLOUD_LLM_BASE_URL | - | LLM API 地址 |
| SMARTCLOUD_LLM_MODEL | - | LLM 模型名称 |

## 项目结构

```
SmartCloud-X/
├── apps/                    # 微服务应用
│   ├── orchestrator-service/  # 编排引擎（核心）
│   ├── business-tools/        # 业务工具
│   ├── gateway-service/       # API 网关
│   ├── knowledge-service/     # 知识库
│   ├── rag-service/           # RAG 服务
│   ├── auth-user-service/     # 认证服务
│   ├── marketing-service/     # 营销服务
│   ├── research-service/      # 调研服务
│   ├── tool-hub-service/      # 工具注册中心
│   ├── web-user/              # 用户端前端
│   └── web-admin/             # 管理后台前端
├── packages/                # 共享包
│   ├── common-schemas/       # JSON Schema 契约
│   ├── common-auth/          # 认证共享库
│   └── frontend-sdk/         # 前端 SDK
├── deploy/                  # 部署配置
│   ├── docker-compose/       # Docker Compose
│   └── k8s/                  # Kubernetes
├── docs/                    # 文档
├── openapi/                 # OpenAPI 契约
├── observability/           # 可观测性
└── scripts/                 # 脚本工具
```

## 开发规范

- 冻结区（`packages/common`、`packages/common-schemas`、`openapi/`、`docs/contracts/`）仅 foundation 工作流可修改
- 其他工作流需修改冻结区时，在 `docs/contracts/change-requests/` 提交变更申请
- 并行开发工作流顺序：foundation → web-user → orchestrator → knowledge + deploy → auth + marketing + research → frontend-sdk → integration + qa

## License

Private — All rights reserved.
