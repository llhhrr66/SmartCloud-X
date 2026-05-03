import { defineConfig, devices } from '@playwright/test';
import {
  resolveStablePlaywrightPorts,
  resolvePlaywrightPorts
} from './tests/e2e/port-utils.mjs';

process.env.SC_PLAYWRIGHT_PORT_CACHE_ID =
  process.env.SC_PLAYWRIGHT_PORT_CACHE_ID ?? `run-${process.pid}-${Date.now().toString(36)}`;

const reuseExistingServer = process.env.PLAYWRIGHT_REUSE_SERVER === '1';
const requestedPorts = resolvePlaywrightPorts();

// Derive per-run default ports and actively probe for a free pair so stale local
// listeners do not block the owned `npm run test:e2e` path on Windows.
const { appPort, apiPort } = reuseExistingServer
  ? requestedPorts
  : await resolveStablePlaywrightPorts();
const appUrl = `http://127.0.0.1:${appPort}`;
const apiUrl = `http://127.0.0.1:${apiPort}`;

process.env.PLAYWRIGHT_APP_PORT = String(appPort);
process.env.PLAYWRIGHT_API_PORT = String(apiPort);

export default defineConfig({
  testDir: './tests/e2e/specs',
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : [['list']],
  timeout: 45_000,
  expect: {
    timeout: 8_000
  },
  use: {
    baseURL: appUrl,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure'
  },
  webServer: [
    {
      command: 'node tests/e2e/mock-api-server.mjs',
      env: {
        ...process.env,
        PLAYWRIGHT_API_PORT: String(apiPort)
      },
      port: apiPort,
      stdout: 'pipe',
      wait: {
        stdout: /\[mock-api-server\] listening on http:\/\/127\.0\.0\.1:(?<SC_PLAYWRIGHT_API_PORT>\d+)/
      },
      timeout: 120_000,
      reuseExistingServer
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${appPort}`,
      env: {
        ...process.env,
        VITE_USE_MOCK_API: 'false',
        VITE_API_BASE_URL: apiUrl
      },
      port: appPort,
      stdout: 'pipe',
      wait: {
        stdout: /http:\/\/127\.0\.0\.1:(?<SC_PLAYWRIGHT_APP_PORT>\d+)/
      },
      timeout: 120_000,
      reuseExistingServer
    }
  ],
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome']
      }
    }
  ]
});
