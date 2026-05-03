from __future__ import annotations

import ast
import logging
from typing import Any

LOGGER_NAME = "smartcloud.gateway"
logger = logging.getLogger(LOGGER_NAME)


def configure_logging() -> None:
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def sanitize_log_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return {str(key): sanitize_log_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [sanitize_log_value(item) for item in value]
    return str(value)


def log_event(event: str, **fields: Any) -> None:
    payload = {"event": event}
    for key, value in fields.items():
        payload[key] = sanitize_log_value(value)
    logger.info(repr(payload))


def parse_log_payload(message: str) -> dict[str, Any] | None:
    try:
        payload = ast.literal_eval(message)
    except (SyntaxError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None
