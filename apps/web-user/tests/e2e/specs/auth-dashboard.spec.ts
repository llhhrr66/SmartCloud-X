import { expect, test } from '@playwright/test';
import { login, resetApi } from '../helpers';

test('logs in and loads the live dashboard baseline', async ({ page }) => {
  await resetApi();
  await login(page);

  const nav = page.getByRole('navigation');
  await expect(nav.getByRole('link', { name: '聊天', exact: true })).toBeVisible();
  await expect(nav.getByRole('link', { name: '工单', exact: true })).toBeVisible();
  await expect(page.getByText('本月消费')).toBeVisible();
  await expect(page.getByText('¥932.50')).toBeVisible();
  await expect(page.getByText('当前账号已开通')).toBeVisible();
});
