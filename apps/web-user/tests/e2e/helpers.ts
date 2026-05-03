import { expect, type Page } from '@playwright/test';

function resolveApiBaseUrl(): string {
  const port = process.env.SC_PLAYWRIGHT_API_PORT ?? process.env.PLAYWRIGHT_API_PORT ?? '38090';
  return `http://127.0.0.1:${port}`;
}

export function resolveAppBaseUrl(): string {
  const port = process.env.SC_PLAYWRIGHT_APP_PORT ?? process.env.PLAYWRIGHT_APP_PORT ?? '3100';
  return `http://127.0.0.1:${port}`;
}

export function resolveAppUrl(path: string): string {
  return new URL(path, `${resolveAppBaseUrl()}/`).toString();
}

const apiBaseUrl = resolveApiBaseUrl();
const runtimeConfigRoutePattern = '**/runtime-config.js';

interface ResetApiOptions {
  profile?: 'full' | 'limited_marketing';
  scenarios?: Array<
    | 'stream_disconnect_once'
    | 'billing_summary_requires_refresh_once'
    | 'marketing_copy_rate_limited'
    | 'citation_detail_forbidden'
    | 'research_task_completes_with_report'
    | 'research_report_file_missing'
  >;
}

interface RuntimeConfigOverrides {
  VITE_APP_TITLE?: string;
  VITE_APP_VERSION?: string;
  VITE_API_BASE_URL?: string;
  VITE_REQUEST_TIMEOUT_MS?: string;
  VITE_SSE_HEARTBEAT_SECONDS?: string;
  VITE_USE_MOCK_API?: string;
}

export async function resetApi(options: ResetApiOptions = {}): Promise<void> {
  const response = await fetch(`${apiBaseUrl}/__test/reset`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(options)
  });

  if (!response.ok) {
    throw new Error(`Failed to reset e2e API server: HTTP ${response.status}`);
  }
}

export async function login(page: Page, account = 'demo@smartcloud.local', password = 'smartcloud-demo'): Promise<void> {
  await page.goto(resolveAppUrl('/login'));
  await page.getByLabel('账号').fill(account);
  await page.getByLabel('密码').fill(password);
  await page.getByRole('button', { name: '登录并进入控制台' }).click();

  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole('heading', { name: '用户工作台总览' })).toBeVisible();
  await expect(page.getByText('Live API')).toBeVisible();
}

export async function applyRuntimeConfig(page: Page, overrides: RuntimeConfigOverrides): Promise<void> {
  await page.route(runtimeConfigRoutePattern, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/javascript; charset=utf-8',
      body: `window.__SMARTCLOUD_RUNTIME_CONFIG__ = Object.assign({}, window.__SMARTCLOUD_RUNTIME_CONFIG__ || {}, ${JSON.stringify(overrides)});`
    });
  });
}

export async function openAppPage(page: Page, path: string, heading: string): Promise<void> {
  await page.goto(resolveAppUrl(path));
  await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible();
}
