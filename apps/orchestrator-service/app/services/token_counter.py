from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)

# Empirical ratios: Chinese ~1.5 chars/token, English ~4 chars/token, mixed ~2.5
_CHARS_PER_TOKEN_ZH = 1.5
_CHARS_PER_TOKEN_MIXED = 2.5

# Common context window sizes (matched by model name substring)
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
    """Estimate token count for a text string using char-ratio heuristic."""
    if not text:
        return 0
    cjk_count = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    ratio = _CHARS_PER_TOKEN_ZH if cjk_count / max(len(text), 1) > 0.3 else _CHARS_PER_TOKEN_MIXED
    return max(1, math.ceil(len(text) / ratio))


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate total token count for a list of OpenAI-format messages."""
    total = 0
    for msg in messages:
        # Each message has ~4 tokens overhead (role, separators)
        total += 4
        content = msg.get("content", "")
        if isinstance(content, str):
            total += estimate_text_tokens(content)
        elif isinstance(content, list):
            # Multimodal content blocks
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        total += estimate_text_tokens(block.get("text", ""))
                    elif block.get("type") == "image_url":
                        total += 85  # low-res image token cost
        # Tool calls token cost
        tool_calls = msg.get("tool_calls")
        if isinstance(tool_calls, list):
            for tc in tool_calls:
                func = tc.get("function", {})
                total += estimate_text_tokens(func.get("name", ""))
                total += estimate_text_tokens(func.get("arguments", ""))
        # tool_call_id overhead
        if msg.get("tool_call_id"):
            total += 6
    return total


def get_context_window_size(model: str | None) -> int:
    """Return context window size based on model name."""
    if not model:
        return _DEFAULT_CONTEXT_WINDOW
    model_lower = model.lower()
    for key, window in _MODEL_WINDOWS.items():
        if key in model_lower:
            return window
    return _DEFAULT_CONTEXT_WINDOW


class TokenCounter:
    """Token counter with EMA calibration from LLM response usage.

    Uses char-ratio estimation by default, but calibrates the ratio
    based on actual prompt_tokens returned by the LLM so that
    subsequent estimates become more accurate.
    """

    def __init__(self) -> None:
        self._calibration_factor: float = 1.0  # actual / estimated
        self._calibration_samples: int = 0

    def estimate(self, text: str) -> int:
        raw = estimate_text_tokens(text)
        return max(1, round(raw * self._calibration_factor))

    def estimate_messages(self, messages: list[dict[str, Any]]) -> int:
        raw = estimate_messages_tokens(messages)
        return max(1, round(raw * self._calibration_factor))

    def calibrate(self, estimated: int, actual: int) -> None:
        """Calibrate using LLM response usage.prompt_tokens."""
        if actual <= 0 or estimated <= 0:
            return
        observed_ratio = actual / estimated
        # EMA (exponential moving average) update
        alpha = 0.3
        self._calibration_factor = alpha * observed_ratio + (1 - alpha) * self._calibration_factor
        self._calibration_samples += 1
        logger.debug(
            "token counter calibrated: factor=%.3f, samples=%d",
            self._calibration_factor,
            self._calibration_samples,
        )

    @property
    def calibration_factor(self) -> float:
        return self._calibration_factor
