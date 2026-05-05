# Prompt 4: 长对话上下文压缩系统（Context Compaction）

> 借鉴 Claude Code `services/compact/` + `services/SessionMemory/` 架构，
> 为 SmartCloud-X orchestrator-service 实现分层上下文压缩。

---

## 一、现状问题

SmartCloud-X 当前上下文管理极其原始：

| 组件 | 当前实现 | 问题 |
|------|----------|------|
| `SessionContext.history_summary` | pipe 分隔字符串，480 字符 / 6 条上限 | 信息密度极低，截断丢失关键信息 |
| `SessionContext.recent_messages` | 滑动窗口，`max_history_turns=20` | 窗口外信息完全丢失，无摘要保留 |
| `_compact_text()` | 硬截断 80 字符 | 语义断裂，无法保留关键信息 |
| Token 计数 | **不存在** | 无法感知上下文窗口压力 |
| LLM 摘要 | **不存在** | 全靠硬截断，无智能压缩 |
| SSE usage 指标 | `prompt_tokens=0` 硬编码 | 无法追踪真实 token 消耗 |

Claude Code 的解法是**多层压缩**：micro-compact（轻量清理）→ auto-compact（LLM 摘要）→ session memory（结构化笔记），我们需要借鉴这套分层机制。

---

## 二、架构设计

```
                    ┌──────────────────────────────────────────┐
                    │       对话消息流（ChatMessageRecord[]）   │
                    └──────────────┬───────────────────────────┘
                                   │
                    ┌──────────────▼───────────────────────────┐
                    │         TokenCounter（估算）              │  ← 第一层：token 估算
                    │   estimate_messages_tokens() → int       │
                    └──────────────┬───────────────────────────┘
                                   │
                    ┌──────────────▼───────────────────────────┐
                    │        AutoCompactTrigger                 │  ← 第二层：自动触发判定
                    │  threshold = context_window - buffer     │
                    │  circuit_breaker: 3 连续失败暂停          │
                    └──────┬──────────────┬────────────────────┘
                           │              │
                ┌──────────▼──┐    ┌──────▼──────────┐
                │ MicroCompact │    │  FullCompact     │  ← 第三层：压缩执行
                │ (轻量清理)    │    │  (LLM 摘要)      │
                │ 旧工具结果清空│    │  3种模板按场景选  │
                └──────────────┘    └──────┬───────────┘
                                         │
                    ┌─────────────────────▼────────────────────┐
                    │        CompactedSessionContext             │  ← 第四层：压缩后上下文
                    │  history_summary: str (LLM 生成)         │
                    │  recent_messages: list (保留最近 N 条)    │
                    │  compact_meta: CompactionMetadata         │
                    └──────────────────────────────────────────┘
                                         │
                    ┌─────────────────────▼────────────────────┐
                    │        SessionMemoryExtractor             │  ← 第五层：会话记忆提取
                    │  10 节 Markdown 模板，LLM 后台提取        │
                    │  Redis 持久化，跨会话复用                  │
                    └──────────────────────────────────────────┘
```

---

## 三、文件变更清单

| 文件 | 操作 | 核心内容 |
|------|------|----------|
| `app/services/token_counter.py` | **新建** | Token 估算（字符比例法 + LLM usage 缓存校准） |
| `app/services/compact.py` | **新建** | 3 种压缩策略 + AutoCompact 触发 + Circuit Breaker |
| `app/services/compact_prompts.py` | **新建** | 3 个压缩 Prompt 模板（BASE / PARTIAL / UP_TO） |
| `app/services/micro_compact.py` | **新建** | 轻量旧工具结果清理（时间阈值 + 缓存编辑） |
| `app/services/session_memory.py` | **新建** | 会话记忆提取器 + 10 节 Markdown 模板 |
| `app/services/session_memory_prompts.py` | **新建** | 记忆提取 Prompt 模板（初始化 + 增量更新） |
| `app/services/session_memory_store.py` | **新建** | Redis 持久化（读/写/按会话查询） |
| `app/models/compact.py` | **新建** | CompactionMetadata + SessionMemoryRecord 模型 |
| `app/core/config.py` | **修改** | 新增 compaction 相关配置字段 |
| `app/services/conversation_context_merge.py` | **修改** | integrate compacted context into derive_next_session_context |
| `app/services/agent_answer_generator.py` | **修改** | 注入 compacted history_summary 到 system prompt |
| `app/services/llm_tool_call_loop.py` | **修改** | 发送消息前检测是否需要 compaction |
| `app/api/routes/orchestration.py` | **修改** | _execute_message 流程中加入 compaction 检查点 |
| `app/services/streaming.py` | **修改** | SSE usage 字段填充真实 token 数据 |

---

## 四、详细实现规格

### 4.1 `app/models/compact.py` — 新模型

```python
from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field


class CompactionStrategy(str, Enum):
    FULL = "full"           # 全量压缩：所有历史消息 → 摘要
    PARTIAL = "partial"     # 部分压缩：最早的一组消息 → 摘要，保留最近
    UP_TO = "up_to"         # 压缩到某条消息为止（pivot message_id）


class CompactionMetadata(BaseModel):
    """记录一次压缩操作的元数据，存入 SessionContext.attributes"""
    strategy: CompactionStrategy
    original_message_count: int
    original_token_estimate: int
    compacted_message_count: int       # 被压缩掉的消息数
    compacted_token_estimate: int      # 压缩后摘要的 token 估算
    compacted_at: str                  # ISO 8601
    compact_summary: str               # LLM 生成的压缩摘要
    rounds_compacted: list[int]        # 被压缩的 API round 编号
    trigger_reason: str                # "auto_threshold" / "manual" / "micro_compact"


class SessionMemoryRecord(BaseModel):
    """会话记忆，Redis 持久化"""
    conversation_id: str
    sections: dict[str, str]           # 10 个 section → markdown 文本
    total_tokens_estimate: int
    version: int = 1
    extracted_at: str
    updated_at: str


class SessionMemoryConfig(BaseModel):
    """记忆提取阈值配置"""
    min_tokens_to_init: int = 10000    # 首次提取最低 token 门槛
    tokens_between_updates: int = 5000 # 两次更新之间的 token 增量
    tool_calls_between_updates: int = 3
    max_tokens_per_section: int = 2000
    max_total_tokens: int = 12000
```

### 4.2 `app/services/token_counter.py` — Token 估算

**设计原则**：不引入 tiktoken 依赖（tiktoken 需要下载词表文件，部署麻烦），使用字符比例估算 + LLM response usage 校准。

```python
from __future__ import annotations
import logging
import math
from typing import Any

logger = logging.getLogger(__name__)

# 经验比例：中文约 1.5 字符/token，英文约 4 字符/token，混合取 2.5
_CHARS_PER_TOKEN_ZH = 1.5
_CHARS_PER_TOKEN_EN = 4.0
_CHARS_PER_TOKEN_MIXED = 2.5

# 常见 context window 大小（按模型名匹配）
_DEFAULT_CONTEXT_WINDOW = 128000
_MODEL_WINDOWS: dict[str, int] = {
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4-turbo": 128000,
    "gpt-3.5-turbo": 16385,
    "gpt-5.3-codex-spark": 128000,
    "deepseek-chat": 65536,
}


def estimate_text_tokens(text: str) -> int:
    """估算一段文本的 token 数。混合中英文用折中比例。"""
    if not text:
        return 0
    # 简单启发：如果 CJK 字符占比 > 30%，用中文比例
    cjk_count = sum(1 for ch in text if '\u4e00' <= ch <= '\u9fff')
    ratio = _CHARS_PER_TOKEN_ZH if cjk_count / max(len(text), 1) > 0.3 else _CHARS_PER_TOKEN_MIXED
    return max(1, math.ceil(len(text) / ratio))


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """估算一组 OpenAI-format messages 的总 token 数。"""
    total = 0
    for msg in messages:
        # 每条消息的固定开销 ~4 tokens (role, separators)
        total += 4
        content = msg.get("content", "")
        if isinstance(content, str):
            total += estimate_text_tokens(content)
        elif isinstance(content, list):
            # multimodal content blocks
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        total += estimate_text_tokens(block.get("text", ""))
                    elif block.get("type") == "image_url":
                        total += 85  # low-res image token cost
        # tool_calls 的 token
        tool_calls = msg.get("tool_calls")
        if isinstance(tool_calls, list):
            for tc in tool_calls:
                func = tc.get("function", {})
                total += estimate_text_tokens(func.get("name", ""))
                total += estimate_text_tokens(func.get("arguments", ""))
        # tool_call_id
        if msg.get("tool_call_id"):
            total += 6
    return total


def get_context_window_size(model: str | None) -> int:
    """根据模型名返回 context window 大小。"""
    if not model:
        return _DEFAULT_CONTEXT_WINDOW
    model_lower = model.lower()
    for key, window in _MODEL_WINDOWS.items():
        if key in model_lower:
            return window
    return _DEFAULT_CONTEXT_WINDOW


class TokenCounter:
    """带校准的 token 计数器。

    利用 LLM response.usage 字段校准估算偏差，
    后续估算会更准确。
    """

    def __init__(self) -> None:
        self._calibration_factor = 1.0  # actual_tokens / estimated_tokens
        self._calibration_samples = 0

    def estimate(self, text: str) -> int:
        raw = estimate_text_tokens(text)
        return max(1, round(raw * self._calibration_factor))

    def estimate_messages(self, messages: list[dict[str, Any]]) -> int:
        raw = estimate_messages_tokens(messages)
        return max(1, round(raw * self._calibration_factor))

    def calibrate(self, estimated: int, actual: int) -> None:
        """用 LLM 返回的 usage.prompt_tokens 校准。"""
        if actual <= 0 or estimated <= 0:
            return
        observed_ratio = actual / estimated
        # EMA (指数移动平均) 更新校准系数
        alpha = 0.3
        self._calibration_factor = (
            alpha * observed_ratio + (1 - alpha) * self._calibration_factor
        )
        self._calibration_samples += 1
        logger.debug(
            "token counter calibrated: factor=%.3f, samples=%d",
            self._calibration_factor,
            self._calibration_samples,
        )

    @property
    def calibration_factor(self) -> float:
        return self._calibration_factor
```

### 4.3 `app/services/compact_prompts.py` — 压缩 Prompt 模板

借鉴 Claude Code `services/compact/prompt.ts` 的三模板设计，但适配 SmartCloud-X 的业务场景（企业智能体对话，中文为主）。

```python
from __future__ import annotations

# 不允许压缩过程中调用任何工具——纯文本摘要
NO_TOOLS_PREAMBLE = (
    "你正在进行对话历史压缩任务。你必须只输出分析文本和结构化摘要，"
    "不能调用任何工具、不能搜索、不能读取文件。只基于下方提供的对话内容进行压缩。"
)

# 9 个摘要章节（与 Claude Code 对齐，但适配中文企业场景）
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
    """全量压缩 Prompt：压缩所有历史消息。"""
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
    """部分压缩 Prompt：压缩旧消息，保留最近消息的原始内容。"""
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
    """向上压缩 Prompt：压缩到 pivot 消息为止，保留 pivot 之后的消息原文。

    适用场景：在某个 agent 切换点之前做压缩。
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
```

### 4.4 `app/services/compact.py` — 核心压缩引擎

```python
from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.core.config import Settings, get_settings
from app.models.compact import (
    CompactionMetadata,
    CompactionStrategy,
)
from app.services.token_counter import TokenCounter, get_context_window_size

logger = logging.getLogger(__name__)

# Auto-compact 触发的缓冲 token 数（类似 Claude Code 的 13K buffer）
_COMPACT_BUFFER_TOKENS = 13000

# Circuit breaker: 连续失败次数上限
_CIRCUIT_BREAKER_MAX_FAILURES = 3

# 每组消息的最大 token 数（用于分组压缩）
_MAX_TOKENS_PER_GROUP = 40000


class AutoCompactTrigger:
    """自动压缩触发判定器。

    借鉴 Claude Code 的 autoCompact.ts:
    - threshold = context_window - buffer_tokens
    - 如果估算 token 数 >= threshold，触发压缩
    - Circuit breaker: 连续失败 N 次后暂停自动压缩
    """

    def __init__(
        self,
        settings: Settings | None = None,
        token_counter: TokenCounter | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._counter = token_counter or TokenCounter()
        self._consecutive_failures = 0
        self._circuit_open = False

    def should_compact(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
    ) -> tuple[bool, int, int]:
        """判断是否需要压缩。

        Returns:
            (should_compact, estimated_tokens, threshold)
        """
        if self._circuit_open:
            logger.debug("auto-compact circuit breaker open, skipping")
            return False, 0, 0

        context_window = get_context_window_size(model or self._settings.llm_model)
        threshold = max(
            context_window - _COMPACT_BUFFER_TOKENS,
            self._settings.compact_min_threshold_tokens,
        )
        estimated = self._counter.estimate_messages(messages)
        should = estimated >= threshold
        if should:
            logger.info(
                "auto-compact triggered: estimated=%d >= threshold=%d (window=%d)",
                estimated, threshold, context_window,
            )
        return should, estimated, threshold

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._circuit_open = False

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= _CIRCUIT_BREAKER_MAX_FAILURES:
            self._circuit_open = True
            logger.warning(
                "auto-compact circuit breaker opened after %d consecutive failures",
                self._consecutive_failures,
            )


def _extract_summary_from_response(text: str) -> str:
    """从 LLM 响应中提取 <summary> 标签内容。"""
    match = re.search(r"<summary>(.*?)</summary>", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Fallback: 如果没有标签，整个响应作为摘要（去掉 analysis 部分）
    analysis_match = re.search(r"</analysis>(.*)", text, re.DOTALL)
    if analysis_match:
        return analysis_match.group(1).strip()
    return text.strip()


def _format_messages_for_compact(messages: list[dict[str, Any]]) -> str:
    """将消息列表格式化为纯文本，供压缩 Prompt 使用。"""
    lines = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if isinstance(content, list):
            # 多模态内容，只取 text 部分
            text_parts = [
                b.get("text", "") for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            content = " ".join(text_parts)
        content = str(content) if content else ""
        # 截断单条过长的消息
        if len(content) > 2000:
            content = content[:2000] + "...[truncated]"
        lines.append(f"[{role}] {content}")
        # 工具调用信息
        tool_calls = msg.get("tool_calls")
        if isinstance(tool_calls, list):
            for tc in tool_calls:
                func = tc.get("function", {})
                name = func.get("name", "")
                args = func.get("arguments", "")
                if len(args) > 500:
                    args = args[:500] + "...[truncated]"
                lines.append(f"  [tool_call] {name}({args})")
    return "\n".join(lines)


def _group_messages_by_round(
    messages: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """按 API round 对消息分组。

    借鉴 Claude Code 的 groupMessagesByApiRound()：
    每当出现新的 assistant 消息（非 tool 角色），视为新 round 开始。
    """
    if not messages:
        return []
    groups: list[list[dict[str, Any]]] = []
    current_group: list[dict[str, Any]] = [messages[0]]
    for msg in messages[1:]:
        role = msg.get("role", "")
        # 新的 assistant 消息（不是 tool result）= 新 round
        if role == "assistant" and not msg.get("tool_calls"):
            groups.append(current_group)
            current_group = [msg]
        else:
            current_group.append(msg)
    if current_group:
        groups.append(current_group)
    return groups


def compact_conversation(
    messages: list[dict[str, Any]],
    *,
    strategy: CompactionStrategy = CompactionStrategy.FULL,
    pivot_message_id: str | None = None,
    settings: Settings | None = None,
    token_counter: TokenCounter | None = None,
) -> tuple[list[dict[str, Any]], CompactionMetadata]:
    """核心压缩函数。

    Args:
        messages: 原始消息列表（OpenAI format）
        strategy: 压缩策略
        pivot_message_id: UP_TO 策略的 pivot 消息 ID

    Returns:
        (compacted_messages, metadata)
        compacted_messages 包含：[system + summary_message] + retained_recent_messages
    """
    _settings = settings or get_settings()
    _counter = token_counter or TokenCounter()
    original_token_est = _counter.estimate_messages(messages)

    # 1. 分组
    groups = _group_messages_by_round(messages)

    if strategy == CompactionStrategy.FULL:
        return _compact_full(messages, groups, original_token_est, _settings, _counter)
    elif strategy == CompactionStrategy.PARTIAL:
        return _compact_partial(messages, groups, original_token_est, _settings, _counter)
    elif strategy == CompactionStrategy.UP_TO:
        return _compact_up_to(
            messages, groups, original_token_est, pivot_message_id,
            _settings, _counter,
        )
    else:
        raise ValueError(f"unknown compaction strategy: {strategy}")


def _compact_full(
    all_messages: list[dict[str, Any]],
    groups: list[list[dict[str, Any]]],
    original_token_est: int,
    settings: Settings,
    counter: TokenCounter,
) -> tuple[list[dict[str, Any]], CompactionMetadata]:
    """全量压缩：所有消息 → LLM 摘要，只保留最近 N 条原文。"""
    from app.services.compact_prompts import build_base_compact_prompt

    # 保留最近 N 条消息不压缩（最近 2 轮）
    retain_count = settings.compact_retain_recent_rounds * 2  # user+assistant per round
    messages_to_compact = all_messages[:-retain_count] if retain_count < len(all_messages) else []
    retained = all_messages[-retain_count:] if retain_count < len(all_messages) else all_messages

    if not messages_to_compact:
        # 无需压缩
        meta = CompactionMetadata(
            strategy=CompactionStrategy.FULL,
            original_message_count=len(all_messages),
            original_token_estimate=original_token_est,
            compacted_message_count=0,
            compacted_token_estimate=0,
            compacted_at=_now_iso(),
            compact_summary="",
            rounds_compacted=[],
            trigger_reason="no_messages_to_compact",
        )
        return all_messages, meta

    # 构建 Prompt
    text_to_compact = _format_messages_for_compact(messages_to_compact)
    prompt = build_base_compact_prompt(text_to_compact)

    # 调用 LLM 生成摘要
    summary = _call_llm_for_compact(prompt, settings)

    # 构建压缩后的消息列表
    summary_message = {
        "role": "system",
        "content": f"[对话历史压缩摘要]\n\n{summary}",
        "name": "compacted_history",
    }
    compacted = [summary_message, *retained]

    compacted_token_est = counter.estimate_messages(compacted)
    meta = CompactionMetadata(
        strategy=CompactionStrategy.FULL,
        original_message_count=len(all_messages),
        original_token_estimate=original_token_est,
        compacted_message_count=len(messages_to_compact),
        compacted_token_estimate=compacted_token_est,
        compacted_at=_now_iso(),
        compact_summary=summary[:500],
        rounds_compacted=list(range(len(groups) - max(settings.compact_retain_recent_rounds, 0))),
        trigger_reason="auto_threshold",
    )
    return compacted, meta


def _compact_partial(
    all_messages: list[dict[str, Any]],
    groups: list[list[dict[str, Any]]],
    original_token_est: int,
    settings: Settings,
    counter: TokenCounter,
) -> tuple[list[dict[str, Any]], CompactionMetadata]:
    """部分压缩：压缩最早的一组消息，保留最近的。"""
    from app.services.compact_prompts import build_partial_compact_prompt

    if len(groups) <= 1:
        # 只有一组，退化为 full compact
        return _compact_full(all_messages, groups, original_token_est, settings, counter)

    # 找到需要压缩的旧消息组（token 累积超过阈值的最早组）
    older_messages: list[dict[str, Any]] = []
    recent_messages: list[dict[str, Any]] = []
    token_accum = 0
    split_idx = len(groups)

    for i, group in enumerate(groups):
        group_tokens = counter.estimate_messages(group)
        token_accum += group_tokens
        if token_accum >= _MAX_TOKENS_PER_GROUP and i < len(groups) - 1:
            split_idx = i + 1
            break

    older_messages = [msg for g in groups[:split_idx] for msg in g]
    recent_messages = [msg for g in groups[split_idx:] for msg in g]

    if not older_messages:
        meta = CompactionMetadata(
            strategy=CompactionStrategy.PARTIAL,
            original_message_count=len(all_messages),
            original_token_estimate=original_token_est,
            compacted_message_count=0,
            compacted_token_estimate=0,
            compacted_at=_now_iso(),
            compact_summary="",
            rounds_compacted=[],
            trigger_reason="no_older_messages",
        )
        return all_messages, meta

    older_text = _format_messages_for_compact(older_messages)
    recent_text = _format_messages_for_compact(recent_messages)
    prompt = build_partial_compact_prompt(older_text, recent_text)

    summary = _call_llm_for_compact(prompt, settings)

    summary_message = {
        "role": "system",
        "content": f"[早期对话压缩摘要]\n\n{summary}",
        "name": "compacted_older_history",
    }
    compacted = [summary_message, *recent_messages]

    compacted_token_est = counter.estimate_messages(compacted)
    meta = CompactionMetadata(
        strategy=CompactionStrategy.PARTIAL,
        original_message_count=len(all_messages),
        original_token_estimate=original_token_est,
        compacted_message_count=len(older_messages),
        compacted_token_estimate=compacted_token_est,
        compacted_at=_now_iso(),
        compact_summary=summary[:500],
        rounds_compacted=list(range(split_idx)),
        trigger_reason="auto_threshold",
    )
    return compacted, meta


def _compact_up_to(
    all_messages: list[dict[str, Any]],
    groups: list[list[dict[str, Any]]],
    original_token_est: int,
    pivot_message_id: str | None,
    settings: Settings,
    counter: TokenCounter,
) -> tuple[list[dict[str, Any]], CompactionMetadata]:
    """向上压缩：压缩到 pivot 消息为止。"""
    from app.services.compact_prompts import build_up_to_compact_prompt

    if not pivot_message_id:
        # 没有 pivot，退化为 partial
        return _compact_partial(all_messages, groups, original_token_est, settings, counter)

    # 找到 pivot 消息的位置
    pivot_idx = None
    for i, msg in enumerate(all_messages):
        if msg.get("message_id") == pivot_message_id or msg.get("id") == pivot_message_id:
            pivot_idx = i
            break

    if pivot_idx is None:
        logger.warning("pivot message %s not found, falling back to partial compact", pivot_message_id)
        return _compact_partial(all_messages, groups, original_token_est, settings, counter)

    older_messages = all_messages[:pivot_idx]
    recent_messages = all_messages[pivot_idx:]

    if not older_messages:
        meta = CompactionMetadata(
            strategy=CompactionStrategy.UP_TO,
            original_message_count=len(all_messages),
            original_token_estimate=original_token_est,
            compacted_message_count=0,
            compacted_token_estimate=0,
            compacted_at=_now_iso(),
            compact_summary="",
            rounds_compacted=[],
            trigger_reason="no_older_messages",
        )
        return all_messages, meta

    older_text = _format_messages_for_compact(older_messages)
    recent_text = _format_messages_for_compact(recent_messages)

    # 用 pivot 消息作为切换点摘要
    pivot_msg = all_messages[pivot_idx]
    pivot_summary = str(pivot_msg.get("content", ""))[:300]

    prompt = build_up_to_compact_prompt(older_text, pivot_summary, recent_text)
    summary = _call_llm_for_compact(prompt, settings)

    summary_message = {
        "role": "system",
        "content": f"[切换点之前对话压缩摘要]\n\n{summary}",
        "name": "compacted_pre_pivot_history",
    }
    compacted = [summary_message, *recent_messages]

    compacted_token_est = counter.estimate_messages(compacted)
    meta = CompactionMetadata(
        strategy=CompactionStrategy.UP_TO,
        original_message_count=len(all_messages),
        original_token_estimate=original_token_est,
        compacted_message_count=len(older_messages),
        compacted_token_estimate=compacted_token_est,
        compacted_at=_now_iso(),
        compact_summary=summary[:500],
        rounds_compacted=[],
        trigger_reason="manual_pivot",
    )
    return compacted, meta


def _call_llm_for_compact(prompt: str, settings: Settings) -> str:
    """调用 LLM 生成压缩摘要。使用轻量级模型以节省成本。"""
    try:
        from openai import OpenAI
    except ImportError:
        logger.error("openai package not available for compaction")
        return ""

    api_key = settings.llm_api_key
    base_url = settings.llm_base_url
    model = settings.compact_model or settings.llm_model

    if not api_key:
        logger.warning("no LLM API key configured for compaction")
        return ""

    try:
        client = OpenAI(
            api_key=api_key,
            base_url=_normalize_url(base_url),
            timeout=float(settings.compact_timeout_seconds),
            max_retries=1,
        )
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=settings.compact_max_output_tokens,
        )
        content = response.choices[0].message.content if response.choices else ""
        return _extract_summary_from_response(content or "")
    except Exception as exc:
        logger.error("LLM compaction call failed: %s", exc)
        raise


def _normalize_url(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip().rstrip("/")
    if not url:
        return None
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.path in {"", "/"}:
        return f"{url}/v1"
    return url


def _now_iso() -> str:
    from datetime import UTC, datetime
    return datetime.now(UTC).isoformat()
```

### 4.5 `app/services/micro_compact.py` — 轻量清理

借鉴 Claude Code 的 `microCompact.ts`：不调用 LLM，只是清理旧的、体积大的工具结果。

```python
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

_CLEAR_MARKER = "[旧工具结果已清理]"

# 默认：超过 60 分钟的工具结果清理
_DEFAULT_TIME_GAP_MINUTES = 60

# 单条工具结果超过此字符数时标记清理
_DEFAULT_SIZE_THRESHOLD_CHARS = 3000


def micro_compact_messages(
    messages: list[dict[str, Any]],
    *,
    time_gap_minutes: int = _DEFAULT_TIME_GAP_MINUTES,
    size_threshold_chars: int = _DEFAULT_SIZE_THRESHOLD_CHARS,
    now_iso: str | None = None,
) -> list[dict[str, Any]]:
    """轻量级旧工具结果清理。不调用 LLM，只清除大体积/陈旧的工具返回。

    规则：
    1. 如果一条 tool role 消息的 content 长度 > size_threshold_chars
       且距上一条 user 消息超过 time_gap_minutes → 清理
    2. 清理方式：将 content 替换为 _CLEAR_MARKER，保留 tool_call_id
    """
    if not messages:
        return messages

    now = datetime.fromisoformat(now_iso) if now_iso else datetime.now(UTC)
    result: list[dict[str, Any]] = []
    last_user_time: datetime | None = None

    for msg in messages:
        role = msg.get("role", "")
        created_at = msg.get("created_at")

        # 追踪最近的 user 消息时间
        if role == "user" and created_at:
            try:
                last_user_time = datetime.fromisoformat(created_at)
            except (ValueError, TypeError):
                pass

        # 检查是否需要清理 tool 结果
        if role == "tool":
            content = msg.get("content", "")
            content_len = len(str(content)) if content else 0
            should_clear = False

            # 条件 1：内容过长
            if content_len > size_threshold_chars:
                should_clear = True

            # 条件 2：时间间隔过长
            if (
                last_user_time
                and created_at
                and content_len > 500  # 太短的没必要清理
            ):
                try:
                    msg_time = datetime.fromisoformat(created_at)
                    gap = (now - msg_time).total_seconds() / 60
                    if gap > time_gap_minutes:
                        should_clear = True
                except (ValueError, TypeError):
                    pass

            if should_clear:
                cleaned = dict(msg)
                cleaned["content"] = _CLEAR_MARKER
                cleaned["_micro_compacted"] = True
                result.append(cleaned)
                continue

        result.append(msg)

    cleared_count = sum(1 for m in result if m.get("_micro_compacted"))
    if cleared_count:
        logger.info("micro-compact cleared %d tool results", cleared_count)

    return result
```

### 4.6 `app/services/session_memory_prompts.py` — 会话记忆 Prompt

借鉴 Claude Code `services/SessionMemory/prompts.ts` 的 10 节模板。

```python
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

# 首次提取 Prompt
SESSION_MEMORY_INIT_PROMPT = """你需要从下方对话历史中提取结构化会话记忆。这些记忆将用于未来会话的上下文恢复，使新助手能够快速理解对话背景。

请严格按照以下 10 个章节输出，每个章节不超过 2000 tokens，总计不超过 12000 tokens。
只保留关键信息，省略冗余细节。

{sections_template}

以下是对话历史：

{messages_text}"""

# 增量更新 Prompt
SESSION_MEMORY_UPDATE_PROMPT = """你需要基于新的对话内容更新现有的会话记忆。

【现有记忆】
{existing_memory}

【新增对话内容】
{new_messages_text}

请更新各个章节，保留仍然有效的旧信息，添加新信息，删除过时内容。
每个章节不超过 2000 tokens，总计不超过 12000 tokens。

{sections_template}"""
```

### 4.7 `app/services/session_memory.py` — 会话记忆提取器

```python
from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.core.config import Settings, get_settings
from app.models.compact import SessionMemoryConfig, SessionMemoryRecord
from app.services.token_counter import TokenCounter

logger = logging.getLogger(__name__)


class SessionMemoryExtractor:
    """借鉴 Claude Code SessionMemory 的后台记忆提取器。

    阈值控制：
    - 首次提取：对话 token 估算 >= min_tokens_to_init
    - 增量更新：距上次更新的 token 增量 >= tokens_between_updates
      或 工具调用增量 >= tool_calls_between_updates
    """

    def __init__(
        self,
        settings: Settings | None = None,
        token_counter: TokenCounter | None = None,
        config: SessionMemoryConfig | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._counter = token_counter or TokenCounter()
        self._config = config or SessionMemoryConfig()

    def should_extract(
        self,
        existing_memory: SessionMemoryRecord | None,
        messages: list[dict[str, Any]],
    ) -> bool:
        """判断是否应该触发记忆提取。"""
        total_tokens = self._counter.estimate_messages(messages)

        if existing_memory is None:
            # 首次提取
            return total_tokens >= self._config.min_tokens_to_init

        # 增量更新：比较 token 增量
        delta_tokens = total_tokens - existing_memory.total_tokens_estimate
        return delta_tokens >= self._config.tokens_between_updates

    def extract_memory(
        self,
        conversation_id: str,
        messages: list[dict[str, Any]],
        existing_memory: SessionMemoryRecord | None = None,
    ) -> SessionMemoryRecord | None:
        """提取会话记忆。首次或增量更新。"""
        from app.services.session_memory_prompts import (
            SESSION_MEMORY_INIT_PROMPT,
            SESSION_MEMORY_UPDATE_PROMPT,
            MEMORY_SECTIONS_TEMPLATE,
        )

        messages_text = self._format_messages(messages)

        if existing_memory is None:
            # 首次提取
            prompt = SESSION_MEMORY_INIT_PROMPT.format(
                sections_template=MEMORY_SECTIONS_TEMPLATE,
                messages_text=messages_text,
            )
        else:
            # 增量更新
            existing_text = self._format_sections(existing_memory.sections)
            new_text = messages_text  # 传入全部消息，让 LLM 自行判断新增部分
            prompt = SESSION_MEMORY_UPDATE_PROMPT.format(
                existing_memory=existing_text,
                new_messages_text=new_text,
                sections_template=MEMORY_SECTIONS_TEMPLATE,
            )

        result_text = self._call_llm(prompt)
        if not result_text:
            return None

        sections = self._parse_sections(result_text)
        total_tokens = self._counter.estimate_messages(messages)
        now = self._now_iso()

        return SessionMemoryRecord(
            conversation_id=conversation_id,
            sections=sections,
            total_tokens_estimate=total_tokens,
            version=(existing_memory.version + 1) if existing_memory else 1,
            extracted_at=existing_memory.extracted_at if existing_memory else now,
            updated_at=now,
        )

    def _format_messages(self, messages: list[dict[str, Any]]) -> str:
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = str(msg.get("content", ""))[:1000]
            lines.append(f"[{role}] {content}")
        return "\n".join(lines)

    def _format_sections(self, sections: dict[str, str]) -> str:
        return "\n\n".join(f"### {k}\n{v}" for k, v in sections.items())

    def _parse_sections(self, text: str) -> dict[str, str]:
        """从 LLM 输出中解析 10 个章节。"""
        sections: dict[str, str] = {}
        # 匹配 ### 标题 模式
        pattern = r"###\s*(.+?)\s*\n(.*?)(?=###|$)"
        for match in re.finditer(pattern, text, re.DOTALL):
            title = match.group(1).strip()
            content = match.group(2).strip()
            if content:
                # 截断过长章节
                if len(content) > self._config.max_tokens_per_section * 2:
                    content = content[: self._config.max_tokens_per_section * 2]
                sections[title] = content
        return sections

    def _call_llm(self, prompt: str) -> str:
        """调用 LLM 生成记忆。"""
        try:
            from openai import OpenAI
        except ImportError:
            logger.error("openai package not available for session memory extraction")
            return ""

        api_key = self._settings.llm_api_key
        base_url = self._settings.llm_base_url
        model = self._settings.compact_model or self._settings.llm_model

        if not api_key:
            return ""

        try:
            client = OpenAI(
                api_key=api_key,
                base_url=self._normalize_url(base_url),
                timeout=float(self._settings.compact_timeout_seconds),
                max_retries=1,
            )
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=self._settings.compact_max_output_tokens * 2,  # 记忆可能更长
            )
            return response.choices[0].message.content or "" if response.choices else ""
        except Exception as exc:
            logger.error("session memory LLM call failed: %s", exc)
            return ""

    @staticmethod
    def _normalize_url(url: str | None) -> str | None:
        if not url:
            return None
        url = url.strip().rstrip("/")
        if not url:
            return None
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.path in {"", "/"}:
            return f"{url}/v1"
        return url

    @staticmethod
    def _now_iso() -> str:
        from datetime import UTC, datetime
        return datetime.now(UTC).isoformat()
```

### 4.8 `app/services/session_memory_store.py` — Redis 持久化

```python
from __future__ import annotations

import json
import logging
from typing import Any

from app.models.compact import SessionMemoryRecord

logger = logging.getLogger(__name__)

# Redis key: smartcloud:session-memory:{conversation_id}
_KEY_TEMPLATE = "smartcloud:session-memory:{conversation_id}"
_TTL_SECONDS = 86400 * 7  # 7 天 TTL


class SessionMemoryStore:
    """Redis 持久化会话记忆。"""

    def __init__(self, redis_client: Any) -> None:
        self._client = redis_client

    def get(self, conversation_id: str) -> SessionMemoryRecord | None:
        if self._client is None:
            return None
        try:
            key = _KEY_TEMPLATE.format(conversation_id=conversation_id)
            raw = self._client.get(key)
            if not raw:
                return None
            return SessionMemoryRecord.model_validate_json(raw)
        except Exception as exc:
            logger.warning("session memory store get failed: %s", exc)
            return None

    def put(self, record: SessionMemoryRecord) -> None:
        if self._client is None:
            return
        try:
            key = _KEY_TEMPLATE.format(conversation_id=record.conversation_id)
            self._client.set(key, record.model_dump_json(), ex=_TTL_SECONDS)
        except Exception as exc:
            logger.warning("session memory store put failed: %s", exc)

    def delete(self, conversation_id: str) -> None:
        if self._client is None:
            return
        try:
            key = _KEY_TEMPLATE.format(conversation_id=conversation_id)
            self._client.delete(key)
        except Exception as exc:
            logger.warning("session memory store delete failed: %s", exc)
```

### 4.9 `app/core/config.py` 修改 — 新增配置字段

在 `Settings` 类中添加以下字段：

```python
# ─── Context Compaction ──────────────────────────────────
compact_enabled: bool = Field(default=True, alias="COMPACT_ENABLED")
compact_model: str | None = Field(default=None, alias="COMPACT_MODEL")
compact_min_threshold_tokens: int = Field(default=30000, alias="COMPACT_MIN_THRESHOLD_TOKENS")
compact_retain_recent_rounds: int = Field(default=2, alias="COMPACT_RETAIN_RECENT_ROUNDS")
compact_max_output_tokens: int = Field(default=4000, alias="COMPACT_MAX_OUTPUT_TOKENS")
compact_timeout_seconds: int = Field(default=30, alias="COMPACT_TIMEOUT_SECONDS")
compact_strategy: Literal["full", "partial", "up_to"] = Field(
    default="partial", alias="COMPACT_STRATEGY"
)
micro_compact_enabled: bool = Field(default=True, alias="MICRO_COMPACT_ENABLED")
micro_compact_time_gap_minutes: int = Field(default=60, alias="MICRO_COMPACT_TIME_GAP_MINUTES")
micro_compact_size_threshold_chars: int = Field(
    default=3000, alias="MICRO_COMPACT_SIZE_THRESHOLD_CHARS"
)
session_memory_enabled: bool = Field(default=True, alias="SESSION_MEMORY_ENABLED")
session_memory_min_tokens_to_init: int = Field(
    default=10000, alias="SESSION_MEMORY_MIN_TOKENS_TO_INIT"
)
session_memory_tokens_between_updates: int = Field(
    default=5000, alias="SESSION_MEMORY_TOKENS_BETWEEN_UPDATES"
)
```

同时在 `passthrough_keys` 集合中添加所有新的别名。

在 `_validate_positive` 的 validator 列表中添加所有新的数值型字段。

### 4.10 `app/services/conversation_context_merge.py` 修改

**修改 `derive_next_session_context()` 方法**：在构建 `history_summary` 之前，检查是否有 `CompactionMetadata`，如果有，用压缩摘要替代硬截断的 pipe 分隔字符串。

```python
# 在 derive_next_session_context 方法中，替换 history_summary 的构建逻辑：

# --- 旧逻辑（删除）---
# merged.history_summary = ConversationContextMerger._merge_history_summary(
#     merged.history_summary,
#     message_request.user_query,
#     assistant_summary,
# )

# --- 新逻辑 ---
compact_meta = merged.attributes.get("_compaction_metadata")
if isinstance(compact_meta, dict) and compact_meta.get("compact_summary"):
    # 有压缩摘要：用压缩摘要作为 history_summary 的基础
    merged.history_summary = compact_meta["compact_summary"][:2000]
else:
    # 无压缩摘要：保留原逻辑
    merged.history_summary = ConversationContextMerger._merge_history_summary(
        merged.history_summary,
        message_request.user_query,
        assistant_summary,
    )
```

### 4.11 `app/services/agent_answer_generator.py` 修改

在 `generate()` 和 `create_with_tools()` 方法中，注入压缩后的 history_summary：

```python
def generate(self, *, agent, user_query, status, next_agent, fallback_answer, tool_calls,
             compacted_history: str | None = None) -> str | None:
    # ... existing code ...
    messages = [
        {"role": "system", "content": self._system_prompt_for(agent)},
    ]
    # 注入压缩摘要
    if compacted_history:
        messages.append({
            "role": "system",
            "content": f"[对话历史摘要]\n{compacted_history}",
            "name": "compacted_history",
        })
    messages.append({
        "role": "user",
        "content": self._build_user_content(...),
    })
```

### 4.12 `app/services/llm_tool_call_loop.py` 修改

在工具调用循环的**每轮开始**前，检测是否需要压缩：

```python
# 在 tool_call_loop 的 while 循环顶部加入：
if settings.compact_enabled:
    from app.services.compact import AutoCompactTrigger, compact_conversation
    trigger = AutoCompactTrigger(settings=settings, token_counter=counter)
    should, est, threshold = trigger.should_compact(current_messages, model=model)
    if should:
        try:
            compacted, meta = compact_conversation(
                current_messages,
                strategy=CompactionStrategy(settings.compact_strategy),
                settings=settings,
                token_counter=counter,
            )
            current_messages = compacted
            trigger.record_success()
            logger.info("auto-compact applied: %d → %d messages", len(current_messages), len(compacted))
        except Exception as exc:
            trigger.record_failure()
            logger.warning("auto-compact failed (circuit breaker aware): %s", exc)

    # 同时执行 micro-compact
    if settings.micro_compact_enabled:
        from app.services.micro_compact import micro_compact_messages
        current_messages = micro_compact_messages(current_messages)
```

### 4.13 `app/api/routes/orchestration.py` 修改

在 `_execute_message()` 流程中加入 compaction 检查点：

```python
# 在 route_request() 之后、_run_orchestration() 之前加入：

# 1. 获取历史消息
messages = await conversation_store.list_messages(conversation_id)

# 2. Micro-compact 预清理
if settings.micro_compact_enabled:
    from app.services.micro_compact import micro_compact_messages
    messages = micro_compact_messages(
        messages,
        time_gap_minutes=settings.micro_compact_time_gap_minutes,
        size_threshold_chars=settings.micro_compact_size_threshold_chars,
    )

# 3. Auto-compact 检查
if settings.compact_enabled:
    from app.services.compact import AutoCompactTrigger, compact_conversation
    from app.models.compact import CompactionStrategy
    trigger = AutoCompactTrigger(settings=settings)
    should, est, threshold = trigger.should_compact(messages)
    if should:
        try:
            compacted_messages, meta = compact_conversation(
                messages,
                strategy=CompactionStrategy(settings.compact_strategy),
                settings=settings,
            )
            # 将 meta 存入 session context attributes
            session_context.attributes["_compaction_metadata"] = meta.model_dump(mode="json")
            messages = compacted_messages
            trigger.record_success()
        except Exception as exc:
            trigger.record_failure()
            logger.warning("compaction failed at orchestration entry: %s", exc)

# 4. Session memory 提取（后台，不阻塞）
if settings.session_memory_enabled:
    try:
        from app.services.session_memory import SessionMemoryExtractor
        from app.services.session_memory_store import SessionMemoryStore
        extractor = SessionMemoryExtractor(settings=settings)
        existing = memory_store.get(conversation_id)
        if extractor.should_extract(existing, messages):
            # 使用 asyncio.run_in_executor 在后台执行
            import asyncio
            loop = asyncio.get_event_loop()
            loop.run_in_executor(
                None,
                _background_extract_memory,
                extractor, memory_store, conversation_id, messages, existing,
            )
    except Exception as exc:
        logger.debug("session memory extraction skipped: %s", exc)
```

新增辅助函数：

```python
def _background_extract_memory(
    extractor, store, conversation_id, messages, existing,
) -> None:
    """后台线程：提取会话记忆并存储到 Redis。"""
    try:
        record = extractor.extract_memory(conversation_id, messages, existing)
        if record:
            store.put(record)
    except Exception as exc:
        logger.warning("background session memory extraction failed: %s", exc)
```

### 4.14 `app/services/streaming.py` 修改

将 SSE usage 的硬编码零值改为从 LLM response 填充：

```python
# 旧：
# usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

# 新：从 AgentExecutionResult 中获取
usage = {
    "prompt_tokens": getattr(result, "prompt_tokens", 0) or 0,
    "completion_tokens": getattr(result, "completion_tokens", 0) or 0,
    "total_tokens": getattr(result, "total_tokens", 0) or 0,
}
```

同时让 `OpenAICompatibleAgentAnswerGenerator.generate()` 返回 usage 信息，在 `AgentExecutionResult` 模型中增加 `prompt_tokens` / `completion_tokens` / `total_tokens` 字段。

---

## 五、集成流程总览

```
用户消息 → orchestration._execute_message()
                │
                ├─ 1. 获取历史消息 (conversation_store.list_messages)
                │
                ├─ 2. Micro-compact 预清理 ← 清除大的/旧的 tool 结果
                │
                ├─ 3. Auto-compact 检查 ← token 估算 ≥ threshold？
                │     │ Yes → compact_conversation() → LLM 摘要
                │     │ No  → 原样保留
                │
                ├─ 4. Session memory 提取 ← 后台 asyncio 线程
                │     存入 Redis (smartcloud:session-memory:{id})
                │
                ├─ 5. route_request() ← 路由到 Agent
                │
                ├─ 6. _run_orchestration()
                │     └─ agent_runtime.execute()
                │         └─ llm_tool_call_loop()
                │             ├─ 每轮开始：compact 检查
                │             ├─ 每轮开始：micro-compact
                │             └─ LLM response → calibrate token counter
                │
                └─ 7. persist_exchange() ← 存储 + SSE
                      └─ SSE usage 填充真实 token 数据
```

---

## 六、测试要求

### 单元测试

| 测试文件 | 覆盖内容 |
|----------|----------|
| `tests/test_token_counter.py` | estimate_text_tokens (中/英/混合)、estimate_messages (含 tool_calls)、calibrate 校准 |
| `tests/test_compact_prompts.py` | 3 个 prompt 模板输出格式、NO_TOOLS_PREAMBLE 存在性 |
| `tests/test_compact.py` | compact_conversation 3 种策略、AutoCompactTrigger 阈值判定、circuit breaker、_group_messages_by_round |
| `tests/test_micro_compact.py` | 时间间隔清理、大小阈值清理、短内容保留、空消息列表 |
| `tests/test_session_memory.py` | should_extract 阈值、extract_memory 首次/增量、_parse_sections |
| `tests/test_session_memory_store.py` | Redis get/put/delete、None client 降级 |

### 集成测试关键场景

1. **20 轮对话 → 触发 auto-compact**：构造长对话，验证压缩后 token 数显著下降
2. **micro-compact 清理旧工具结果**：插入带时间戳的大体积 tool 消息，验证被清理
3. **Session memory 跨对话复用**：对话 A 提取记忆，对话 B 读取并注入 context
4. **Circuit breaker 生效**：模拟 LLM 失败 3 次，验证自动停止压缩

---

## 七、环境变量 / Docker 配置

在 `deploy/docker-compose/.env` 和 `docker-compose.yml` 的 orchestrator-service environment 中新增：

```yaml
COMPACT_ENABLED: ${COMPACT_ENABLED:-true}
COMPACT_MODEL: ${COMPACT_MODEL:-}
COMPACT_MIN_THRESHOLD_TOKENS: ${COMPACT_MIN_THRESHOLD_TOKENS:-30000}
COMPACT_RETAIN_RECENT_ROUNDS: ${COMPACT_RETAIN_RECENT_ROUNDS:-2}
COMPACT_MAX_OUTPUT_TOKENS: ${COMPACT_MAX_OUTPUT_TOKENS:-4000}
COMPACT_TIMEOUT_SECONDS: ${COMPACT_TIMEOUT_SECONDS:-30}
COMPACT_STRATEGY: ${COMPACT_STRATEGY:-partial}
MICRO_COMPACT_ENABLED: ${MICRO_COMPACT_ENABLED:-true}
MICRO_COMPACT_TIME_GAP_MINUTES: ${MICRO_COMPACT_TIME_GAP_MINUTES:-60}
MICRO_COMPACT_SIZE_THRESHOLD_CHARS: ${MICRO_COMPACT_SIZE_THRESHOLD_CHARS:-3000}
SESSION_MEMORY_ENABLED: ${SESSION_MEMORY_ENABLED:-true}
SESSION_MEMORY_MIN_TOKENS_TO_INIT: ${SESSION_MEMORY_MIN_TOKENS_TO_INIT:-10000}
SESSION_MEMORY_TOKENS_BETWEEN_UPDATES: ${SESSION_MEMORY_TOKENS_BETWEEN_UPDATES:-5000}
```

---

## 八、依赖说明

**零新增 Python 依赖**。全部使用 stdlib + 已有的 `openai` SDK + 已有的 `redis-py`。
Token 计数使用字符比例估算 + LLM usage 校准，不引入 tiktoken。
