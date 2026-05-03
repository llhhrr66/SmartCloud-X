# output_schema
输出需满足以下字段约束：
- final_answer: string | null
- citations: string[]
- tool_calls: array
- next_agent: string | null
- confidence: number (0.0-1.0)

要求：
- final_answer 只基于用户问题、工具结果和保底事实答案生成。
- 不得编造账单金额、备案状态、营销结果或研究结论。
- 当状态为 handoff 时，需明确说明将转交下一个 agent 继续处理。
- 当状态为 need_user_input 时，需明确缺少的信息或需要的确认。