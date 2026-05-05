from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from app.coordinator.phases import (
    CoordinatorResult,
    ImplementationResult,
    ImplementationSpec,
    Phase,
    PhaseResult,
    ResearchResult,
    VerificationIssue,
    VerificationResult,
)
from app.coordinator.prompts import (
    implementation_worker_prompt,
    prompt_builder,
    research_worker_prompt,
    verification_worker_prompt,
)
from app.coordinator.workers import ToolDefinition, WorkerAgent, WorkerResult

logger = logging.getLogger(__name__)


ROLE_TOOL_MAP: dict[str, list[ToolDefinition]] = {
    "research": [
        ToolDefinition(name="file_search", description="Search for files by glob pattern", capability="filesystem", mode="query"),
        ToolDefinition(name="code_search", description="Search code with regex/ripgrep", capability="code", mode="query"),
        ToolDefinition(name="read_file", description="Read file contents", capability="filesystem", mode="query"),
        ToolDefinition(name="list_directory", description="List directory contents", capability="filesystem", mode="query"),
        ToolDefinition(name="web_search", description="Search the web for information", capability="web", mode="query"),
        ToolDefinition(name="knowledge_query", description="Query internal knowledge base", capability="knowledge", mode="query"),
    ],
    "implementation": [
        ToolDefinition(name="read_file", description="Read file contents", capability="filesystem", mode="query"),
        ToolDefinition(name="write_file", description="Write or overwrite a file", capability="filesystem", mode="write"),
        ToolDefinition(name="edit_file", description="Make targeted edits to a file", capability="filesystem", mode="write"),
        ToolDefinition(name="run_tests", description="Run test suite", capability="code", mode="write"),
        ToolDefinition(name="run_command", description="Execute shell command", capability="system", mode="write"),
        ToolDefinition(name="commit_changes", description="Commit changes to git", capability="vcs", mode="write"),
    ],
    "verification": [
        ToolDefinition(name="read_file", description="Read file contents", capability="filesystem", mode="query"),
        ToolDefinition(name="code_search", description="Search code with regex/ripgrep", capability="code", mode="query"),
        ToolDefinition(name="list_directory", description="List directory contents", capability="filesystem", mode="query"),
        ToolDefinition(name="run_tests", description="Run test suite", capability="code", mode="query"),
        ToolDefinition(name="type_check", description="Run type checker", capability="code", mode="query"),
        ToolDefinition(name="lint_check", description="Run linter", capability="code", mode="query"),
    ],
}


def get_tools_for_role(role: str) -> list[ToolDefinition]:
    """Get the tool set for a given Worker role."""
    return ROLE_TOOL_MAP.get(role, ROLE_TOOL_MAP["research"])


class CoordinatorOrchestrator:
    """Four-phase orchestrator: Research -> Synthesis -> Implementation -> Verification.

    The Coordinator itself does NOT call LLMs directly. It is a pure logic orchestration layer.
    LLM calls happen inside Workers (which call downstream services internally).
    The Synthesis phase may optionally call an LLM to synthesize specs, but defaults to rule-based.
    Simple questions can skip Research and go directly to Implementation.
    """

    def __init__(self):
        self._workers: dict[str, WorkerAgent] = {}
        self._results: dict[str, list[PhaseResult]] = {}
        self._phase_order: list[Phase] = []

    async def execute_task(
        self,
        user_request: str,
        context: dict[str, Any] | None = None,
    ) -> CoordinatorResult:
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        started_at = time.perf_counter()
        context = context or {}

        self._results[task_id] = []
        self._phase_order = self._determine_phases(user_request)

        logger.info(
            "Coordinator task %s started, phases=%s",
            task_id,
            [p.value for p in self._phase_order],
        )

        try:
            # Phase 1: Research (may be skipped for simple tasks)
            research_results: list[ResearchResult] = []
            if Phase.RESEARCH in self._phase_order:
                research_results = await self.research_phase(user_request)
                for r in research_results:
                    self._results[task_id].append(r)

            # Phase 2: Synthesis — Coordinator synthesises directly
            spec = await self.synthesis_phase(research_results, user_request)
            self._results[task_id].append(spec)

            # Phase 3: Implementation
            impl_result = await self.implementation_phase(spec)
            self._results[task_id].append(impl_result)

            # Phase 4: Verification — always fresh Worker
            verify_result = await self.verification_phase(impl_result)
            self._results[task_id].append(verify_result)

            passed = verify_result.passed
            final = self._build_final_result(
                task_id, passed, research_results, impl_result, verify_result
            )

        except Exception as exc:
            logger.exception("Coordinator task %s failed", task_id)
            final = f"Task failed: {exc}"

        total_duration_ms = int((time.perf_counter() - started_at) * 1000)
        phases_dict = {r.phase.value: r for r in self._results.get(task_id, [])}

        return CoordinatorResult(
            task_id=task_id,
            status="completed",
            phases=phases_dict,
            final_result=final,
            workers=[w.worker_id for w in self._workers.values()],
            total_duration_ms=total_duration_ms,
        )

    # ------------------------------------------------------------------
    # Phase 1: Research
    # ------------------------------------------------------------------

    async def research_phase(self, user_request: str) -> list[ResearchResult]:
        """Parse user intent, split into independent research subtasks,
        launch multiple Worker Agents in parallel (different research angles),
        wait for all Workers, collect results.
        """
        subtasks = self._decompose_research(user_request)
        if not subtasks:
            return []

        worker_futures = []
        for subtask in subtasks:
            worker = WorkerAgent(
                role="research",
                tools=get_tools_for_role("research"),
                worker_id=f"research_{uuid.uuid4().hex[:8]}",
            )
            self._workers[worker.worker_id] = worker
            prompt = research_worker_prompt(subtask["purpose"], worker.tools)
            worker_futures.append(
                worker.run(prompt, context={"purpose": subtask["purpose"]})
            )

        worker_results: list[WorkerResult] = await asyncio.gather(*worker_futures)

        research_outputs: list[ResearchResult] = []
        for wr in worker_results:
            research_outputs.append(self._parse_research_output(wr))
        return research_outputs

    # ------------------------------------------------------------------
    # Phase 2: Synthesis
    # ------------------------------------------------------------------

    async def synthesis_phase(
        self,
        research_results: list[ResearchResult],
        user_request: str,
    ) -> ImplementationSpec:
        """Coordinator synthesises results itself (no Worker delegation).
        Generates an implementation spec with concrete file paths, line numbers, changes needed.
        Decides: continue existing Workers (SendMessage) vs spawn new Workers (Agent).
        """
        all_files = list(dict.fromkeys(
            f for r in research_results for f in r.file_paths
        ))

        if not research_results:
            return ImplementationSpec(
                details=f"Direct implementation for: {user_request}",
                target_files=[],
                approach="direct",
                worker_strategy="spawn",
            )

        combined_findings = "\n".join(
            f"[{r.worker_id}] {r.findings}" for r in research_results
        )

        return ImplementationSpec(
            details=(
                f"Synthesized from {len(research_results)} research workers:\n"
                f"{combined_findings}"
            ),
            target_files=all_files,
            approach="sequential",
            worker_strategy=self._decide_worker_strategy(research_results),
        )

    # ------------------------------------------------------------------
    # Phase 3: Implementation
    # ------------------------------------------------------------------

    async def implementation_phase(self, spec: ImplementationSpec) -> ImplementationResult:
        """Dispatch implementation tasks based on worker_strategy.
        "continue" -> SendMessage to existing Worker.
        "spawn" -> create new Worker.
        """
        worker = WorkerAgent(
            role="implementation",
            tools=get_tools_for_role("implementation"),
            worker_id=f"impl_{uuid.uuid4().hex[:8]}",
        )
        self._workers[worker.worker_id] = worker
        prompt = implementation_worker_prompt(
            spec.details, spec.details, worker.tools,
        )

        result = await worker.run(
            prompt,
            context={"purpose": spec.details, "spec": spec.details},
        )

        return ImplementationResult(
            worker_id=worker.worker_id,
            changes=[{"files": spec.target_files, "approach": spec.approach}],
            files_modified=spec.target_files,
            tests_passed=0,
            tests_failed=0,
        )

    # ------------------------------------------------------------------
    # Phase 4: Verification
    # ------------------------------------------------------------------

    async def verification_phase(self, impl_result: ImplementationResult) -> VerificationResult:
        """Always spawn a NEW Worker for verification (fresh perspective, no implementation bias).
        Worker role: "verification", tools: read-only + test tools.
        Verification requirement: PROVE the code works, not just confirm it exists.
        """
        worker = WorkerAgent(
            role="verification",
            tools=get_tools_for_role("verification"),
            worker_id=f"verify_{uuid.uuid4().hex[:8]}",
        )
        self._workers[worker.worker_id] = worker

        context_str = (
            f"Implementation by {impl_result.worker_id} "
            f"modified: {', '.join(impl_result.files_modified)}"
        )
        prompt = verification_worker_prompt(
            "Verify the implementation correctness",
            context_str,
            worker.tools,
        )

        result = await worker.run(
            prompt,
            context={"purpose": "Verify implementation", "spec": context_str},
        )

        return VerificationResult(
            passed=result.status == "success",
            issues=[],
            evidence=[f"Verification worker {worker.worker_id}: {result.status}"],
            worker_id=worker.worker_id,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _determine_phases(self, user_request: str) -> list[Phase]:
        """Decide which phases are needed.
        Simple questions skip Research. Complex tasks use the full pipeline.
        Phases are not rigid — adapt to the request.
        """
        request_lower = user_request.lower().strip()

        simple_patterns = [
            "what is", "how do i", "show me", "explain",
            "who is", "when did", "where is",
        ]
        if any(request_lower.startswith(p) for p in simple_patterns):
            if len(user_request.split()) < 15:
                return [Phase.IMPLEMENTATION, Phase.VERIFICATION]

        complex_keywords = [
            "research", "investigate", "analyze", "compare",
            "generate report", "audit", "review all",
        ]
        if any(kw in request_lower for kw in complex_keywords):
            return [
                Phase.RESEARCH, Phase.SYNTHESIS,
                Phase.IMPLEMENTATION, Phase.VERIFICATION,
            ]

        return [Phase.SYNTHESIS, Phase.IMPLEMENTATION, Phase.VERIFICATION]

    def _decompose_research(self, user_request: str) -> list[dict[str, str]]:
        """Break a research request into independent subtasks."""
        request_lower = user_request.lower()
        subtasks: list[dict[str, str]] = []

        if "competitor" in request_lower or "compare" in request_lower:
            subtasks.append({
                "purpose": f"Research existing competitors and features for: {user_request}",
            })
            subtasks.append({
                "purpose": f"Research market trends and pricing for: {user_request}",
            })
            subtasks.append({
                "purpose": f"Research technical implementation approaches for: {user_request}",
            })
        elif "code" in request_lower or "implement" in request_lower:
            subtasks.append({
                "purpose": f"Search codebase for relevant existing files for: {user_request}",
            })
            subtasks.append({
                "purpose": f"Identify dependencies and imports needed for: {user_request}",
            })
        else:
            subtasks.append({
                "purpose": f"Research the codebase for: {user_request}",
            })

        return subtasks

    def _decide_worker_strategy(self, research_results: list[ResearchResult]) -> str:
        """Decide: continue existing Worker vs spawn new."""
        return "spawn"

    def _parse_research_output(self, worker_result: WorkerResult) -> ResearchResult:
        content = worker_result.content or ""
        file_paths: list[str] = []
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped and ("/" in stripped or "\\" in stripped):
                parts = stripped.split()
                for part in parts:
                    if "." in part and ("/" in part or "\\" in part):
                        file_paths.append(part.strip("',\";()[]{}"))

        return ResearchResult(
            worker_id=worker_result.worker_id,
            findings=content,
            file_paths=list(dict.fromkeys(file_paths)),
            confidence=0.5 if worker_result.status == "success" else 0.2,
            citations=[],
        )

    def _build_final_result(
        self,
        task_id: str,
        passed: bool,
        research_results: list[ResearchResult],
        impl_result: ImplementationResult,
        verify_result: VerificationResult,
    ) -> str:
        lines = [
            f"Task {task_id} completed.",
            f"Verification: {'PASSED' if passed else 'FAILED'}",
            f"Research workers: {len(research_results)}",
            f"Files modified: {len(impl_result.files_modified)}",
            f"Issues: {len(verify_result.issues)}",
        ]
        return "\n".join(lines)