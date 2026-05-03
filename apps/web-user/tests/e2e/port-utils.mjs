import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';

const MIN_PORT = 1024;
const MAX_PORT = 65535;
const DERIVED_PORT_SPAN = 500;
const PORT_CACHE_MAX_AGE_MS = 30 * 60 * 1000;
const PORT_CACHE_ENV_KEY = 'SC_PLAYWRIGHT_PORT_CACHE_ID';

export function resolvePortCachePath(runId = process.env[PORT_CACHE_ENV_KEY] ?? String(process.pid)) {
  const normalizedRunId = String(runId)
    .trim()
    .replace(/[^a-zA-Z0-9_-]+/g, '-')
    .replace(/^-+|-+$/g, '') || 'default';

  return path.join(os.tmpdir(), `smartcloud-x-web-user-playwright-ports-${normalizedRunId}.json`);
}

function parsePort(value) {
  if (value === undefined || value === null || value === '') {
    return null;
  }

  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < MIN_PORT || parsed > MAX_PORT) {
    return null;
  }

  return parsed;
}

export function createDerivedPort(basePort, pid = process.pid) {
  const normalizedBase = parsePort(basePort);
  if (normalizedBase === null) {
    throw new Error(`Invalid base port: ${basePort}`);
  }

  const safePid = Number.isInteger(pid) ? Math.abs(pid) : 0;
  const offset = safePid % DERIVED_PORT_SPAN;
  return normalizedBase + offset;
}

export function resolvePlaywrightPorts({
  appPortEnv = process.env.PLAYWRIGHT_APP_PORT,
  apiPortEnv = process.env.PLAYWRIGHT_API_PORT,
  pid = process.pid
} = {}) {
  const appPort = parsePort(appPortEnv) ?? createDerivedPort(34100, pid);
  const requestedApiPort = parsePort(apiPortEnv);
  let apiPort = requestedApiPort ?? createDerivedPort(38100, pid);

  if (apiPort === appPort) {
    apiPort = createDerivedPort(38100, pid);
    if (apiPort === appPort) {
      apiPort += 1;
    }
  }

  return {
    appPort,
    apiPort
  };
}

async function canListenOnPort(port, host) {
  return await new Promise((resolve) => {
    const server = net.createServer();

    server.once('error', () => {
      resolve(false);
    });

    server.listen(port, host, () => {
      server.close(() => resolve(true));
    });
  });
}

function isProcessAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) {
    return false;
  }

  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function readCachedPorts() {
  const cachePath = resolvePortCachePath();
  if (!fs.existsSync(cachePath)) {
    return null;
  }

  try {
    const payload = JSON.parse(fs.readFileSync(cachePath, 'utf8'));
    const writtenAt = Date.parse(payload.writtenAt);
    if (!Number.isFinite(writtenAt) || Date.now() - writtenAt > PORT_CACHE_MAX_AGE_MS) {
      return null;
    }

    const appPort = parsePort(payload.appPort);
    const apiPort = parsePort(payload.apiPort);
    const ownerPid = Number(payload.ownerPid);
    if (appPort === null || apiPort === null || !isProcessAlive(ownerPid)) {
      return null;
    }

    return {
      appPort,
      apiPort,
      ownerPid
    };
  } catch {
    return null;
  }
}

function writeCachedPorts(ports) {
  const cachePath = resolvePortCachePath();
  fs.writeFileSync(
    cachePath,
    JSON.stringify(
      {
        ...ports,
        ownerPid: process.pid,
        writtenAt: new Date().toISOString()
      },
      null,
      2
    ),
    'utf8'
  );
}

export async function findAvailablePort(
  startPort,
  {
    host = '127.0.0.1',
    maxAttempts = 25,
    excludePorts = []
  } = {}
) {
  const normalizedStart = parsePort(startPort);
  if (normalizedStart === null) {
    throw new Error(`Invalid start port: ${startPort}`);
  }

  const excluded = new Set(excludePorts);
  for (let offset = 0; offset < maxAttempts; offset += 1) {
    const candidate = normalizedStart + offset;
    if (candidate > MAX_PORT || excluded.has(candidate)) {
      continue;
    }

    if (await canListenOnPort(candidate, host)) {
      return candidate;
    }
  }

  throw new Error(`Unable to find an available port from ${normalizedStart}`);
}

export async function resolveAvailablePlaywrightPorts({
  appPortEnv = process.env.PLAYWRIGHT_APP_PORT,
  apiPortEnv = process.env.PLAYWRIGHT_API_PORT,
  pid = process.pid,
  host = '127.0.0.1'
} = {}) {
  const requested = resolvePlaywrightPorts({
    appPortEnv,
    apiPortEnv,
    pid
  });

  const appPort = await findAvailablePort(requested.appPort, {
    host
  });
  const apiPort = await findAvailablePort(requested.apiPort, {
    host,
    excludePorts: [appPort]
  });

  return {
    appPort,
    apiPort
  };
}

export async function resolveStablePlaywrightPorts(options = {}) {
  const cachedPorts = readCachedPorts();
  if (cachedPorts) {
    return {
      appPort: cachedPorts.appPort,
      apiPort: cachedPorts.apiPort
    };
  }

  const ports = await resolveAvailablePlaywrightPorts(options);
  writeCachedPorts(ports);
  return ports;
}
