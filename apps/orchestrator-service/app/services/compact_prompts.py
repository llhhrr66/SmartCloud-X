from __future__ import annotations

# No tools allowed during compaction — pure text summarization only
NO_TOOLS_PREAMBLE = (
    "你正在进行对话历史压缩任务。你必须只输出分析文本和结构化摘要，"
    "不能调用任何工具、不能搜索、不能读取文件。只基于下方提供的对话内容进行压缩。"
)

# 9 summary sections (aligned with Claude Code but adapted for Chinese enterprise context)
SUMMARY_SECTIONS = [
    ("1. 对话目标", "本次对话的核心任务和目标是什么？用户想完成什么？"),
    ("2. 已完成的工作", "到目前为止已经完成了哪些步骤？哪些任务已经交付？"),
    ("3. 关键决策与结论", "做出了哪些重要决定？得出了什么结论？"),
    ("4. 使用过的工具与结果摘要", "调用了哪些工具？关键结果是什么？（不要重复原始数据，只保留摘要）"),
    ("5. 用户偏好与要求", "用户表达了什么偏好、约束或特殊要求？"),
    ("6. 当前进展与状态", "现在进行到哪一步？是否有未完成的任务？"),
    ("7. 重要实体与上下文", "涉及的产品、订单、工单、客户等关键实体及其 ID/编号"),
    ("8. 错误与修正记录", "遇到了什么错误？采取了什么修正措施？"),
    ("9. 待办与下一步", "还需要做什么？用户明确或隐含期望的后续步骤"),
]

SUMMARY_SECTIONS_TEMPLATE = "\n".join(
    f"### {title}\n{desc}" for title, desc in SUMMARY_SECTIONS
)


def build_base_compact_prompt(messages_text: str) -> str:
    """Full compaction prompt: compress all history messages."""
    return f"""{NO_TOOLS_PREAMBLE}

你需要将下方对话历史压缩为一份结构化摘要。摘要必须保留所有关键信息，
使得一个全新的助手只读摘要就能无缝继续对话，不会丢失重要上下文。

请先在 <analysis> 标签中分析对话，然后在 <summary> 标签中输出结构化摘要。

<analysis>
逐条审视对话消息，标记：
- 关键决策点
- 重要实体（产品名/订单号/工单号）
- 用户明确表达的偏好
- 工具调用的核心结果（不要保留原始数据，只保留结论）
- 错误及其修正
- 当前进展状态
</analysis>

<summary>
{SUMMARY_SECTIONS_TEMPLATE}
</summary>

以下是需要压缩的对话历史：

{messages_text}"""


def build_partial_compact_prompt(
    older_messages_text: str,
    recent_messages_text: str,
) -> str:
    """Partial compaction prompt: compress older messages, keep recent ones raw."""
    return f"""{NO_TOOLS_PREAMBLE}

你需要将下方的【旧对话历史】压缩为结构化摘要，同时保留【最近对话】的原始内容。
摘要必须保留旧对话中的所有关键信息，使助手能够理解完整对话背景。

请先在 <analysis> 标签中分析旧对话，然后在 <summary> 标签中输出结构化摘要。

<analysis>
逐条审视【旧对话历史】，标记：
- 关键决策点
- 重要实体（产品名/订单号/工单号）
- 用户明确表达的偏好
- 工具调用的核心结果
- 错误及其修正
- 当前进展状态
</analysis>

<summary>
{SUMMARY_SECTIONS_TEMPLATE}
</summary>

===旧对话历史（需要压缩）===

{older_messages_text}

===最近对话（保留原文）===

{recent_messages_text}"""


def build_up_to_compact_prompt(
    older_messages_text: str,
    pivot_summary: str,
    recent_messages_text: str,
) -> str:
    """Up-to compaction prompt: compress up to a pivot message.

    Suitable for compaction before an agent handoff point.
    """
    return f"""{NO_TOOLS_PREAMBLE}

你需要将下方的【早期对话历史】压缩为结构化摘要。
【切换点摘要】提供了中间一个关键节点的信息，【切换点之后】的消息保留原文。

请先在 <analysis> 标签中分析早期对话，然后在 <summary> 标签中输出结构化摘要。

<analysis>
逐条审视【早期对话历史】，标记：
- 关键决策点
- 重要实体（产品名/订单号/工单号）
- 用户明确表达的偏好
- 工具调用的核心结果
- 错误及其修正
</analysis>

<summary>
{SUMMARY_SECTIONS_TEMPLATE}
</summary>

===早期对话历史（需要压缩）===

{older_messages_text}

===切换点摘要===

{pivot_summary}

===切换点之后的对话（保留原文）===

{recent_messages_text}"""
