# Web User SSE Samples

这些 `.sse` 文件用于保留用户端聊天页可回放的事件样例，覆盖：

- `normal-stream.sse`：基础 `message.started -> message.delta -> message.completed`
- `tool-handoff-stream.sse`：`agent.routed -> tool.started -> tool.finished -> message.completed`
- `error-stream.sse`：`message.started -> agent.routed -> tool.started -> message.error`

适合后续接入：

- 前端回放调试
- SSE 事件映射单测
- 与后端 staging 返回进行逐事件比对
