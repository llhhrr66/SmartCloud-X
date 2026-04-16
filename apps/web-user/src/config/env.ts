import packageJson from '../../package.json';

const runtimeConfigKeys = [
  'VITE_APP_TITLE',
  'VITE_APP_VERSION',
  'VITE_API_BASE_URL',
  'VITE_REQUEST_TIMEOUT_MS',
  'VITE_SSE_HEARTBEAT_SECONDS',
  'VITE_USE_MOCK_API'
] as const;

type RuntimeConfigKey = (typeof runtimeConfigKeys)[number];
type RuntimeConfigMap = Partial<Record<RuntimeConfigKey, string>>;

export interface AppEnv {
  appTitle: string;
  appVersion: string;
  apiBaseUrl: string;
  requestTimeoutMs: number;
  sseHeartbeatSeconds: number;
  useMockApi: boolean;
  clientPlatform: 'web';
  runtimeConfigEnabled: boolean;
  runtimeOverrideKeys: RuntimeConfigKey[];
}

function readBoolean(value: string | undefined, fallback: boolean): boolean {
  if (value === undefined) {
    return fallback;
  }

  return ['1', 'true', 'yes', 'on'].includes(value.toLowerCase());
}

function readNumber(value: string | undefined, fallback: number): number {
  if (!value) {
    return fallback;
  }

  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function readRuntimeConfig(): RuntimeConfigMap {
  if (typeof window === 'undefined') {
    return {};
  }

  const runtimeConfig = (window as Window & { __SMARTCLOUD_RUNTIME_CONFIG__?: unknown }).__SMARTCLOUD_RUNTIME_CONFIG__;
  if (!runtimeConfig || typeof runtimeConfig !== 'object') {
    return {};
  }

  const config = runtimeConfig as Record<string, unknown>;
  return runtimeConfigKeys.reduce<RuntimeConfigMap>((accumulator, key) => {
    const value = config[key];
    if (typeof value === 'string') {
      accumulator[key] = value;
    }
    return accumulator;
  }, {});
}

function readConfigValue(runtimeConfig: RuntimeConfigMap, key: RuntimeConfigKey, fallback: string | undefined): string | undefined {
  return runtimeConfig[key] ?? fallback;
}

const runtimeConfig = readRuntimeConfig();
const runtimeOverrideKeys = runtimeConfigKeys.filter((key) => runtimeConfig[key] !== undefined);

export const appEnv: AppEnv = {
  appTitle: readConfigValue(runtimeConfig, 'VITE_APP_TITLE', import.meta.env.VITE_APP_TITLE) ?? 'SmartCloud-X User Console',
  appVersion: readConfigValue(runtimeConfig, 'VITE_APP_VERSION', import.meta.env.VITE_APP_VERSION) ?? packageJson.version ?? '0.1.0',
  apiBaseUrl: readConfigValue(runtimeConfig, 'VITE_API_BASE_URL', import.meta.env.VITE_API_BASE_URL) ?? 'http://localhost:8000',
  requestTimeoutMs: readNumber(readConfigValue(runtimeConfig, 'VITE_REQUEST_TIMEOUT_MS', import.meta.env.VITE_REQUEST_TIMEOUT_MS), 30_000),
  sseHeartbeatSeconds: readNumber(
    readConfigValue(runtimeConfig, 'VITE_SSE_HEARTBEAT_SECONDS', import.meta.env.VITE_SSE_HEARTBEAT_SECONDS),
    15
  ),
  useMockApi: readBoolean(readConfigValue(runtimeConfig, 'VITE_USE_MOCK_API', import.meta.env.VITE_USE_MOCK_API), false),
  clientPlatform: 'web',
  runtimeConfigEnabled: runtimeOverrideKeys.length > 0,
  runtimeOverrideKeys
};
