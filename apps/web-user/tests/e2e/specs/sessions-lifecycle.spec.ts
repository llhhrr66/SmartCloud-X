import { expect, test } from '@playwright/test';
import { login, openAppPage, resetApi } from '../helpers';

test('renames, archives, restores, and deletes a session from the browser', async ({ page }) => {
  await resetApi();
  await login(page);
  await openAppPage(page, '/sessions', '会话历史');

  const originalTitle = 'GPU 挂载排障';
  const renamedTitle = 'GPU 挂载排障（E2E 生命周期）';
  const originalCard = page.locator('.session-card').filter({
    has: page.getByRole('heading', { name: originalTitle, exact: true })
  });

  await expect(originalCard).toHaveCount(1);

  page.once('dialog', async (dialog) => {
    expect(dialog.type()).toBe('prompt');
    await dialog.accept(renamedTitle);
  });
  await originalCard.getByRole('button', { name: '重命名' }).click();

  const renamedCard = page.locator('.session-card').filter({
    has: page.getByRole('heading', { name: renamedTitle, exact: true })
  });

  await expect(renamedCard).toHaveCount(1);
  await renamedCard.getByRole('button', { name: '归档' }).click();
  await expect(renamedCard.getByText('已归档')).toBeVisible();

  await renamedCard.getByRole('button', { name: '恢复' }).click();
  await expect(renamedCard.getByText('进行中')).toBeVisible();

  page.once('dialog', async (dialog) => {
    expect(dialog.type()).toBe('confirm');
    await dialog.accept();
  });
  await renamedCard.getByRole('button', { name: '删除' }).click();

  await expect(renamedCard).toHaveCount(0);
  await expect(page.getByText(renamedTitle)).toHaveCount(0);
});
