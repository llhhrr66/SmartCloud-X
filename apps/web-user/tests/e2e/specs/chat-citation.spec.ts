import { expect, test } from '@playwright/test';
import { login, openAppPage, resetApi } from '../helpers';

test('sends a chat message, survives one SSE disconnect, and opens citation detail', async ({ page }) => {
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
  await expect(page.getByText('账单汇总来自财务账单知识片段')).toBeVisible();
});

test('renders a citation permission error when citation detail returns 403', async ({ page }) => {
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
