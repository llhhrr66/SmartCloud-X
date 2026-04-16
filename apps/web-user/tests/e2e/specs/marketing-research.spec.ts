import { expect, test } from '@playwright/test';
import { login, openAppPage, resetApi } from '../helpers';

test('creates marketing outputs and a research task in the browser', async ({ page }) => {
  await resetApi();
  await login(page);
  await openAppPage(page, '/marketing', '营销中心');

  await page.getByRole('button', { name: '生成营销文案' }).click();
  await expect(page.getByText('面向企业技术负责人的大模型上云方案')).toBeVisible();
  await expect(page.getByText('立即申请 GPU 试用')).toBeVisible();

  await page.getByRole('button', { name: '创建海报任务' }).click();
  await expect(page.getByText('工业级上云活动')).toBeVisible();
  await expect(page.getByText('queued')).toBeVisible();

  await openAppPage(page, '/research', '研究中心');
  await page.getByLabel('主题').fill('E2E LangGraph 调研');
  await page.getByLabel('范围').fill('验证浏览器端研究任务创建和历史卡片展示。');
  await page.getByRole('button', { name: '创建研究任务' }).click();

  await expect(page.getByText('E2E LangGraph 调研')).toBeVisible();
  await expect(page.getByText('研究任务已创建，等待后端服务完成生成。')).toBeVisible();
});
