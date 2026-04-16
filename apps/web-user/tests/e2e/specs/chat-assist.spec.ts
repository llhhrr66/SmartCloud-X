import { expect, test } from '@playwright/test';
import { login, openAppPage, resetApi } from '../helpers';

test('retries the latest chat turn and carries context into a prefilled assist ticket draft', async ({ page }) => {
  await resetApi();
  await login(page);
  await openAppPage(page, '/chat', '聊天主链路');

  await page.getByRole('button', { name: '账单分析' }).click();
  await page.getByRole('button', { name: '发送消息' }).click();

  await expect(page.getByText('最近三个月账单总额为 932.50 元，其中云服务器 780.00 元。')).toBeVisible({
    timeout: 12_000
  });

  const conversationUrl = page.url();
  const conversationId = conversationUrl.split('/chat/')[1];

  await page.getByRole('button', { name: '重试上一轮' }).first().click();
  await expect(page.getByText('已重新生成上一轮回复，消息列表已刷新。')).toBeVisible();
  await expect(page.getByText('已重新生成上一轮回复，建议继续核对账单周期和实例维度。')).toBeVisible();

  await page.getByRole('button', { name: '创建协助工单' }).click();

  await expect(page).toHaveURL(/\/tickets/);
  await expect(page.getByRole('heading', { name: '工单中心', exact: true })).toBeVisible();
  await expect(page.getByText('已导入聊天协助草稿')).toBeVisible();
  const ticketSection = page.locator('div.card').filter({
    has: page.getByRole('heading', { name: '工单工作台', exact: true })
  });
  const ticketForm = ticketSection.locator('form').first();

  await expect(ticketForm.getByLabel('主题')).toHaveValue(/人工协助：/);
  await expect(ticketForm.getByLabel('分类')).toHaveValue('billing');
  await expect(ticketForm.getByLabel('优先级')).toHaveValue('medium');

  const content = await ticketForm.getByLabel('内容').inputValue();
  expect(content).toContain(`conversation_id: ${conversationId}`);
  expect(content).toContain('scene: 账单与订单');
  expect(content).toContain('trace_id: trace_');
  expect(content).toContain('用户诉求: 帮我查询最近三个月的云服务器账单，并总结费用最高的实例。');

  await ticketForm.getByRole('button', { name: '创建工单' }).click();
  await expect(page.getByText(/工单 tic_e2e_/)).toBeVisible();
});
