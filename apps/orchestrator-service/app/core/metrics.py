from prometheus_client import Counter, Histogram

SAGA_STEPS_TOTAL = Counter(
    "orchestrator_saga_steps_total",
    "Total saga step executions",
    ["saga_name", "step", "status"],
)

SAGA_COMPENSATIONS_TOTAL = Counter(
    "orchestrator_saga_compensations_total",
    "Total saga compensation actions",
    ["saga_name", "step", "result"],
)

SAGA_FAILURES_TOTAL = Counter(
    "orchestrator_saga_failures_total",
    "Total saga step failures",
    ["saga_name", "step", "error_type"],
)

SAGA_STEP_DURATION = Histogram(
    "orchestrator_saga_step_duration_seconds",
    "Duration of saga step executions",
    ["saga_name", "step"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
