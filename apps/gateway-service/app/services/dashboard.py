from __future__ import annotations

from math import ceil


def build_admin_dashboard_summary(
    *,
    conversation_total: int,
    upstream_statuses: dict[str, dict],
    total_cost: float = 0.0,
) -> dict:
    degraded = [name for name, payload in upstream_statuses.items() if payload.get("status") != "ok"]
    latencies = sorted(int(payload.get("latency_ms") or 0) for payload in upstream_statuses.values())
    if not latencies:
        p95_latency_ms = 0
    else:
        index = max(0, ceil(len(latencies) * 0.95) - 1)
        p95_latency_ms = latencies[index]
    return {
        "conversation_count": conversation_total,
        "error_count": len(degraded),
        "active_alert_count": len(degraded),
        "p95_latency_ms": p95_latency_ms,
        "total_cost": round(total_cost, 2),
    }
