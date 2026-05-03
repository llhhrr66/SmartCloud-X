import { expect, test } from '@playwright/test';
import { login, openAppPage, resetApi, resolveAppUrl } from '../helpers';

test('recovers from a one-time 401 by refreshing the auth session', async ({ page }) => {
  await resetApi({
    scenarios: ['billing_summary_requires_refresh_once']
  });
  await login(page);
  await page.getByRole('navigation').getByRole('link', { name: '账单', exact: true }).click();

  await expect(page).toHaveURL(/\/billing$/);
  await expect(page.getByRole('heading', { name: '账单结果页', exact: true })).toBeVisible();
  await expect(page.getByText('¥932.50').first()).toBeVisible();
  await expect(page.getByText('账单明细')).toBeVisible();
});

test('shows permission denial UX when the logged-in user lacks route access', async ({ page }) => {
  await resetApi({
    profile: 'limited_marketing'
  });
  await login(page);
  await page.goto(resolveAppUrl('/marketing'));

  await expect(page.getByText('营销暂未开通')).toBeVisible();
  await expect(page.getByText('user:marketing.read')).toBeVisible();
  await expect(page.getByText('permission_denied', { exact: true })).toBeVisible();
});

test('renders structured 429 API errors in the marketing workspace', async ({ page }) => {
  await resetApi({
    scenarios: ['marketing_copy_rate_limited']
  });
  await login(page);
  await openAppPage(page, '/marketing', '营销中心');

  await page.getByRole('button', { name: '生成营销文案' }).click();

  await expect(page.getByText('营销文案生成触发限流，请 30 秒后重试。')).toBeVisible();
  await expect(page.getByText('api_error', { exact: true }).first()).toBeVisible();
});
