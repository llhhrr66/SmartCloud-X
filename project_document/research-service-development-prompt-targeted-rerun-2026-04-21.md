请阅读 /home/ljr/SmartCloud-X/project_document/research-service-development-prompt-2026-04-21.md，并在严格遵守其原始停止规则、验证命令和边界前提下，继续完成 research-service。

这不是全局复审轮，也不是再做一遍 gap analysis。你上一轮已经明确知道 research-service 未完成，且未完成点非常具体。现在禁止再做泛化复述，必须直接进入定点清障开发。

## 本轮唯一目标
只按以下顺序推进，逐项做完再进入下一项：

### 1. 先补“最小真实 markdown 导出闭环”
要求：
- 不能再只返回 placeholder download_url。
- 至少要让 research 任务完成后生成真实 markdown 产物或稳定可读取的导出内容。
- 导出结果必须能通过测试和代码证据证明“不是占位符”。

### 2. 再补“最小真实报告生成闭环”
要求：
- 不能再只是固定模板占位。
- 至少基于 topic / scope / reference_urls 真实生成可区分的 summary、sections、citations 或 metadata。
- 不要求一步到生产级，但必须不是“输入不同，结果仍基本一样”的固定假内容。

### 3. 如有余力，再补“最小 external search adapter”
要求：
- 即使只是可配置 HTTP stub / mockable search provider，也必须让 external search 不再只是 capability 声称。
- 如果这一步做不完，可标记为 remaining / blocked，但前两步必须优先完成。

## 强制规则
1. 禁止再做整轮泛审/泛 gap analysis。
2. 禁止再用“现有测试通过”“可以交 review”“已有 provider abstraction”替代核心职责开发。
3. 禁止把 observability / lifecycle / abstraction 完成误当成 research 核心能力完成。
4. 每完成一项，必须立即：
   - 跑真实测试
   - 跑 compileall
   - 自审是否真的闭环
   - 更新结论
5. 如果某项未完成，必须输出 P0 / P1 / P2 / P3 风险，并继续下一步，而不是停在 review。
6. 只有在以下两种情况之一才允许停止：
   - markdown 导出 + 最小真实报告生成均已闭环，并通过验证；
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
- research-service 核心职责还剩什么没完成

如果你再次只是复述“当前还没完成、下轮该做什么”而没有真正补导出/补报告生成，本轮视为失败。
