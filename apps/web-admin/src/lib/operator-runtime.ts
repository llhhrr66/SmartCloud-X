export type OperatorTone = "ok" | "info" | "warning" | "danger";

export type OperatorMetric = {
  label: string;
  value: string;
  tone: OperatorTone;
  detail: string;
};

export type OperatorNotice = {
  id: string;
  title: string;
  summary: string;
  detail: string;
  tone: OperatorTone;
  tags: string[];
};

export type OperatorRuntimeSummary = {
  headline: string;
  metrics: OperatorMetric[];
  notices: OperatorNotice[];
};

export type OperatorSurface =
  | "canonical-admin"
  | "owner-local-knowledge"
  | "owner-local-rag"
  | "health"
  | "runtime-snapshot"
  | "local-ui";

export type ApiErrorLike = {
  kind?: string;
  message: string;
  status?: number;
  code?: number | string;
  requestId?: string;
  retryAfterMs?: number;
  details?: {
    missingFields?: string[];
    requiredPermissions?: string[];
    missingAuthContext?: string[];
    confirmationRequired?: boolean;
    confirmToolNames?: string[];
    requiresAccountContext?: boolean;
  };
};

export type HealthLike = {
  service?: string;
  status?: string;
  ready?: boolean;
  warnings?: string[];
};

export type ConnectorLike = {
  backend: string;
  configured: boolean;
  endpoint?: string | null;
  target?: string | null;
  notes?: string[];
};

export type SnapshotLike = {
  integrations?: {
    rawStorage: ConnectorLike;
    metadataStore: ConnectorLike;
    vectorStore: ConnectorLike;
    bm25Store: ConnectorLike;
    cache: ConnectorLike;
    taskQueue: ConnectorLike;
    outboxPath: string;
    rawMirrorRoot: string;
    pendingEvents: number;
    eventCounters?: Record<string, number>;
    recentEvents: Array<{
      eventId: string;
      eventType: string;
      operation: string;
      status: string;
      queueName: string;
      docId: string;
      chunkCount: number;
      createdAt: string;
      lastError?: string | null;
      connectorResults?: Array<{
        connector: string;
        status: string;
        detail?: string | null;
      }>;
    }>;
  } | null;
};

type BuildRuntimeSummaryInput = {
  knowledgeHealth: HealthLike | null;
  ragHealth: HealthLike | null;
  snapshot: SnapshotLike | null;
};

type BuildRequestAlertInput = {
  action: string;
  route: string;
  surface: OperatorSurface;
  info: ApiErrorLike;
};

function hasBackendName(connector: ConnectorLike | undefined, pattern: RegExp): boolean {
  return Boolean(connector?.backend && pattern.test(connector.backend));
}

function isFallbackConnector(connector: ConnectorLike | undefined): boolean {
  if (!connector) {
    return true;
  }

  return (
    !connector.configured ||
    hasBackendName(connector, /json|local|file|filesystem|runtime/i)
  );
}

function formatConnectorState(
  connector: ConnectorLike | undefined,
  liveBackendPattern: RegExp,
): {
  value: string;
  tone: OperatorTone;
  detail: string;
} {
  if (!connector) {
    return {
      value: "unknown",
      tone: "warning",
      detail: "The runtime snapshot has not exposed this connector yet.",
    };
  }

  if (!connector.configured) {
    return {
      value: "local fallback",
      tone: "warning",
      detail: `${connector.backend} is not configured as a live shared backend.`,
    };
  }

  if (hasBackendName(connector, liveBackendPattern)) {
    return {
      value: connector.backend,
      tone: "ok",
      detail: connector.target ?? connector.endpoint ?? "Configured through the runtime snapshot.",
    };
  }

  if (hasBackendName(connector, /json|local|file|filesystem|runtime/i)) {
    return {
      value: connector.backend,
      tone: "warning",
      detail: "This connector still looks file-backed or local-only from the current snapshot.",
    };
  }

  return {
    value: connector.backend,
    tone: "info",
    detail:
      connector.target ??
      connector.endpoint ??
      "Configured, but not recognized as a shared live backend.",
  };
}

function formatApiMetric(label: string, health: HealthLike | null): OperatorMetric {
  if (!health) {
    return {
      label,
      value: "not proven",
      tone: "warning",
      detail: "No health payload has been captured for this surface yet.",
    };
  }

  if (health.status === "ok" && health.ready !== false) {
    return {
      label,
      value: "ready",
      tone: "ok",
      detail: health.service
        ? `${health.service} reports ok/ready on the current health surface.`
        : "The current health surface reports ok/ready.",
    };
  }

  if (health.ready === false) {
    return {
      label,
      value: "not ready",
      tone: "warning",
      detail: health.service
        ? `${health.service} is reachable, but it is not ready yet.`
        : "The health surface is reachable, but not ready yet.",
    };
  }

  return {
    label,
    value: health.status ?? "unavailable",
    tone: "danger",
    detail: "The current health response does not prove a ready live API path.",
  };
}

function buildStaticRouteNotice(): OperatorNotice {
  return {
    id: "route-mix",
    title: "This console mixes contract-facing and owner-local routes",
    summary:
      "Use `/api/v1/admin/**` as the canonical admin surface, and treat `/api/knowledge/v1/**` plus `/api/rag/v1/**` as owner-local debug or live-service views.",
    detail:
      "That split is intentional for the current repo reality: some flows are already exposed through admin placeholders, while health, snapshot, imports, search preview, diagnostics, and answer playground still lean on service-local routes. A successful owner-local route does not prove that every canonical admin placeholder is fully promoted.",
    tone: "info",
    tags: ["contract-facing", "owner-local", "mixed-surface"],
  };
}

function buildHealthNotice(
  id: string,
  title: string,
  health: HealthLike | null,
): OperatorNotice | null {
  if (!health?.warnings?.length && health?.ready !== false) {
    return null;
  }

  return {
    id,
    title,
    summary:
      health?.ready === false
        ? `${title} is reachable but not ready.`
        : health?.warnings?.[0] ?? `${title} is reporting warnings.`,
    detail:
      health?.warnings?.join(" | ") ??
      "The current health payload indicates a degraded or incomplete runtime state.",
    tone: health?.ready === false ? "warning" : "info",
    tags: [health?.status ?? "unknown", "health-surface"],
  };
}

function buildConnectorNotice(
  id: string,
  title: string,
  connector: ConnectorLike | undefined,
  liveBackendPattern: RegExp,
  fallbackSummary: string,
): OperatorNotice | null {
  if (!connector) {
    return {
      id,
      title,
      summary: "No connector details are available in the current runtime snapshot.",
      detail: "Refresh the runtime snapshot to see whether this path is live, disabled, or degraded.",
      tone: "warning",
      tags: ["runtime-snapshot", "unknown"],
    };
  }

  if (!isFallbackConnector(connector) && hasBackendName(connector, liveBackendPattern)) {
    return null;
  }

  return {
    id,
    title,
    summary: fallbackSummary,
    detail: `${connector.backend} ${
      connector.configured ? "is configured" : "is not configured"
    }${
      connector.target
        ? ` for ${connector.target}`
        : connector.endpoint
          ? ` via ${connector.endpoint}`
          : ""
    }.`,
    tone: connector.configured ? "warning" : "info",
    tags: [connector.backend, connector.configured ? "configured" : "fallback"],
  };
}

function buildRecentEventNotice(snapshot: SnapshotLike | null): OperatorNotice | null {
  const recentEvents = snapshot?.integrations?.recentEvents ?? [];
  const failingEvent = recentEvents.find(
    (event) =>
      Boolean(event.lastError) ||
      Boolean(
        event.connectorResults?.some((result) => !/success|completed|ok/i.test(result.status)),
      ),
  );

  if (!failingEvent) {
    return null;
  }

  return {
    id: "recent-indexing-event",
    title: "Recent indexing activity still shows connector-level drift",
    summary: `${failingEvent.operation} for ${failingEvent.docId} is reporting ${failingEvent.status}.`,
    detail:
      failingEvent.lastError ??
      failingEvent.connectorResults
        ?.map(
          (result) =>
            `${result.connector}: ${result.status}${result.detail ? ` (${result.detail})` : ""}`,
        )
        .join(" | ") ??
      "The runtime snapshot reports recent event failures or non-success connector results.",
    tone: "warning",
    tags: [failingEvent.queueName, failingEvent.status, "async-indexing"],
  };
}

export function buildRuntimeTruthSummary({
  knowledgeHealth,
  ragHealth,
  snapshot,
}: BuildRuntimeSummaryInput): OperatorRuntimeSummary {
  const integrations = snapshot?.integrations ?? null;
  const metadataMetric = formatConnectorState(integrations?.metadataStore, /mysql/i);
  const rawMetric = formatConnectorState(integrations?.rawStorage, /minio|s3|object/i);
  const retrievalMetric = formatConnectorState(integrations?.vectorStore, /qdrant|vector/i);
  const bm25Metric = formatConnectorState(integrations?.bm25Store, /opensearch|elastic|bm25/i);

  const notices = [
    buildStaticRouteNotice(),
    buildHealthNotice("knowledge-health", "Knowledge API", knowledgeHealth),
    buildHealthNotice("rag-health", "RAG API", ragHealth),
    buildConnectorNotice(
      "metadata-runtime",
      "Metadata authority is not fully live-backed yet",
      integrations?.metadataStore,
      /mysql/i,
      "The current metadata path still looks local, file-backed, or otherwise non-authoritative from the snapshot.",
    ),
    buildConnectorNotice(
      "raw-storage-runtime",
      "Document raw storage still looks file-backed or mirrored",
      integrations?.rawStorage,
      /minio|s3|object/i,
      "The current raw document path still looks file-backed, mirrored, or local-only.",
    ),
    buildConnectorNotice(
      "vector-runtime",
      "Vector retrieval is not fully proven from the current snapshot",
      integrations?.vectorStore,
      /qdrant|vector/i,
      "The current vector connector is disabled, degraded, or not clearly live-backed.",
    ),
    buildConnectorNotice(
      "bm25-runtime",
      "BM25 retrieval is not fully proven from the current snapshot",
      integrations?.bm25Store,
      /opensearch|elastic|bm25/i,
      "The current BM25 connector is disabled, degraded, or not clearly live-backed.",
    ),
    buildConnectorNotice(
      "queue-runtime",
      "Async indexing still depends on a local or degraded queue path",
      integrations?.taskQueue,
      /redis|queue/i,
      "The current task queue is not clearly backed by a live shared queue service.",
    ),
    buildRecentEventNotice(snapshot),
  ].filter((notice): notice is OperatorNotice => Boolean(notice));

  const warningCount = notices.filter(
    (notice) => notice.tone === "warning" || notice.tone === "danger",
  ).length;

  return {
    headline:
      warningCount > 0
        ? "Current health and snapshot data show usable admin surfaces, but operators should still treat part of the runtime as file-backed, owner-local, or degraded."
        : "Current health and snapshot data point to a ready knowledge/RAG runtime without obvious degraded edges.",
    metrics: [
      formatApiMetric("Knowledge API", knowledgeHealth),
      formatApiMetric("RAG API", ragHealth),
      {
        label: "Metadata path",
        value: metadataMetric.value,
        tone: metadataMetric.tone,
        detail: metadataMetric.detail,
      },
      {
        label: "Raw storage",
        value: rawMetric.value,
        tone: rawMetric.tone,
        detail: rawMetric.detail,
      },
      {
        label: "Vector retrieval",
        value: retrievalMetric.value,
        tone: retrievalMetric.tone,
        detail: retrievalMetric.detail,
      },
      {
        label: "BM25 retrieval",
        value: bm25Metric.value,
        tone: bm25Metric.tone,
        detail: bm25Metric.detail,
      },
    ],
    notices,
  };
}

function joinNonEmpty(parts: Array<string | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

export function buildRequestAlert({
  action,
  route,
  surface,
  info,
}: BuildRequestAlertInput): OperatorNotice {
  const tone: OperatorTone =
    info.kind === "server" || info.kind === "timeout"
      ? "danger"
      : info.kind === "rate_limited" ||
          info.kind === "validation" ||
          info.kind === "forbidden" ||
          info.kind === "not_found"
        ? "warning"
        : "info";

  const tags = [
    surface,
    info.kind ?? "unknown",
    info.status ? `http-${info.status}` : undefined,
    info.code ? `code-${info.code}` : undefined,
  ].filter((tag): tag is string => Boolean(tag));

  const summary = joinNonEmpty([
    info.message,
    info.requestId ? `(request id: ${info.requestId})` : undefined,
  ]);

  let detail = `Route ${route} failed on the ${surface} surface.`;

  if (info.kind === "not_found" && surface === "canonical-admin") {
    detail +=
      " This is more likely a contract-facing placeholder gap than proof that the entire live backend is down.";
  } else if (info.kind === "forbidden") {
    detail +=
      " The request reached the service, but the current operator or RBAC context was rejected.";
  } else if (info.kind === "validation") {
    const missingFields = info.details?.missingFields ?? [];
    detail += missingFields.length
      ? ` Missing fields: ${missingFields.join(", ")}.`
      : " The backend rejected the payload or confirm-token semantics.";
  } else if (info.kind === "rate_limited") {
    detail += info.retryAfterMs
      ? ` Retry after roughly ${info.retryAfterMs} ms.`
      : " Back off before retrying the same route.";
  } else if (info.kind === "timeout" || info.kind === "server") {
    detail +=
      " Check whether this API is truly live, whether an upstream dependency is degraded, and whether the request id appears in backend logs.";
  } else if (surface === "owner-local-knowledge" || surface === "owner-local-rag") {
    detail +=
      " This owner-local route is closer to service reality than the contract-facing admin placeholders, so do not mistake a local failure for a gateway/admin contract issue.";
  }

  if (info.details?.requiredPermissions?.length) {
    detail += ` Required permissions: ${info.details.requiredPermissions.join(", ")}.`;
  }

  if (info.details?.missingAuthContext?.length) {
    detail += ` Missing auth context: ${info.details.missingAuthContext.join(", ")}.`;
  }

  if (info.details?.confirmationRequired) {
    detail += " The backend is explicitly asking for a higher-risk confirmation flow.";
  }

  return {
    id: `${surface}-${action}-${route}`,
    title: action,
    summary,
    detail,
    tone,
    tags,
  };
}
