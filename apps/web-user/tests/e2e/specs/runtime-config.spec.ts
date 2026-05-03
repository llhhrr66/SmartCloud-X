import { expect, test } from '@playwright/test';
import { applyRuntimeConfig, login, resetApi, resolveAppUrl } from '../helpers';

const apiBaseUrl = `http://127.0.0.1:${process.env.SC_PLAYWRIGHT_API_PORT ?? process.env.PLAYWRIGHT_API_PORT ?? '38090'}`;

test('applies runtime-config overrides in the browser before and after login', async ({ page }) => {
  await resetApi();
  await applyRuntimeConfig(page, {
    VITE_APP_TITLE: 'SmartCloud Runtime Console E2E',
    VITE_APP_VERSION: '9.9.9-runtime',
    VITE_API_BASE_URL: apiBaseUrl,
    VITE_SSE_HEARTBEAT_SECONDS: '33',
    VITE_USE_MOCK_API: 'false'
  });

  await page.goto(resolveAppUrl('/login'));
  await expect(page).toHaveTitle('SmartCloud Runtime Console E2E');

  await login(page);

  const shellMeta = page.locator('.sidebar__meta');
  await expect(page.locator('.sidebar__title')).toHaveText('SmartCloud Runtime Console E2E');
  await expect(shellMeta.getByText('9.9.9-runtime', { exact: true })).toBeVisible();
  await expect(page.getByText('Runtime Config', { exact: true })).toBeVisible();
  await expect(shellMeta.getByText(apiBaseUrl, { exact: true })).toBeVisible();
  await expect(shellMeta.getByText('33s', { exact: true })).toBeVisible();
});
