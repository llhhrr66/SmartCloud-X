const { spawn } = require('node:child_process');
const path = require('node:path');

const [, , mode, ...args] = process.argv;
const repoRoot = path.resolve(__dirname, '..', '..');
const webUserRoot = path.resolve(repoRoot, 'apps', 'web-user');
const webAdminRoot = path.resolve(repoRoot, 'apps', 'web-admin');

function forwardSignal(child, signal) {
  process.on(signal, () => {
    if (!child.killed) {
      child.kill(signal);
    }
  });
}

function run(command, commandArgs, options) {
  const child = spawn(command, commandArgs, {
    stdio: 'inherit',
    ...options,
  });

  forwardSignal(child, 'SIGINT');
  forwardSignal(child, 'SIGTERM');

  child.on('error', (error) => {
    console.error(error);
    process.exit(1);
  });
  child.on('exit', (code, signal) => {
    if (signal) {
      process.kill(process.pid, signal);
      return;
    }
    process.exit(code ?? 1);
  });
}

if (mode === 'mock-api') {
  const [apiPort, serverScript] = args;
  if (!apiPort || !serverScript) {
    throw new Error('mock-api mode requires <apiPort> <serverScript>');
  }
  run(process.execPath, [serverScript], {
    cwd: repoRoot,
    env: {
      ...process.env,
      PLAYWRIGHT_API_PORT: String(apiPort),
    },
  });
} else if (mode === 'web-user-dev') {
  const [appPort, apiUrl] = args;
  if (!appPort || !apiUrl) {
    throw new Error('web-user-dev mode requires <appPort> <apiUrl>');
  }
  run(
    process.execPath,
    [path.resolve(webUserRoot, 'node_modules', 'vite', 'bin', 'vite.js'), '--host', '127.0.0.1', '--port', String(appPort)],
    {
      cwd: webUserRoot,
      env: {
        ...process.env,
        VITE_USE_MOCK_API: 'false',
        VITE_API_BASE_URL: apiUrl,
      },
    },
  );
} else if (mode === 'web-admin-dev') {
  const [adminPort, apiUrl] = args;
  if (!adminPort || !apiUrl) {
    throw new Error('web-admin-dev mode requires <adminPort> <apiUrl>');
  }
  run(
    process.execPath,
    [path.resolve(webAdminRoot, 'node_modules', 'vite', 'bin', 'vite.js'), '--host', '127.0.0.1', '--port', String(adminPort)],
    {
      cwd: webAdminRoot,
      env: {
        ...process.env,
        VITE_KNOWLEDGE_SERVICE_BASE_URL: `${apiUrl}/api/knowledge/v1`,
        VITE_RAG_SERVICE_BASE_URL: `${apiUrl}/api/rag/v1`,
        VITE_OPERATOR_REASON_HEADER: 'X-Operator-Reason',
      },
    },
  );
} else {
  throw new Error(`unknown mode: ${mode ?? '<missing>'}`);
}
