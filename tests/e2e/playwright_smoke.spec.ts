import { expect, test } from '../../apps/web-user/node_modules/@playwright/test/index.mjs';
import { login, openAppPage, resetApi } from '../../apps/web-user/tests/e2e/helpers';

test('repo browser smoke preserves marketing and research task cards across reload', async ({
  page
}) => {
  await resetApi({
    scenarios: ['research_task_completes_with_report']
  });
  await login(page);
  await openAppPage(page, '/marketing', '营销中心');

  await page.getByRole('button', { name: '生成营销文案' }).click();
  await expect(page.getByText('面向企业技术负责人的大模型上云方案')).toBeVisible();
  await expect(page.getByText('立即申请 GPU 试用')).toBeVisible();

  await page.getByRole('button', { name: '创建海报任务' }).click();
  await expect(page.getByText('工业级上云活动')).toBeVisible();
  await expect(page.getByText('queued')).toBeVisible();

  await page.evaluate(() => window.localStorage.removeItem('smartcloud-x:web-user:task-registry'));
  await page.reload();

  await expect(page.getByRole('heading', { name: '营销中心', exact: true })).toBeVisible();
  await expect(page.getByText('工业级上云活动')).toBeVisible();

  await openAppPage(page, '/research', '研究中心');
  await page.getByLabel('主题').fill('Repo 根浏览器持久化回放');
  await page.getByLabel('范围').fill('验证 repo 级 Playwright 入口在刷新后仍能恢复研究任务卡片。');
  await page.getByRole('button', { name: '创建研究任务' }).click();

  await expect(page.getByText('Repo 根浏览器持久化回放')).toBeVisible();
  await expect(page.getByText('completed')).toBeVisible({ timeout: 12_000 });
  await expect(page.getByRole('button', { name: '查看报告文件' })).toBeVisible();

  await page.evaluate(() => window.localStorage.removeItem('smartcloud-x:web-user:task-registry'));
  await page.reload();

  await expect(page.getByRole('heading', { name: '研究中心', exact: true })).toBeVisible();
  await expect(page.getByText('Repo 根浏览器持久化回放')).toBeVisible();
  await expect(page.getByRole('button', { name: '查看报告文件' })).toBeVisible();
});

test('repo browser smoke keeps the billing workspace usable across reload after one-time refresh recovery', async ({
  page
}) => {
  await resetApi({
    scenarios: ['billing_summary_requires_refresh_once']
  });
  await login(page);
  await openAppPage(page, '/billing', '账单结果页');

  await expect(page).toHaveURL(/\/billing$/);
  await expect(page.getByText('¥932.50').first()).toBeVisible();
  await expect(page.getByText('账单明细')).toBeVisible();

  await page.reload();

  await expect(page).toHaveURL(/\/billing$/);
  await expect(page.getByRole('heading', { name: '账单结果页', exact: true })).toBeVisible();
  await expect(page.getByText('¥932.50').first()).toBeVisible();
  await expect(page.getByText('账单明细')).toBeVisible();
});
