import { defineConfig, devices } from '../../apps/web-user/node_modules/@playwright/test/index.mjs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const configDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(configDir, '..', '..');
const webUserRoot = path.resolve(repoRoot, 'apps/web-user');
const webAdminRoot = path.resolve(repoRoot, 'apps/web-admin');

const appPort = Number(process.env.QA_BROWSER_APP_PORT ?? 3200);
const apiPort = Number(process.env.QA_BROWSER_API_PORT ?? 39090);
const adminPort = Number(process.env.QA_BROWSER_ADMIN_PORT ?? 3201);
const appUrl = `http://127.0.0.1:${appPort}`;
const apiUrl = `http://127.0.0.1:${apiPort}`;
const adminUrl = `http://127.0.0.1:${adminPort}`;

const loopbackNoProxy = '127.0.0.1,localhost';
process.env.NO_PROXY = process.env.NO_PROXY
  ? `${process.env.NO_PROXY},${loopbackNoProxy}`
  : loopbackNoProxy;
process.env.no_proxy = process.env.no_proxy
  ? `${process.env.no_proxy},${loopbackNoProxy}`
  : loopbackNoProxy;
process.env.SC_PLAYWRIGHT_APP_PORT = String(appPort);
process.env.SC_PLAYWRIGHT_API_PORT = String(apiPort);
process.env.SC_PLAYWRIGHT_ADMIN_PORT = String(adminPort);
process.env.PLAYWRIGHT_API_PORT = String(apiPort);
process.env.TEST_API_BASE_URL = apiUrl;

export default defineConfig({
  testDir: configDir,
  testMatch: ['app-smoke.spec.ts', 'playwright_smoke.spec.ts', 'test_browser_entry.spec.ts', 'admin-smoke.spec.ts'],
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
      command: `node ${path.resolve(configDir, 'run-web-server.cjs')} mock-api ${apiPort} ${path.resolve(webUserRoot, 'tests/e2e/mock-api-server.mjs')}`,
      cwd: repoRoot,
      url: `${apiUrl}/__test/health`,
      timeout: 120_000,
      reuseExistingServer: !process.env.CI
    },
    {
      command: `node ${path.resolve(configDir, 'run-web-server.cjs')} web-user-dev ${appPort} ${apiUrl}`,
      cwd: repoRoot,
      url: `${appUrl}/login`,
      timeout: 120_000,
      reuseExistingServer: !process.env.CI
    },
    {
      command: `node ${path.resolve(configDir, 'run-web-server.cjs')} web-admin-dev ${adminPort} ${apiUrl}`,
      cwd: repoRoot,
      url: `${adminUrl}/`,
      timeout: 120_000,
      reuseExistingServer: !process.env.CI
    }
  ],
  projects: [
    {
      name: 'web-user-chromium',
      use: {
        ...devices['Desktop Chrome']
      },
      testIgnore: ['admin-smoke.spec.ts']
    },
    {
      name: 'web-admin-chromium',
      testMatch: ['admin-smoke.spec.ts'],
      use: {
        ...devices['Desktop Chrome'],
        baseURL: adminUrl
      }
    }
  ]
});
