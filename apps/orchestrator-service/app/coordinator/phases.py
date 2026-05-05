
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Phase(str, Enum):
    RESEARCH = "research"
    SYNTHESIS = "synthesis"
    IMPLEMENTATION = "implementation"
    VERIFICATION = "verification"


class PhaseResult(BaseModel):
    phase: Phase
    status: str = "pending"


class ResearchResult(PhaseResult):
    phase: Phase = Phase.RESEARCH
    worker_id: str
    findings: str
    file_paths: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    citations: list[str] = Field(default_factory=list)


class ImplementationSpec(PhaseResult):
    phase: Phase = Phase.SYNTHESIS
    details: str
    target_files: list[str] = Field(default_factory=list)
    approach: str = "sequential"
    worker_strategy: str = "spawn"


class ImplementationResult(PhaseResult):
    phase: Phase = Phase.IMPLEMENTATION
    worker_id: str
    changes: list[dict[str, Any]] = Field(default_factory=list)
    files_modified: list[str] = Field(default_factory=list)
    tests_passed: int = 0
    tests_failed: int = 0


class VerificationIssue(BaseModel):
    severity: str = "warning"
    file_path: str | None = None
    line: int | None = None
    description: str


class VerificationResult(PhaseResult):
    phase: Phase = Phase.VERIFICATION
    passed: bool = False
    issues: list[VerificationIssue] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    worker_id: str = ""


class CoordinatorResult(BaseModel):
    task_id: str
    status: str = "pending"
    phases: dict[str, PhaseResult] = Field(default_factory=dict)
    final_result: str | None = None
    workers: list[str] = Field(default_factory=list)
    total_duration_ms: int = 0

