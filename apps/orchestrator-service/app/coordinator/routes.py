from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.coordinator.coordinator import CoordinatorOrchestrator
from app.coordinator.phases import CoordinatorResult, Phase
from app.models.common import ApiEnvelope, ErrorInfo

logger = logging.getLogger(__name__)

router = APIRouter(tags=["coordinator"])

_coordinator = CoordinatorOrchestrator()
_task_store: dict[str, CoordinatorResult] = {}


class CoordinatorExecuteRequest(BaseModel):
    user_request: str = Field(min_length=1, description="The user's request to orchestrate")
    context: dict[str, Any] = Field(default_factory=dict)


class CoordinatorStatusResponse(BaseModel):
    task_id: str
    status: str
    current_phase: str | None = None
    phases_completed: list[str] = Field(default_factory=list)
    workers: list[dict[str, Any]] = Field(default_factory=list)
    progress: str = "0/4"


@router.post("/coordinator/execute")
async def execute_coordinator_task(payload: CoordinatorExecuteRequest) -> ApiEnvelope[CoordinatorResult]:
    """Execute a task through the Coordinator four-phase pipeline.

    Phases: Research -> Synthesis -> Implementation -> Verification
    Simple tasks may skip Research.
    """
    try:
        result = await _coordinator.execute_task(
            user_request=payload.user_request,
            context=payload.context,
        )
        _task_store[result.task_id] = result
        return ApiEnvelope(success=True, data=result)
    except Exception as exc:
        logger.exception("Coordinator execution failed")
        raise HTTPException(
            status_code=500,
            detail=ErrorInfo(
                code="COORDINATOR_EXECUTION_FAILED",
                message=str(exc),
            ).model_dump(),
        ) from exc


@router.get("/coordinator/tasks/{task_id}/status")
def get_coordinator_task_status(task_id: str) -> ApiEnvelope[CoordinatorStatusResponse]:
    """Get the current status of a coordinator task.

    Returns current phase, worker statuses, and overall progress.
    """
    task = _task_store.get(task_id)
    if task is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorInfo(
                code="COORDINATOR_TASK_NOT_FOUND",
                message=f"Task '{task_id}' not found.",
            ).model_dump(),
        )

    phases_completed = list(task.phases.keys())
    phase_order = [
        Phase.RESEARCH.value,
        Phase.SYNTHESIS.value,
        Phase.IMPLEMENTATION.value,
        Phase.VERIFICATION.value,
    ]
    completed_count = sum(1 for p in phase_order if p in phases_completed)
    current_phase = phase_order[completed_count] if completed_count < 4 else None

    workers_info = [
        {"worker_id": wid, "role": "unknown"}
        for wid in task.workers
    ]

    return ApiEnvelope(
        success=True,
        data=CoordinatorStatusResponse(
            task_id=task.task_id,
            status=task.status,
            current_phase=current_phase,
            phases_completed=phases_completed,
            workers=workers_info,
            progress=f"{completed_count}/4",
        ),
    )