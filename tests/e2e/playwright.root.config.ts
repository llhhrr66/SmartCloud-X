import { defineConfig, devices } from '../../apps/web-user/node_modules/@playwright/test/index.mjs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const configDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(configDir, '..', '..');
const webUserRoot = path.resolve(repoRoot, 'apps/web-user');

const appPort = Number(process.env.QA_BROWSER_APP_PORT ?? 3200);
const apiPort = Number(process.env.QA_BROWSER_API_PORT ?? 39090);
const appUrl = `http://127.0.0.1:${appPort}`;
const apiUrl = `http://127.0.0.1:${apiPort}`;

process.env.PLAYWRIGHT_API_PORT = String(apiPort);
process.env.TEST_API_BASE_URL = apiUrl;

export default defineConfig({
  testDir: configDir,
  testMatch: ['test_browser_entry.spec.ts'],
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
      command: `PLAYWRIGHT_API_PORT=${apiPort} node ${path.resolve(webUserRoot, 'tests/e2e/mock-api-server.mjs')}`,
      cwd: repoRoot,
      url: `${apiUrl}/__test/health`,
      timeout: 120_000,
      reuseExistingServer: !process.env.CI
    },
    {
      command: `VITE_USE_MOCK_API=false VITE_API_BASE_URL=${apiUrl} npm run dev -- --host 127.0.0.1 --port ${appPort}`,
      cwd: webUserRoot,
      url: `${appUrl}/login`,
      timeout: 120_000,
      reuseExistingServer: !process.env.CI
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
