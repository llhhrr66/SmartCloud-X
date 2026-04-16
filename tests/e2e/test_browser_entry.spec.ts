import { expect, test } from '../../apps/web-user/node_modules/@playwright/test/index.mjs';
import { login, openAppPage, resetApi } from '../../apps/web-user/tests/e2e/helpers';

test('repo browser entry recovers billing_summary_requires_refresh_once on billing bootstrap', async ({ page }) => {
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

test('repo browser entry opens citation detail on billing happy path without injected failures', async ({
  page
}) => {
  await resetApi();
  await login(page);
  await openAppPage(page, '/chat', '聊天主链路');

  await page.getByRole('button', { name: '账单分析' }).click();
  await page.getByRole('button', { name: '发送消息' }).click();

  await expect(page.getByText('最近三个月账单总额为 932.50 元，其中云服务器 780.00 元。')).toBeVisible({
    timeout: 10_000
  });

  await page.getByRole('button', { name: /账单说明/ }).first().click();
  await expect(page.getByRole('heading', { name: '引用详情' })).toBeVisible();
  await expect(page.getByText('账单说明（E2E 引用详情）')).toBeVisible();
  await expect(page.getByText('账单汇总来自财务账单知识片段')).toBeVisible();
});

test('repo browser entry blocks limited_marketing route access with permission_denied UX', async ({ page }) => {
  await resetApi({
    profile: 'limited_marketing'
  });
  await login(page);
  await page.goto('/marketing');

  await expect(page.getByText('营销暂未开通')).toBeVisible();
  await expect(page.getByText('user:marketing.read')).toBeVisible();
  await expect(page.getByText('permission_denied', { exact: true })).toBeVisible();
});

test('repo browser entry survives SSE reconnect when stream_disconnect_once interrupts chat', async ({ page }) => {
  await resetApi({
    scenarios: ['stream_disconnect_once']
  });
  await login(page);
  await openAppPage(page, '/chat', '聊天主链路');

  await page.getByRole('button', { name: '账单分析' }).click();
  await page.getByRole('button', { name: '发送消息' }).click();

  await expect(page.getByText(/流式连接已中断，正在进行第 1\/3 次自动重连/)).toBeVisible();
  await expect(page.getByText('最近三个月账单总额为 932.50 元，其中云服务器 780.00 元。')).toBeVisible({
    timeout: 15_000
  });

  await page.getByRole('button', { name: /账单说明/ }).first().click();
  await expect(page.getByRole('heading', { name: '引用详情' })).toBeVisible();
  await expect(page.getByText('账单说明（E2E 引用详情）')).toBeVisible();
});

test('repo browser entry shows citation_detail_forbidden errors in citation drawer', async ({ page }) => {
  await resetApi({
    scenarios: ['citation_detail_forbidden']
  });
  await login(page);
  await openAppPage(page, '/chat', '聊天主链路');

  await page.getByRole('button', { name: '账单分析' }).click();
  await page.getByRole('button', { name: '发送消息' }).click();

  await expect(page.getByText('最近三个月账单总额为 932.50 元，其中云服务器 780.00 元。')).toBeVisible({
    timeout: 10_000
  });

  await page.getByRole('button', { name: /账单说明/ }).first().click();
  await expect(page.getByText('当前账号无权查看该引用原文。')).toBeVisible();
  await expect(page.getByText('api_error')).toBeVisible();
});

test('repo browser entry renders structured 429 marketing errors for marketing_copy_rate_limited', async ({ page }) => {
  await resetApi({
    scenarios: ['marketing_copy_rate_limited']
  });
  await login(page);
  await openAppPage(page, '/marketing', '营销中心');

  await page.getByRole('button', { name: '生成营销文案' }).click();

  await expect(page.getByText('营销文案生成触发限流，请 30 秒后重试。')).toBeVisible();
  await expect(page.getByText('api_error', { exact: true }).first()).toBeVisible();
});

test('repo browser entry surfaces research_report_file_missing in report preview', async ({ page }) => {
  await resetApi({
    scenarios: ['research_task_completes_with_report', 'research_report_file_missing']
  });
  await login(page);
  await openAppPage(page, '/research', '研究中心');

  await page.getByLabel('主题').fill('Repo E2E 研究报告缺失');
  await page.getByLabel('范围').fill('验证 repo 根浏览器入口覆盖研究报告缺失结构化错误。');
  await page.getByLabel('输出格式').selectOption('pdf');
  await page.getByRole('button', { name: '创建研究任务' }).click();

  const taskCard = page.locator('.task-card').filter({
    has: page.getByText('Repo E2E 研究报告缺失', { exact: true })
  });

  await expect(taskCard.getByText('completed')).toBeVisible({ timeout: 12_000 });
  await expect(taskCard.getByRole('button', { name: '查看报告文件' })).toBeVisible();

  await taskCard.getByRole('button', { name: '查看报告文件' }).click();

  const reportPreview = page.locator('.card').filter({
    has: page.getByRole('heading', { name: '报告预览', exact: true })
  });

  await expect(reportPreview.getByText('研究报告文件不存在。')).toBeVisible();
});
