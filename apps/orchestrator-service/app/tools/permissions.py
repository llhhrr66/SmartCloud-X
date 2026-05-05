from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel


class PermissionMode(str, Enum):
    AUTO = "auto"
    ASK = "ask"
    DENY = "deny"


class PermissionResult(BaseModel):
    mode: PermissionMode
    reason: str = ""
    requires_elevation: bool = False


def check_permission(
    tool_name: str,
    tool_is_readonly: bool,
    role: str,
    user_context: dict[str, Any] | None = None,
) -> PermissionResult:
    """Simplified YOLO classifier — readonly tools auto-approved, writes check role."""

    if tool_is_readonly:
        return PermissionResult(mode=PermissionMode.AUTO, reason="readonly tool auto-approved")

    if role == "admin":
        return PermissionResult(mode=PermissionMode.AUTO, reason="admin role auto-approved")

    if role in ("research", "marketing"):
        return PermissionResult(
            mode=PermissionMode.ASK,
            reason=f"write tool '{tool_name}' requires confirmation for role={role}",
        )

    return PermissionResult(
        mode=PermissionMode.DENY,
        reason=f"unknown role={role} denied for write tool '{tool_name}'",
    )
