import { expect, test } from '@playwright/test';
import { login, openAppPage, resetApi } from '../helpers';

test('updates the profile and rotates the password through the browser', async ({ page }) => {
  await resetApi();
  await login(page);
  await openAppPage(page, '/profile', '个人中心');

  await page.getByLabel('昵称').fill('E2E 演示用户（已更新）');
  await page.getByLabel('语言').fill('en-US');
  await page.getByLabel('时区').fill('UTC');
  await page.getByRole('button', { name: '保存资料' }).click();

  await expect(page.getByText('个人资料已更新。')).toBeVisible();
  await expect(page.getByLabel('昵称')).toHaveValue('E2E 演示用户（已更新）');
  await expect(page.getByLabel('时区')).toHaveValue('UTC');

  await page.getByLabel('旧密码').fill('smartcloud-demo');
  await page.getByLabel('新密码', { exact: true }).fill('smartcloud-demo-rotated');
  await page.getByLabel('确认新密码', { exact: true }).fill('smartcloud-demo-rotated');
  await page.getByRole('button', { name: '修改密码' }).click();

  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByText('密码已修改，请重新登录。')).toBeVisible();

  await page.getByLabel('密码').fill('smartcloud-demo-rotated');
  await page.getByRole('button', { name: '登录并进入控制台' }).click();

  await expect(page).toHaveURL(/\/$/);
  await openAppPage(page, '/profile', '个人中心');
  await expect(page.getByLabel('昵称')).toHaveValue('E2E 演示用户（已更新）');
  await expect(page.getByLabel('时区')).toHaveValue('UTC');
});
