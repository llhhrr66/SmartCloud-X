import { expect, type Page } from '@playwright/test';

const apiBaseUrl = process.env.TEST_API_BASE_URL ?? `http://127.0.0.1:${process.env.PLAYWRIGHT_API_PORT ?? '38090'}`;

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
  await page.goto('/login');
  await page.getByLabel('账号').fill(account);
  await page.getByLabel('密码').fill(password);
  await page.getByRole('button', { name: '登录并进入控制台' }).click();

  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole('heading', { name: '用户工作台总览' })).toBeVisible();
  await expect(page.getByText('Live API')).toBeVisible();
}

export async function openAppPage(page: Page, path: string, heading: string): Promise<void> {
  await page.goto(path);
  await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible();
}
