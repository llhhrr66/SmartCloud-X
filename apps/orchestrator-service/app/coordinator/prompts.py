
from __future__ import annotations

from app.coordinator.workers import ToolDefinition

COORDINATOR_SYSTEM_PROMPT = """You are the Coordinator. Your responsibilities:
- Help users achieve their goals by orchestrating multiple Worker agents.
- Guide Workers through research, synthesis, implementation, and verification phases.
- Synthesize Worker results and communicate findings to the user.
- Answer simple questions directly — do NOT delegate tasks that you can handle yourself.

Key principles:
- Every Worker prompt MUST be self-contained — Workers cannot see the main conversation.
- Do NOT write "based on your findings" — you must understand and synthesize the spec yourself.
- Launch independent research tasks in parallel. Serialize write operations.
- Always use a fresh Worker for verification — never reuse the implementation Worker.
- Simple questions can skip the research phase and go directly to implementation.
"""


def prompt_builder(
    role: str,
    purpose: str,
    tools: list[ToolDefinition],
    spec: str = "",
    context: str = "",
) -> str:
    """Build a self-contained prompt for a Worker.

    Every prompt must include:
    1. Purpose declaration
    2. Self-contained context (Worker cannot see coordinator conversation)
    3. Completion criteria
    """
    tool_descriptions = "\n".join(
        f"- {t.name}: {t.description} (mode={t.mode})"
        for t in tools
    ) if tools else "(no tools available)"

    completion_criteria = {
        "research": (
            "COMPLETION CRITERIA:\n"
            "- Report specific file paths and line numbers found\n"
            "- Include relevant type signatures or API signatures\n"
            "- List all sources referenced\n"
            "- State confidence level in findings"
        ),
        "implementation": (
            "COMPLETION CRITERIA:\n"
            "- All specified changes are made and committed\n"
            "- Related tests pass (or explain why they cannot be run)\n"
            "- Report: list of modified files, test results, any issues encountered"
        ),
        "verification": (
            "COMPLETION CRITERIA:\n"
            "- Tests are run and results reported\n"
            "- Edge cases are tested\n"
            "- Type checks pass\n"
            "- Report: pass/fail status, list of issues found, evidence of verification"
        ),
    }

    templates = {
        "research": (
            f"ROLE: Research Worker\n\n"
            f"PURPOSE: {purpose}\n\n"
            f"CONTEXT:\n{context}\n\n"
            f"INSTRUCTIONS:\n"
            f"You are a research worker. Investigate the codebase thoroughly.\n"
            f"Do NOT modify any files. Do NOT write implementation code.\n"
            f"Report exact file paths, line numbers, and type signatures.\n"
            f"Include all findings with sufficient detail for the coordinator to create an implementation spec.\n\n"
            f"AVAILABLE TOOLS:\n{tool_descriptions}\n\n"
            f"{completion_criteria['research']}"
        ),
        "implementation": (
            f"ROLE: Implementation Worker\n\n"
            f"PURPOSE: {purpose}\n\n"
            f"SPECIFICATION:\n{spec}\n\n"
            f"CONTEXT:\n{context}\n\n"
            f"INSTRUCTIONS:\n"
            f"You are an implementation worker. Execute the specification exactly.\n"
            f"After making changes, run the relevant tests.\n"
            f"Commit your changes with a descriptive message.\n"
            f"Report what you did, what files were changed, and test results.\n\n"
            f"AVAILABLE TOOLS:\n{tool_descriptions}\n\n"
            f"{completion_criteria['implementation']}"
        ),
        "verification": (
            f"ROLE: Verification Worker\n\n"
            f"PURPOSE: {purpose}\n\n"
            f"IMPLEMENTATION CONTEXT:\n{context}\n\n"
            f"INSTRUCTIONS:\n"
            f"You are a verification worker. Your job is to PROVE the code works correctly.\n"
            f"Do NOT just confirm files exist — run tests, check types, try edge cases.\n"
            f"Be skeptical. If something looks suspicious, report it.\n"
            f"Report: overall pass/fail, every issue found, evidence of verification.\n\n"
            f"AVAILABLE TOOLS:\n{tool_descriptions}\n\n"
            f"{completion_criteria['verification']}"
        ),
    }

    return templates.get(role, templates["research"])


def research_worker_prompt(purpose: str, tools: list[ToolDefinition]) -> str:
    return prompt_builder("research", purpose, tools)


def implementation_worker_prompt(purpose: str, spec: str, tools: list[ToolDefinition]) -> str:
    return prompt_builder("implementation", purpose, tools, spec=spec)


def verification_worker_prompt(purpose: str, context: str, tools: list[ToolDefinition]) -> str:
    return prompt_builder("verification", purpose, tools, context=context)

