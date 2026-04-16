import { expect, test } from '../../apps/web-user/node_modules/@playwright/test/index.mjs';
import { login, openAppPage, resetApi } from '../../apps/web-user/tests/e2e/helpers';

test('repo browser app smoke logs in and renders dashboard and seeded session history', async ({
  page
}) => {
  await resetApi();
  await login(page);

  const navigation = page.getByRole('navigation');
  await expect(page.getByRole('heading', { name: '用户工作台总览', exact: true })).toBeVisible();
  await expect(navigation.getByRole('link', { name: '聊天', exact: true })).toBeVisible();
  await expect(navigation.getByRole('link', { name: '会话', exact: true })).toBeVisible();
  await expect(page.getByText('本月消费')).toBeVisible();
  await expect(page.getByText('¥932.50')).toBeVisible();
  await expect(page.getByText('当前账号已开通')).toBeVisible();

  await openAppPage(page, '/sessions', '会话历史');

  const sessionCard = page.locator('.session-card').filter({
    has: page.getByRole('heading', { name: 'GPU 挂载排障', exact: true })
  });

  await expect(sessionCard).toHaveCount(1);
  await expect(sessionCard.getByText('Product_Tech_Agent')).toBeVisible();
  await expect(sessionCard.getByText('技术支持')).toBeVisible();
  await expect(sessionCard.getByText('消息数：2')).toBeVisible();
});
