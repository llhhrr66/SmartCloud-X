请阅读 /home/ljr/SmartCloud-X/project_document/tool-hub-service-development-prompt-2026-04-21.md 并按照其中指示完成 tool-hub-service 开发任务。

这次按用户的严格要求执行，不允许只做一轮审计/验证就停。

新增强制规则：
1. 你必须一个一个检查提示词中的任务项，明确判断“代码是否真的完成”“测试是否真的完成”。
2. 对任何未完成、证据不足、仍有残余风险的点，必须列出 P0 / P1 / P2 / P3 风险分级。
3. 列出风险后，不允许直接停止；必须继续执行开发 + 测试 + 审阅 + 修复循环。
4. 只有在以下两种情况之一才允许停止：
   - 所有可完成任务均已真正完成；
   - 只剩真实 blocked 项，且你已按原任务文件要求完成多轮修复。
5. 不允许因为“可以交 review”“本轮验证通过”“现状已基本具备”就停止。
6. 必须在最终输出中显式说明：
   - 是否还需要下一轮开发/测试/审阅循环
   - 如果需要，下一轮先做什么
7. 必须输出：
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

继续遵守原任务文件中的优先级、停止规则和验证命令。