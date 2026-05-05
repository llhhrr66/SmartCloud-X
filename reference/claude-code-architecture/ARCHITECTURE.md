# Claude Code 架构深度解析

> 基于 `XiaoMaColtAI/claude-code-source` 反编译源码的架构分析，提炼可借鉴的设计模式。

---

## 一、核心架构概览

```
┌─────────────────────────────────────────────────┐
│                   QueryEngine                    │  ← 核心编排器
│  (对话上下文 / 工具调度 / 响应处理 / 状态管理)     │
├─────────────────────────────────────────────────┤
│              Tool Registry (tools.ts)             │  ← 工具注册中心
│  getAllBaseTools() → assembleToolPool()          │
│  → filterToolsByDenyRules()                      │
├──────────┬──────────┬───────────┬───────────────┤
│ AgentTool│BashTool  │FileTools  │ 40+ 更多工具   │  ← 具体工具实现
│ (子Agent)│(Shell)   │(R/W/Edit) │                │
├──────────┴──────────┴───────────┬───────────────┤
│       Coordinator Mode          │ Plan Mode      │  ← 高级模式
│  (多Worker编排)                 │ (先规划后执行)  │
├────────────────────────────────┬────────────────┤
│    Permissions System          │  Task System    │  ← 横切关注点
│  (auto/ask/deny/yoloClassifier)│ (TodoWrite)    │
└────────────────────────────────┴────────────────┘
```

---

## 二、多 Agent 协作机制（核心亮点）

### 2.1 Agent 生命周期

```
                    ┌──────────────┐
                    │  AgentTool   │  入口
                    │  .call()     │
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────────┐
        │ One-Shot │ │  Sync    │ │   Async      │
        │ (Explore │ │ (前景Agent│ │ (后台Agent)  │
        │  Plan)   │ │ 阻塞等待) │ │ 立即返回ID   │
        └──────────┘ └────┬─────┘ └──────┬───────┘
                          │              │
                          │    auto-back-│ground timer
                          │    (超时自动│转后台)
                          ▼              ▼
                    ┌──────────────────────────┐
                    │  runAsyncAgentLifecycle  │
                    │  ┌─ makeStream() ──────┐ │
                    │  │ AsyncGenerator<Msg> │ │  ← LLM 流式迭代
                    │  └────────────────────┘ │
                    │  → progress tracking    │
                    │  → summarize (长对话)   │
                    │  → classifyHandoff      │  ← 安全审查
                    │  → enqueue notification │  ← 通知父Agent
                    └──────────────────────────┘
```

**关键设计**：
- **Sync → Async 自动降级**：前景 Agent 运行超过阈值（autoBackgroundMs）后自动转为后台执行，不阻塞用户
- **One-Shot 内置Agent**：Explore、Plan 等不走完整生命周期，用完即弃，更轻量
- **每个 Agent 有独立的消息流**：`agentMessages[]` 独立收集，不与主对话混合

### 2.2 Agent 间通信

```
┌──────────┐  SendMessage   ┌──────────────┐
│ Agent A  │ ──────────────→│ Agent B      │
│ (Lead)   │                │ (Worker)     │
│          │←─── Mailbox ────│              │
│          │  notification   │              │
└──────────┘                 └──────────────┘

通信方式:
1. SendMessage(to: "agent-xyz", message: "...")
2. writeToMailbox(recipient, {from, text, summary, timestamp})
3. <<task-notification>> XML 格式的结果回传
```

**消息类型**（Zod discriminatedUnion）：
```typescript
z.discriminatedUnion('type', [
  { type: 'shutdown_request', reason?: string },       // 请求关闭
  { type: 'shutdown_response', request_id, approve },   // 关闭响应
  { type: 'plan_approval_response', request_id, approve, feedback? } // Plan审批
])
```

**核心约束**：
- **Workers 看不到主对话**：每个 prompt 必须自包含（self-contained）
- **通知是单向的**：Worker 结果通过 `<<task-notification>>` XML 以 user-role 消息形式注入主对话
- **可以继续或重新创建**：`SendMessage` 继续已有 worker（保留上下文），或 `Agent` 创建新的（干净状态）

### 2.3 Coordinator 模式（最值得借鉴）

Coordinator 是一个**纯粹的编排者**，不直接操作文件，只调度 Worker：

```
用户请求
   │
   ▼
┌─────────────────────────────────┐
│        Coordinator (Lead)        │
│                                  │
│  ┌─ Research Phase ───────────┐  │
│  │ Agent(worker, "调查Auth")  │  │  ← 并行启动
│  │ Agent(worker, "调查测试")  │  │
│  └────────────────────────────┘  │
│          │ 等待通知               │
│          ▼                        │
│  ┌─ Synthesis ────────────────┐  │
│  │  阅读研究结果的文件路径、     │  │  ← Coordinator 自己做
│  │  行号、类型签名              │  │
│  │  合成实施规格                │  │
│  └────────────────────────────┘  │
│          │                        │
│  ┌─ Implementation Phase ─────┐  │
│  │ SendMessage(worker, spec) │  │  ← 继续已有worker
│  └────────────────────────────┘  │
│          │                        │
│  ┌─ Verification Phase ───────┐  │
│  │ Agent(worker, "验证")     │  │  ← 新worker，新鲜视角
│  └────────────────────────────┘  │
└─────────────────────────────────┘
```

**Coordinator 的 Worker 工具白名单**（异步 Agent 允许的工具集）：
```
ASYNC_AGENT_ALLOWED_TOOLS = {
  Bash, Read, Write, Edit, Glob, Grep,     // 文件/系统操作
  WebSearch, WebFetch,                       // 网络访问
  Agent, SendMessage,                         // 子Agent通信
  TaskCreate, TaskUpdate, TaskList,           // 任务协调
  EnterPlanMode, ExitPlanMode,               // 计划模式
  NotebookEdit,                               // Jupyter
  MCP tools, Skill tool                       // 扩展
}
```

**Worker 不允许的工具**：
```
ALL_AGENT_DISALLOWED_TOOLS: AgentTool (防止无限嵌套), 其他危险操作
CUSTOM_AGENT_DISALLOWED_TOOLS: 额外限制自定义Agent
```

---

## 三、Tool 系统设计

### 3.1 工具基类与注册

```typescript
// Tool.ts - 核心类型
interface Tool {
  name: string
  inputSchema: ZodSchema      // Zod 做参数校验
  outputSchema: ZodSchema     // 输出也有 schema

  // 生命周期
  call(input, context): Promise<ToolResult>
  checkPermissions(input, context): PermissionResult
  renderToolUseMessage(): ReactNode    // UI 渲染

  // 元数据
  isReadOnly(): boolean       // 只读工具不需权限
  isConcurrencySafe(): boolean  // 可并发执行
  toAutoClassifierInput(input): string  // 自动模式分类
}

// tools.ts - 注册中心
function assembleToolPool(appState): Tools {
  const baseTools = getAllBaseTools()    // 所有内置工具
  const mcpTools = getMcpTools()         // MCP 动态工具
  const allTools = [...baseTools, ...mcpTools]
  return filterToolsByDenyRules(allTools, denyRules)
}
```

### 3.2 工具过滤的三层防御

```
Layer 1: filterToolsForAgent()
  ├── MCP 工具始终放行
  ├── Plan 模式放行 ExitPlanMode
  ├── ALL_AGENT_DISALLOWED_TOOLS 硬黑名单
  ├── CUSTOM_AGENT_DISALLOWED_TOOLS 自定义黑名单
  └── ASYNC_AGENT_ALLOWED_TOOLS 白名单（异步Agent）

Layer 2: resolveAgentTools()
  ├── disallowedTools 额外过滤（Agent定义中指定）
  ├── 通配符 '*' 允许全部（过滤后）
  └── 逐个验证工具名是否存在

Layer 3: checkPermissions()
  ├── PermissionMode: auto / ask / deny
  └── yoloClassifier: AI 判断是否自动放行
```

### 3.3 Prompt 构建（agentToolUtils.ts 的精妙之处）

**resolveAgentTools** 的 Agent 工具特殊处理：
```typescript
// Agent 工具的特殊元数据: allowedAgentTypes
// "Agent(worker, researcher)" → allowedAgentTypes = ["worker", "researcher"]
// 子Agent中Agent被排除，但元数据被保留用于跟踪
if (toolName === AGENT_TOOL_NAME) {
  if (ruleContent) {
    allowedAgentTypes = ruleContent.split(',').map(s => s.trim())
  }
  if (!isMainThread) {
    validTools.push(toolSpec)  // 标记有效但不解析
    continue                    // 子Agent不能创建子子Agent
  }
}
```

---

## 四、安全审查：Handoff Classifier

子 Agent 完成后，结果返回主 Agent 前，经过安全审查：

```typescript
async function classifyHandoffIfNeeded({
  agentMessages, tools, toolPermissionContext, abortSignal, subagentType
}): Promise<string | null> {
  // 1. 构建 Agent 对话的摘要
  const agentTranscript = buildTranscriptForClassifier(agentMessages, tools)

  // 2. AI 分类器判断是否违规
  const classifierResult = await classifyYoloAction(
    agentMessages,
    reviewPrompt,  // "Review the sub-agent's work based on block rules"
    tools,
    toolPermissionContext,
    abortSignal,
  )

  // 3. 三种结果
  // unavailable → 放行但加警告
  // blocked → 加安全警告
  // allowed → 正常放行
}
```

**这是极好的安全模式**：子 Agent 的输出不直接信任，而是经过一个轻量 AI 审查。类似"交叉验证"思路。

---

## 五、任务系统（Task System）

### 5.1 任务状态机

```
          ┌──────────┐
          │ pending  │ ← TaskCreate
          └────┬─────┘
               │
          ┌────▼─────┐
          │in_progress│ ← TaskUpdate(status: "in_progress")
          └────┬─────┘
               │
     ┌─────────┼──────────┐
     ▼         ▼          ▼
┌─────────┐┌────────┐┌────────┐
│completed││ blocked││deleted │
└─────────┘└────────┘└────────┘
```

### 5.2 任务间的阻塞依赖

```typescript
// TaskUpdate 支持 addBlocks / addBlockedBy
addBlocks: z.array(z.string()).optional()    // 这个任务阻塞哪些任务
addBlockedBy: z.array(z.string()).optional() // 这个任务被哪些任务阻塞
```

类似 Kanban 看板的依赖关系，适合多 Agent 并行编排。

### 5.3 任务与 Agent 的关联

每个异步 Agent 自动创建一个 Task，Task 的 `taskId` 就是 `agentId`：
- Agent 完成 → Task 标记 `completed`
- Agent 失败 → Task 标记 `failed` + error message
- Agent 被杀 → Task 标记 `killed` + 部分结果
- 用户通过 `TaskStop` 可随时终止 Agent

---

## 六、可借鉴的设计模式总结

### 6.1 直接可用

| 模式 | 描述 | SmartCloud-X 应用场景 |
|------|------|----------------------|
| **Tool 基类 + Zod Schema** | 工具统一接口，输入输出都有类型校验 | orchestrator 的工具注册体系 |
| **Agent 工具白名单** | 不同类型 Agent 可用不同工具子集 | 不同角色 Agent（research/marketing/admin）的权限隔离 |
| **Sync→Async 自动降级** | 前景 Agent 超时自动转后台 | 长时间运行的 Agent 任务（如海报生成） |
| **Handoff 安全审查** | 子Agent输出经 AI 审查后才返回主Agent | Agent 链式调用时的安全检查点 |
| **Self-contained Prompt** | 每个 Agent 的 prompt 必须完整自包含 | 多 Agent 编排的 prompt 设计规范 |
| **Task 阻塞依赖** | addBlocks/addBlockedBy 任务依赖图 | 复杂工作流编排（研究→实施→验证） |

### 6.2 架构级借鉴

| 模式 | 描述 |
|------|------|
| **Coordinator 编排模式** | Lead 只调度不执行，Worker 只执行不决策。4 阶段：Research → Synthesis → Implementation → Verification |
| **Continue vs Spawn 决策** | 高上下文重叠 → SendMessage 继续；低重叠 → 新建 Agent。验证用新 Agent（新鲜视角） |
| **工具过滤三层防御** | 全局黑名单 → Agent 定义过滤 → 运行时权限检查 |
| **通知式结果回传** | `<<task-notification>>` XML 格式，不阻塞，通过事件驱动 |

### 6.3 Claude Code 的 Anti-Patterns（应避免）

| 反模式 | 问题 |
|--------|------|
| `"Based on your findings, fix the bug"` | 懒惰委托——把理解也推给子Agent |
| 一个 Worker 检查另一个 Worker | 浪费资源，用通知机制 |
| 验证者和实现者共享上下文 | 验证需要新鲜视角，不应带实现偏见 |

---

## 七、源码关键文件索引

| 文件 | 行数 | 核心内容 |
|------|------|----------|
| `tools/AgentTool/AgentTool.tsx` | 1398 | Agent 入口、sync/async 路径、生命周期 |
| `tools/AgentTool/agentToolUtils.ts` | 687 | filterToolsForAgent、resolveAgentTools、finalizeAgentTool、classifyHandoffIfNeeded、runAsyncAgentLifecycle |
| `coordinator/coordinatorMode.ts` | 370 | Coordinator 系统提示词、Worker 工具集、多阶段编排指南 |
| `tools/SendMessageTool/SendMessageTool.tsx` | 917 | Agent 间通信、Mailbox 机制、广播 |
| `tools/AgentTool/builtInAgents.ts` | 73 | 内置 Agent 定义（Explore/Plan/Verification） |
| `Tool.ts` | 369 | 工具基类、buildTool()、ToolUseContext |
| `tools.ts` | ~200 | 工具注册、assembleToolPool、deny rules |
| `tasks/LocalAgentTask/LocalAgentTask.ts` | ~500 | 异步 Agent 状态管理、进度追踪 |
| `utils/permissions/permissions.ts` | 1487 | 权限检查流水线 |
| `utils/permissions/yoloClassifier.ts` | 1496 | AI 自动模式分类器 |
