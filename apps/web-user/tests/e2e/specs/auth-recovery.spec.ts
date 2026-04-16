import { expect, test } from '@playwright/test';
import { resetApi } from '../helpers';

test('sends a reset code, completes password recovery, and signs in with the new password', async ({ page }) => {
  await resetApi();
  await page.goto('/login');

  await page.getByRole('button', { name: '忘记密码？通过验证码重置' }).click();
  await expect(page.getByRole('heading', { name: '找回并重置密码', exact: true })).toBeVisible();

  await page.getByRole('button', { name: '发送重置验证码' }).click();
  await expect(page.getByText(/重置验证码已发送至/)).toBeVisible();

  await page.getByRole('button', { name: '校验验证码并创建挑战' }).click();
  await expect(page.getByText(/challenge_id：challenge_/)).toBeVisible();

  await page.getByLabel('新密码', { exact: true }).fill('smartcloud-demo-reset');
  await page.getByLabel('确认新密码', { exact: true }).fill('smartcloud-demo-reset');
  await page.getByRole('button', { name: '提交新密码' }).click();

  await expect(page.getByText('密码已重置，请使用新密码重新登录。')).toBeVisible();
  await page.getByLabel('密码').fill('smartcloud-demo-reset');
  await page.getByRole('button', { name: '登录并进入控制台' }).click();

  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole('heading', { name: '用户工作台总览', exact: true })).toBeVisible();
});
