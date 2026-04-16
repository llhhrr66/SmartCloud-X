import { expect, test } from '@playwright/test';
import { login, openAppPage, resetApi } from '../helpers';

test('shows order detail and keeps a newly created refund visible in the refreshed history', async ({ page }) => {
  await resetApi();
  await login(page);
  await openAppPage(page, '/orders', '订单中心');

  const detailSection = page.locator('div.card').filter({
    has: page.getByRole('heading', { name: '订单详情抽屉', exact: true })
  });
  const refundFormSection = page.locator('div.card').filter({
    has: page.getByRole('heading', { name: '退款申请', exact: true })
  });
  const refundHistorySection = page.locator('div.card').filter({
    has: page.getByRole('heading', { name: '退款记录', exact: true })
  });
  const refundReason = 'E2E 订单退款流程验证：浏览器端刷新后仍需展示新退款时间线。';

  await expect(detailSection.getByText('ord_202604_001')).toBeVisible();
  await expect(detailSection.getByText('cn-shanghai-1')).toBeVisible();
  await expect(detailSection.getByText('1x NVIDIA L40')).toBeVisible();

  await refundFormSection.getByLabel('退款原因').fill(refundReason);
  await refundFormSection.getByRole('button', { name: '提交退款申请' }).click();

  await expect(page.getByText(/退款申请 ref_e2e_/)).toBeVisible();
  await expect(refundHistorySection.getByText(/ref_e2e_/)).toBeVisible();
  await expect(refundHistorySection.getByText(refundReason)).toBeVisible();
});
