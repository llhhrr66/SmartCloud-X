from __future__ import annotations

MEMORY_SECTIONS = [
    ("会话标题", "用 5-10 个字概括本次对话的核心主题"),
    ("当前状态", "对话当前处于什么阶段？正在做什么？"),
    ("任务规格", "用户明确提出的需求和约束条件"),
    ("文件与函数", "涉及的关键文件路径、函数名、API 端点"),
    ("工作流程", "已执行的操作步骤和流程"),
    ("错误与修正", "遇到的错误及其修复措施"),
    ("知识库文档", "检索到的相关文档和知识库条目"),
    ("经验教训", "过程中发现的重要规律、陷阱、最佳实践"),
    ("关键结果", "已交付的具体结果（含数据、结论、输出物）"),
    ("工作日志", "按时间顺序的操作记录（精简）"),
]

MEMORY_SECTIONS_TEMPLATE = "\n".join(
    f"### {title}\n{desc}" for title, desc in MEMORY_SECTIONS
)

# Initial extraction prompt — placeholders filled at runtime with config values
SESSION_MEMORY_INIT_PROMPT = """你需要从下方对话历史中提取结构化会话记忆。这些记忆将用于未来会话的上下文恢复，使新助手能够快速理解对话背景。

请严格按照以下 {section_count} 个章节输出，每个章节不超过 {max_tokens_per_section} tokens，总计不超过 {max_total_tokens} tokens。
只保留关键信息，省略冗余细节。

{sections_template}

以下是对话历史：

{messages_text}"""

# Incremental update prompt
SESSION_MEMORY_UPDATE_PROMPT = """你需要基于新的对话内容更新现有的会话记忆。

【现有记忆】
{existing_memory}

【新增对话内容】
{new_messages_text}

请更新各个章节，保留仍然有效的旧信息，添加新信息，删除过时内容。
每个章节不超过 {max_tokens_per_section} tokens，总计不超过 {max_total_tokens} tokens。

{sections_template}"""
