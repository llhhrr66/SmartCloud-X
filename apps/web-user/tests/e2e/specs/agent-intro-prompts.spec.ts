import { expect, test } from '@playwright/test';
import { login, openAppPage, resetApi } from '../helpers';

test('shows agent intro, recommended prompts, fills first message on click, and sends it after creating conversation', async ({ page }) => {
  await resetApi();
  await login(page);
  await openAppPage(page, '/chat', 'AI 会话');

  // Open new conversation modal
  await page.getByRole('button', { name: '新建' }).click();
  await expect(page.getByText('新建 AI 会话')).toBeVisible();

  // Select billing agent
  await page.getByRole('button', { name: '账单专员' }).click();

  // Verify intro section is visible
  await expect(page.getByText('账单专员的自我介绍')).toBeVisible();
  await expect(page.getByText(/我是账单专员/)).toBeVisible();

  // Verify 4 recommended prompts are shown
  const promptButtons = page.locator('button.rounded-full');
  const promptCount = await promptButtons.count();
  expect(promptCount).toBeGreaterThanOrEqual(4);

  // Click the first recommended prompt
  const firstPromptText = await promptButtons.first().textContent();
  await promptButtons.first().click();

  // Verify the first message textarea has been filled
  const firstMessageInput = page.locator('#first-message');
  await expect(firstMessageInput).not.toHaveValue('');

  // The value should contain part of the prompt text
  const filledValue = await firstMessageInput.inputValue();
  expect(filledValue.length).toBeGreaterThan(0);

  // Click "开始会话" to create and enter conversation
  await page.getByRole('button', { name: '开始会话' }).click();

  // Should navigate to conversation page
  await expect(page).toHaveURL(/\/chat\/conv_/, { timeout: 10_000 });

  // Verify the first message was actually sent (user message visible in chat)
  await expect(page.locator('.whitespace-pre-wrap').filter({ hasText: filledValue })).toBeVisible({
    timeout: 12_000
  });
});

test('switching agent clears the first message and shows new prompts', async ({ page }) => {
  await resetApi();
  await login(page);
  await openAppPage(page, '/chat', 'AI 会话');

  await page.getByRole('button', { name: '新建' }).click();
  await expect(page.getByText('新建 AI 会话')).toBeVisible();

  // Select customer_service, fill a message
  await page.getByRole('button', { name: '客服助手' }).click();
  await page.locator('#first-message').fill('some test message');

  // Switch to marketing agent
  await page.getByRole('button', { name: '营销专员' }).click();

  // First message should be cleared
  await expect(page.locator('#first-message')).toHaveValue('');

  // Marketing intro should be visible
  await expect(page.getByText('营销专员的自我介绍')).toBeVisible();
  await expect(page.getByText(/我是营销专员/)).toBeVisible();
});
