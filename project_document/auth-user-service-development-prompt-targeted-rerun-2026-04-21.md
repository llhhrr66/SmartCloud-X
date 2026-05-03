请阅读 /home/ljr/SmartCloud-X/project_document/auth-user-service-development-prompt-2026-04-21.md，并在严格遵守其原始停止规则、验证命令和边界前提下，继续完成 auth-user-service。

这不是全局复审轮，也不是再做一遍 gap analysis。你前面多轮已经说明 auth-user-service 本身代码并不差，但现在不能继续停在“可交 review”。必须直接进入定点清障开发。

## 本轮唯一目标
只按以下顺序推进，逐项做完再进入下一项：

### 1. 先核实并补齐权限/合约接入证明
要求：
- 不要再只说“auth 合约已提供，下游是否调用取决于别人”。
- 在 auth-user-service 自己边界内，补齐能够证明 internal validate-token / check-permission / caller allow-list / denied_permissions 行为稳定的测试与文档证据。
- 如果已有实现但缺测试，就补测试；如果已有测试但口径不清，就修文档/状态说明。

### 2. 再补 user profile 的边角校验与回归覆盖
要求：
- 不止空白字符串。
- 继续查：边界长度、null/trim、非法 URL、locale/time_zone 合理性、持久化一致性、错误 envelope 稳定性。
- 能补就补代码+测试，不能补要明确风险级别。

### 3. 再补 health/ready 与 public/internal contract 证据
要求：
- 让 README、测试、状态口径和当前真实 public/internal auth contract 更严丝合缝。
- 如果 broader owned-scope validation 仍被 marketing/research 拖住，必须把“这不是 auth 自身 blocker”的证据写得更硬，而不是一句话带过。

## 强制规则
1. 禁止再做整轮泛审/泛 gap analysis。
2. 禁止再只输出“auth 本身可以 review，问题在别的服务”就停。
3. 必须至少新增一个真实代码/测试/文档层面的收口动作，而不是纯复述现状。
4. 每完成一项，必须立即：
   - 跑真实测试
   - 跑 compileall
   - 自审是否真的闭环
   - 更新结论
5. 如果某项未完成，必须输出 P0 / P1 / P2 / P3 风险，并继续下一步，而不是停在 review。
6. 只有在以下两种情况之一才允许停止：
   - 本轮定点缺口（权限/合约证明、profile 边角覆盖、contract/health 文档证据）都闭环；
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
- 本轮新增了什么真实能力或真实证据
- auth-user-service 核心职责还剩什么没完成

如果你再次只是复述“本服务已可 review，问题在别处”而没有真正补代码/补测试/补文档证据，本轮视为失败。
