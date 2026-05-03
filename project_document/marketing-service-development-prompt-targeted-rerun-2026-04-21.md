请阅读 /home/ljr/SmartCloud-X/project_document/marketing-service-development-prompt-2026-04-21.md，并在严格遵守其原始停止规则、验证命令和边界前提下，继续完成 marketing-service。

这不是全局复审轮，也不是再做一遍 gap analysis。你前面多轮已经明确知道 marketing-service 未完成点集中在少数具体缺口。现在禁止继续泛化复述，必须直接进入定点清障开发。

## 本轮唯一目标
只按以下顺序推进，逐项做完再进入下一项：

### 1. 先补 /readyz 为真实 backend readiness 探测
要求：
- 不能再只是配置态/config-level readiness。
- 至少对任务文件要求的关键后端给出真实连通性/可用性判断。
- 若某些后端未配置，可明确为 disabled；但已配置的后端不能只做静态判断。

### 2. 再补 tracing / metrics 对关键失败路径的覆盖
要求：
- 补 MinIO 操作、MongoDB upsert、Celery enqueue、auth validation 的关键 span/metric 覆盖。
- 至少做到：成功/失败路径都能在代码和测试中看到证据。

### 3. 再补 P5 测试缺口
优先顺序：
- MinIO bucket missing / upload failure / object missing or delete-related path
- Celery worker execution / enqueue failure path
- MongoDB upsert failure path
- 并发幂等更严格的竞争场景
- readyz up/down 探测场景

### 4. 最后修 README 口径
要求：
- 让 README 与真实实现一致
- 不能再出现“README 已写得很全，但能力其实还没闭环”的情况

## 强制规则
1. 禁止再做整轮泛审/泛 gap analysis。
2. 禁止再重复输出“还有这些缺口，下轮再做”而不真正补代码/补测试。
3. 禁止把已有 provider abstraction、现有 15 tests 通过、或 observability 基础接入，误当成任务整体完成。
4. 每完成一项，必须立即：
   - 跑真实测试
   - 跑 compileall
   - 自审是否真的闭环
   - 更新结论
5. 如果某项未完成，必须输出 P0 / P1 / P2 / P3 风险，并继续下一步，而不是停在 review。
6. 只有在以下两种情况之一才允许停止：
   - /readyz 真探测 + tracing/metrics 关键失败路径 + P5 关键测试补齐都闭环；
   - 某项命中真实 blocker，且已按原任务文件要求做足修复尝试。

## 本轮最终必须输出
- modified files
- completed items
- remaining items
- blocked items
- validation commands/results
- completion table
- known limitations
- P0 risks
- P1 risks
- P2 risks
- P3 risks
- 本轮新增了什么真实能力
- marketing-service 核心职责还剩什么没完成

如果你再次只是复述“还需要下一轮”而没有真正补 /readyz、补 tracing/metrics、补测试，本轮视为失败。
