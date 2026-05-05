from __future__ import annotations

import json
import logging
from typing import Any

from app.core.config import get_settings
from app.models.orchestration import AgentName, IntentSignal, RouteRequest

logger = logging.getLogger(__name__)

# LLM routing prompt template — instructs the model to classify user query
# into one of the 5 agent domains with confidence scores and reasoning.

ROUTING_SYSTEM_PROMPT = """You are an intelligent routing classifier for a cloud platform customer service system. Your task is to analyze user queries and determine which specialized agent(s) should handle them.

Available agents and their domains:

1. product_tech_agent — Cloud product technical consulting: GPU instances, cloud servers, CDN, domain names, SSL certificates, security groups, instance specifications, product selection, technical architecture.
   Keywords: GPU, instance, server, CDN, domain, SSL, security group, specification, bandwidth, storage, configuration, deploy

2. finance_order_agent — Billing, orders, and invoices: billing queries, cost analysis, invoice management, refunds, payment issues, account balance.
   Keywords: bill, invoice, cost, payment, refund, balance, price, charge, order, transaction

3. ops_marketing_agent — Marketing campaigns and operations: promotions, discount activities, campaign rules, coupons, referral programs, new user offers.
   Keywords: campaign, discount, coupon, promotion, activity, offer, benefit, trial, free tier

4. icp_compliance_agent — ICP filing and compliance: ICP registration process, required materials, filing status check, domain registration compliance, real-name verification.
   Keywords: ICP, filing, registration, compliance, real-name, verification, document, government

5. deep_research_agent — In-depth research and analysis: competitive analysis, industry reports, technology trends, benchmark comparisons, architecture reviews.
   Keywords: research, report, analysis, comparison, benchmark, trend, review, study, whitepaper

For each user query, output a JSON object with:
- "primary_agent": the best matching agent name (use the exact names above)
- "confidence": float 0.0-1.0, your confidence in the primary routing
- "supporting_agents": list of other agents that might help (empty if none needed)
- "reasoning": brief explanation in Chinese (max 50 chars)
- "requires_retrieval": boolean, true if the query needs knowledge base lookup (documentation, FAQs, how-to guides)
- "needs_human_handoff": boolean, true if the query suggests needing human support (complaints, complex issues, escalation requests)
- "urgency": "low", "normal", or "high"

Output ONLY the JSON object, no other text."""


def _build_routing_messages(user_query: str, history: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [
        {"role": "system", "content": ROUTING_SYSTEM_PROMPT},
    ]
    if history:
        # Include last 3 turns for context
        for msg in history[-6:]:
            messages.append(msg)
    messages.append({"role": "user", "content": user_query})
    return messages


def _parse_routing_response(raw: str) -> dict[str, Any] | None:
    """Parse JSON from LLM response, handling markdown code blocks."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        # Remove opening and closing fences
        cleaned = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to extract JSON object with regex
        import re
        m = re.search(r"\{[\s\S]*\}", cleaned)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return None


VALID_AGENTS: set[str] = {
    "product_tech_agent",
    "finance_order_agent",
    "ops_marketing_agent",
    "icp_compliance_agent",
    "deep_research_agent",
}


def _validate_agent_name(name: str) -> AgentName | None:
    if name in VALID_AGENTS:
        return name  # type: ignore[return-value]
    return None


class LLMRouter:
    """LLM-driven intent classification router.

    Uses the configured LLM to classify user queries into agent domains,
    replacing or augmenting the keyword-based router with semantic understanding.
    """

    def __init__(self) -> None:
        self._settings = get_settings()

    def _build_llm_client(self):
        """Build an OpenAI-compatible client from orchestrator settings."""
        from openai import OpenAI

        return OpenAI(
            api_key=self._settings.llm_api_key,
            base_url=self._settings.llm_base_url,
            timeout=self._settings.llm_timeout_seconds,
        )

    def route(self, request: RouteRequest) -> dict[str, Any] | None:
        """Classify the user query using LLM.

        Returns parsed routing dict or None on failure (caller falls back to keyword router).
        """
        if not self._settings.llm_ready():
            logger.debug("LLM not configured, skipping LLM routing")
            return None

        try:
            client = self._build_llm_client()
            messages = _build_routing_messages(
                request.user_query,
                history=request.conversation_context if hasattr(request, "conversation_context") else None,
            )
            response = client.chat.completions.create(
                model=self._settings.llm_model or "gpt-4o-mini",
                messages=messages,  # type: ignore[arg-type]
                temperature=0.1,
                max_tokens=500,
            )
            raw = response.choices[0].message.content or ""
            logger.debug("LLM routing raw response: %s", raw[:300])
        except Exception as exc:
            logger.warning("LLM routing call failed: %s", exc)
            return None

        parsed = _parse_routing_response(raw)
        if parsed is None:
            logger.warning("Failed to parse LLM routing response: %s", raw[:200])
            return None

        # Validate primary agent
        primary = parsed.get("primary_agent", "")
        if not _validate_agent_name(primary):
            logger.warning("LLM returned invalid primary_agent: %s", primary)
            return None

        # Validate supporting agents
        supporting = [
            name for name in parsed.get("supporting_agents", [])
            if _validate_agent_name(name) and name != primary
        ]

        return {
            "primary_agent": primary,
            "confidence": float(parsed.get("confidence", 0.5)),
            "supporting_agents": supporting,
            "reasoning": str(parsed.get("reasoning", ""))[:100],
            "requires_retrieval": bool(parsed.get("requires_retrieval", False)),
            "needs_human_handoff": bool(parsed.get("needs_human_handoff", False)),
            "urgency": parsed.get("urgency", "normal"),
            "llm_routed": True,
        }

    def to_signals(self, routing_result: dict[str, Any]) -> list[IntentSignal]:
        """Convert LLM routing result to IntentSignal list for downstream compatibility."""
        signals: list[IntentSignal] = []

        primary = routing_result["primary_agent"]
        confidence = routing_result["confidence"]
        signals.append(IntentSignal(
            label=primary,  # type: ignore[arg-type]
            score=confidence,
            source="llm-router",
        ))

        for agent in routing_result.get("supporting_agents", []):
            signals.append(IntentSignal(
                label=agent,  # type: ignore[arg-type]
                score=max(0.1, confidence * 0.6),
                source="llm-router",
            ))

        return signals