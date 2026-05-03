type RuntimeConfig = {
  VITE_APP_TITLE?: string;
  VITE_APP_VERSION?: string;
  VITE_API_BASE_URL?: string;
  VITE_USE_MOCK_API?: string | boolean;
  VITE_REQUEST_TIMEOUT_MS?: string | number;
  VITE_SSE_HEARTBEAT_SECONDS?: string | number;
};

declare global {
  interface Window {
    __SMARTCLOUD_RUNTIME_CONFIG__?: RuntimeConfig;
  }
}

function read<T extends string | number | boolean>(
  runtimeKey: keyof RuntimeConfig,
  envKey: string,
  fallback: T,
  cast: (raw: unknown) => T
): T {
  const runtime = typeof window !== "undefined" ? window.__SMARTCLOUD_RUNTIME_CONFIG__ : undefined;
  const rt = runtime?.[runtimeKey];
  if (rt !== undefined && rt !== "") return cast(rt);
  const ev = (import.meta as ImportMeta & { env?: Record<string, unknown> }).env?.[envKey];
  if (ev !== undefined && ev !== "") return cast(ev);
  return fallback;
}

const asBool = (v: unknown) => v === true || v === "true" || v === "1";
const asNum = (v: unknown) => {
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : 0;
};
const asStr = (v: unknown) => (typeof v === "string" ? v : String(v ?? ""));

export const runtimeConfig = {
  appTitle: read("VITE_APP_TITLE", "VITE_APP_TITLE", "SmartCloud-X 企业智能云服务平台", asStr),
  appVersion: read("VITE_APP_VERSION", "VITE_APP_VERSION", "0.2.0", asStr),
  apiBaseUrl: read("VITE_API_BASE_URL", "VITE_API_BASE_URL", "/", asStr),
  useMockApi: read("VITE_USE_MOCK_API", "VITE_USE_MOCK_API", false, asBool),
  requestTimeoutMs: read("VITE_REQUEST_TIMEOUT_MS", "VITE_REQUEST_TIMEOUT_MS", 30_000, asNum),
  sseHeartbeatSeconds: read("VITE_SSE_HEARTBEAT_SECONDS", "VITE_SSE_HEARTBEAT_SECONDS", 15, asNum),
  clientPlatform: "web-user",
  hasRuntimeOverride:
    typeof window !== "undefined" && Object.keys(window.__SMARTCLOUD_RUNTIME_CONFIG__ ?? {}).length > 0,
};

export type { RuntimeConfig };
