import { expect, test } from '@playwright/test';
import { login, openAppPage, resetApi } from '../helpers';

test('creates a ticket from the focused ticket center', async ({ page }) => {
  await resetApi();
  await login(page);
  await openAppPage(page, '/tickets', '工单中心');

  const ticketSection = page.locator('div.card').filter({
    has: page.getByRole('heading', { name: '工单工作台', exact: true })
  });
  const ticketForm = ticketSection.locator('form').first();

  await ticketForm.getByLabel('主题', { exact: true }).fill('E2E 工单提交流程');
  await ticketForm.locator('textarea').first().fill('请帮我复核 GPU 挂盘异常的排障步骤和建议的下一步动作。');
  await ticketForm.getByRole('button', { name: '创建工单' }).click();

  await expect(page.getByText(/工单 tic_e2e_/)).toBeVisible();
  await expect(page.getByRole('button', { name: /E2E 工单提交流程/ }).first()).toBeVisible();
});

test('keeps generic attachments and ICP materials separated in the composite service desk workspace', async ({ page }) => {
  await resetApi();
  await login(page);
  await openAppPage(page, '/service-desk', '服务台');

  const uploadSection = page.locator('form.card').filter({
    has: page.getByRole('heading', { name: '附件 / 材料准备', exact: true })
  });
  const ticketSection = page.locator('div.card').filter({
    has: page.getByRole('heading', { name: '工单工作台', exact: true })
  });
  const ticketForm = ticketSection.locator('form').first();
  const icpSection = page.locator('div.card').filter({
    has: page.getByRole('heading', { name: 'ICP备案工作台', exact: true })
  });

  await uploadSection.getByLabel('文件名').fill('generic-ticket-evidence-e2e.png');
  await uploadSection.getByRole('button', { name: '申请上传凭据' }).click();
  await expect(uploadSection.getByRole('button', { name: /完成上传登记并加入 工单 \/ 退款附件/ })).toBeVisible();

  await uploadSection.getByRole('button', { name: /完成上传登记并加入 工单 \/ 退款附件/ }).click();
  await expect(page.getByText('上传登记已完成，附件已加入工单 / 退款 / 工单回复表单。')).toBeVisible();
  await expect(uploadSection.locator('.list-row').filter({ hasText: 'generic-ticket-evidence-e2e.png' })).toHaveCount(1);
  await expect(uploadSection.getByText('尚未准备 ICP 材料。营业执照、域名证书等文件应单独登记到这里。')).toBeVisible();

  await uploadSection.getByLabel('用途').selectOption('icp_material');
  await uploadSection.getByLabel('文件名').fill('business-license-e2e.pdf');
  await uploadSection.getByLabel('MIME').fill('application/pdf');
  await uploadSection.getByRole('button', { name: '申请上传凭据' }).click();
  await uploadSection.getByRole('button', { name: /完成上传登记并加入 ICP 备案材料/ }).click();

  await expect(page.getByText('上传登记已完成，材料已加入 ICP 备案表单。')).toBeVisible();
  await expect(uploadSection.locator('.list-row').filter({ hasText: 'generic-ticket-evidence-e2e.png' })).toHaveCount(1);
  await expect(uploadSection.locator('.list-row').filter({ hasText: 'business-license-e2e.pdf' })).toHaveCount(1);

  await ticketForm.getByLabel('主题', { exact: true }).fill('E2E 综合服务台工单');
  await ticketForm.locator('textarea').first().fill('验证综合服务台中的附件准备不会污染 ICP 材料区。');
  await ticketForm.getByRole('button', { name: '创建工单' }).click();

  await expect(page.getByText(/工单 tic_e2e_/)).toBeVisible();
  await expect(ticketSection.getByRole('button', { name: /E2E 综合服务台工单/ })).toBeVisible();

  await icpSection.getByRole('button', { name: '材料预检查' }).click();
  await expect(page.getByText('材料预检查通过，可以继续提交备案申请。')).toBeVisible();

  await icpSection.getByRole('button', { name: '提交备案申请' }).click();
  await expect(page.getByText(/备案申请 ICP_E2E_/)).toBeVisible();
});

test('registers an ICP material upload, passes precheck, and submits an application', async ({ page }) => {
  await resetApi();
  await login(page);
  await openAppPage(page, '/icp', 'ICP备案');

  await page.getByRole('button', { name: '申请上传凭据' }).click();
  await expect(page.getByText('已生成上传凭据')).toBeVisible();

  await page.getByRole('button', { name: /完成上传登记并加入 ICP 备案材料/ }).click();
  await expect(page.getByText('上传登记已完成，材料已加入 ICP 备案表单。')).toBeVisible();

  await page.getByRole('button', { name: '材料预检查' }).click();
  await expect(page.getByText('材料预检查通过，可以继续提交备案申请。')).toBeVisible();

  await page.getByRole('button', { name: '提交备案申请' }).click();
  await expect(page.getByText(/备案申请 ICP_E2E_/)).toBeVisible();
  await expect(page.getByText('SmartCloud 模型体验站')).toBeVisible();
  await expect(page.getByText('浏览器跟踪回填', { exact: true })).toBeVisible();
  await expect(
    page.getByText('当前 ICP 申请历史仍来自浏览器跟踪的申请号回填，因为后端尚未提供 canonical list endpoint。')
  ).toBeVisible();
});
