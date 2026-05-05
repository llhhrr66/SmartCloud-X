"""Hook system for tool execution interception (business-tools layer).

This is the local-catalog counterpart to the tool-hub-service hooks module.
Both share the same HookDecision/HookEvent models but this module can be
imported directly by StaticBusinessTool without reaching across services.
"""
from __future__ import annotations

import fnmatch
import importlib
import json
import logging
from enum import Enum
from typing import Any, Literal
from urllib.request import Request as URLRequest, urlopen
from urllib.error import URLError

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class HookEvent(str, Enum):
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"


class HookDecision(BaseModel):
    """Result of a single hook evaluation."""
    action: Literal["allow", "warn", "block"] = "allow"
    message: str = ""
    modified_payload: dict[str, Any] | None = None  # PRE only


class HookRegistration(BaseModel):
    """A registered hook with matching criteria and handler info."""
    hook_id: str
    event: HookEvent
    tool_name_pattern: str = "*"
    handler_type: Literal["callable", "http"] = "callable"
    handler_target: str
    priority: int = 0
    enabled: bool = True


_callable_cache: dict[str, Any] = {}


def _resolve_callable(dotted_path: str) -> Any:
    if dotted_path in _callable_cache:
        return _callable_cache[dotted_path]
    if ":" in dotted_path:
        module_path, attr_name = dotted_path.rsplit(":", 1)
    else:
        module_path, attr_name = dotted_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    handler = getattr(module, attr_name)
    _callable_cache[dotted_path] = handler
    return handler


def _invoke_http_handler(url: str, payload: dict[str, Any]) -> HookDecision:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = URLRequest(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            return HookDecision.model_validate_json(body)
    except (URLError, OSError, json.JSONDecodeError, Exception) as exc:
        logger.warning("HTTP hook %s failed: %s", url, exc)
        return HookDecision(action="allow", message=f"hook call failed: {exc}")


class HookRegistry:
    def __init__(self) -> None:
        self._hooks: list[HookRegistration] = []

    def register(self, hook: HookRegistration) -> None:
        self._hooks = [h for h in self._hooks if h.hook_id != hook.hook_id]
        self._hooks.append(hook)
        self._hooks.sort(key=lambda h: h.priority)

    def unregister(self, hook_id: str) -> bool:
        before = len(self._hooks)
        self._hooks = [h for h in self._hooks if h.hook_id != hook_id]
        return len(self._hooks) < before

    def list_hooks(self) -> list[HookRegistration]:
        return list(self._hooks)

    def clear(self) -> None:
        self._hooks.clear()

    def dispatch(self, event: HookEvent, tool_name: str, payload: dict[str, Any]) -> HookDecision:
        warnings: list[str] = []
        effective_payload = payload
        modified = False

        for hook in self._hooks:
            if not hook.enabled or hook.event != event:
                continue
            if not fnmatch.fnmatch(tool_name, hook.tool_name_pattern):
                continue

            decision = self._evaluate_hook(hook, tool_name, effective_payload)

            if decision.action == "block":
                logger.info("Hook %s blocked tool %s on %s: %s", hook.hook_id, tool_name, event.value, decision.message)
                return HookDecision(action="block", message=decision.message, modified_payload=effective_payload if modified else None)

            if decision.action == "warn":
                logger.info("Hook %s warned on tool %s (%s): %s", hook.hook_id, tool_name, event.value, decision.message)
                warnings.append(decision.message)

            if event == HookEvent.PRE_TOOL_USE and decision.modified_payload is not None:
                effective_payload = decision.modified_payload
                modified = True

        if warnings:
            return HookDecision(action="warn", message="; ".join(warnings), modified_payload=effective_payload if modified else None)
        return HookDecision(action="allow", modified_payload=effective_payload if modified else None)

    def _evaluate_hook(self, hook: HookRegistration, tool_name: str, payload: dict[str, Any]) -> HookDecision:
        hook_payload = {"event": hook.event.value, "tool_name": tool_name, "payload": payload, "hook_id": hook.hook_id}
        if hook.handler_type == "http":
            return _invoke_http_handler(hook.handler_target, hook_payload)
        try:
            handler = _resolve_callable(hook.handler_target)
            result = handler(hook.event.value, tool_name, payload)
            if isinstance(result, HookDecision):
                return result
            if isinstance(result, dict):
                return HookDecision.model_validate(result)
            return HookDecision(action="allow")
        except Exception as exc:
            logger.warning("Callable hook %s (%s) raised: %s", hook.hook_id, hook.handler_target, exc)
            return HookDecision(action="allow", message=f"hook error: {exc}")


_global_registry = HookRegistry()


def get_hook_registry() -> HookRegistry:
    return _global_registry


def dispatch_hook(event: HookEvent, tool_name: str, payload: dict[str, Any]) -> HookDecision:
    return _global_registry.dispatch(event, tool_name, payload)


def load_hooks_from_config(path: str) -> None:
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        logger.warning("Hooks config file not found: %s", path)
        return
    raw = p.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Hooks config must be valid JSON: %s", path)
        return
    hooks_data = data if isinstance(data, list) else data.get("hooks", [])
    registry = get_hook_registry()
    for item in hooks_data:
        try:
            hook = HookRegistration.model_validate(item)
            registry.register(hook)
            logger.info("Loaded hook: %s (%s) -> %s", hook.hook_id, hook.event.value, hook.handler_target)
        except Exception as exc:
            logger.warning("Skipping invalid hook config entry: %s — %s", item, exc)
