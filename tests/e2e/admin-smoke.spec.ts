import { expect, test } from '../../apps/web-user/node_modules/@playwright/test/index.mjs';

test('repo root browser can open web-admin console shell', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('中文测试后台 / 运营控制台')).toBeVisible();
  await expect(page.getByRole('heading', { name: '让测试人员一打开就知道现在该做什么' })).toBeVisible();
  await expect(page.getByRole('link', { name: '测试入口' })).toBeVisible();
});
