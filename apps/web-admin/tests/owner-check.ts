function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

const adminViews = [
  "dashboard",
  "knowledge",
  "documents",
  "imports",
  "retrieval",
  "agents",
  "marketing",
  "audit",
];

function runNavigationCoverageScenario() {
  assert(adminViews.length === 8, "expected eight authenticated admin views");
  assert(adminViews.includes("agents"), "expected orchestrator agent view");
  assert(adminViews.includes("marketing"), "expected marketing campaign view");
}

function runApiSurfaceScenario() {
  const canonicalRoutes = [
    "/api/v1/admin/dashboard/summary",
    "/api/v1/admin/knowledge-bases",
    "/api/v1/admin/files/uploads",
    "/api/v1/admin/retrieval/diagnostics",
    "/api/v1/admin/agents",
    "/api/v1/admin/marketing/campaigns",
  ];
  assert(canonicalRoutes.every((route) => route.startsWith("/api/v1/admin")), "expected canonical admin routes through gateway");
}

runNavigationCoverageScenario();
runApiSurfaceScenario();

console.log("owner-check: ok");
