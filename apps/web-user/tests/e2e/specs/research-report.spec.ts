import { expect, test } from '@playwright/test';
import { login, openAppPage, resetApi } from '../helpers';

test('creates a research task, observes completion, and previews the generated report file', async ({ page }) => {
  await resetApi({
    scenarios: ['research_task_completes_with_report']
  });
  await login(page);
  await openAppPage(page, '/research', '研究中心');

  await page.getByLabel('主题').fill('E2E 研究报告预览');
  await page.getByLabel('范围').fill('验证研究任务完成后，浏览器端可以直接预览导出文件元数据。');
  await page.getByLabel('输出格式').selectOption('pdf');
  await page.getByRole('button', { name: '创建研究任务' }).click();

  const taskCard = page.locator('.task-card').filter({
    has: page.getByText('E2E 研究报告预览', { exact: true })
  });

  await expect(taskCard.getByText('研究任务已创建，等待后端服务完成生成。')).toBeVisible();
  await expect(taskCard.getByText('completed')).toBeVisible({ timeout: 12_000 });
  await expect(taskCard.getByRole('button', { name: '查看报告文件' })).toBeVisible();

  await taskCard.getByRole('button', { name: '查看报告文件' }).click();

  const reportPreview = page.locator('.card').filter({
    has: page.getByRole('heading', { name: '报告预览', exact: true })
  });

  await expect(reportPreview.getByText('report-e2e.md', { exact: true })).toBeVisible();
  await expect(reportPreview.getByText('file_seed_001', { exact: true })).toBeVisible();
  await expect(reportPreview.getByText('text/markdown', { exact: true })).toBeVisible();
  await expect(reportPreview.getByRole('link', { name: /打开下载链接/ })).toHaveAttribute(
    'href',
    'https://downloads.smartcloud.local/reports/report-e2e.md'
  );
});

test('renders a file-preview error when the generated research report metadata is unavailable', async ({ page }) => {
  await resetApi({
    scenarios: ['research_task_completes_with_report', 'research_report_file_missing']
  });
  await login(page);
  await openAppPage(page, '/research', '研究中心');

  await page.getByLabel('主题').fill('E2E 研究报告缺失');
  await page.getByLabel('范围').fill('验证研究任务完成但文件服务返回 404 时，页面能渲染结构化错误。');
  await page.getByRole('button', { name: '创建研究任务' }).click();

  const taskCard = page.locator('.task-card').filter({
    has: page.getByText('E2E 研究报告缺失', { exact: true })
  });

  await expect(taskCard.getByText('completed')).toBeVisible({ timeout: 12_000 });
  await taskCard.getByRole('button', { name: '查看报告文件' }).click();

  const reportPreview = page.locator('.card').filter({
    has: page.getByRole('heading', { name: '报告预览', exact: true })
  });

  await expect(reportPreview.getByText('研究报告文件不存在。')).toBeVisible();
});
