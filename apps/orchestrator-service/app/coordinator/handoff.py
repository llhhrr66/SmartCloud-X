
from __future__ import annotations

import re
from dataclasses import dataclass

from app.coordinator.workers import WorkerResult

DANGEROUS_PATTERNS: list[tuple[str, str]] = [
    (r"rm\s+-rf\s+/", "Recursive deletion of root directory"),
    (r"rm\s+-rf\s+~", "Recursive deletion of home directory"),
    (r"rm\s+-rf\s+\$HOME", "Recursive deletion of home directory"),
    (r">\s*/dev/sda", "Overwriting raw disk device"),
    (r"dd\s+if=.*of=/dev/", "Writing directly to block device"),
    (r"chmod\s+777\s+/", "Unsafe recursive chmod on root"),
    (r"DROP\s+(TABLE|DATABASE)", "SQL DROP without confirmation"),
    (r"TRUNCATE\s+(TABLE\s+)?", "SQL TRUNCATE without confirmation"),
    (r"DELETE\s+FROM\s+.+\s+WHERE\s+1\s*=\s*1", "SQL DELETE all rows"),
    (r"os\.remove\(.*\)", "Python file deletion"),
    (r"shutil\.rmtree\(.*\)", "Python recursive directory deletion"),
    (r"subprocess\.(call|run|Popen)\(.*rm\s+-rf", "Shell rm -rf via subprocess"),
    (r"eval\(|exec\(", "Dynamic code execution"),
    (r"__import__\(.*os.*\)", "Dynamic import of os module"),
]


@dataclass
class HandoffDecision:
    verdict: str  # "allowed" | "allowed_with_warning" | "blocked"
    reason: str = ""
    warnings: list[str] | None = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


def classify_handoff(worker_result: WorkerResult) -> HandoffDecision:
    """Classify Worker output for safety before handoff.

    For readonly Workers (research, verification): auto-allow without inspection.
    For write Workers (implementation): check for dangerous patterns.
    """
    if worker_result.status == "failed":
        return HandoffDecision(
            verdict="allowed",
            reason="Worker failed — no output to hand off",
        )

    if worker_result.role in ("research", "verification"):
        return HandoffDecision(
            verdict="allowed",
            reason=f"Readonly worker ({worker_result.role}) auto-allowed",
        )

    if not worker_result.content or not worker_result.content.strip():
        return HandoffDecision(
            verdict="allowed",
            reason="Worker produced empty content",
        )

    return _scan_content(worker_result.content)


def _scan_content(content: str) -> HandoffDecision:
    warnings: list[str] = []
    blocked = False

    for pattern, description in DANGEROUS_PATTERNS:
        matches = re.findall(pattern, content, re.IGNORECASE | re.MULTILINE)
        if matches:
            severity = pattern.split("|")[0] if "|" in pattern else pattern
            if any(kw in severity.lower() for kw in ("rm -rf /", ">/dev/sda", "dd if=")):
                blocked = True
                warnings.append(f"BLOCKED: {description} — found pattern: {pattern}")
            else:
                warnings.append(f"WARNING: {description} — found pattern: {pattern}")

    if blocked:
        return HandoffDecision(
            verdict="blocked",
            reason="Dangerous destructive operations detected",
            warnings=warnings,
        )
    if warnings:
        return HandoffDecision(
            verdict="allowed_with_warning",
            reason=f"{len(warnings)} warning(s) found",
            warnings=warnings,
        )
    return HandoffDecision(
        verdict="allowed",
        reason="No dangerous patterns detected",
    )

