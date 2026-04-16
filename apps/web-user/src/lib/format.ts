import type {
  ConversationStatus,
  IcpApplicationStatus,
  RefundStatus,
  Scene,
  TicketPriority,
  ToolCallStatus
} from '../types/domain';

export const sceneLabels: Record<Scene, string> = {
  customer_service: '智能客服',
  billing: '账单与订单',
  technical_support: '技术支持',
  icp: '备案服务',
  marketing: '营销推广',
  research: '深度研究'
};

export function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'short'
  }).format(new Date(value));
}

export function formatCurrency(value: string | number, currency = 'CNY'): string {
  const amount = typeof value === 'string' ? Number(value) : value;
  return new Intl.NumberFormat('zh-CN', {
    style: 'currency',
    currency,
    minimumFractionDigits: 2
  }).format(Number.isFinite(amount) ? amount : 0);
}

export function conversationStatusLabel(status: ConversationStatus): string {
  return (
    {
      active: '进行中',
      running: '处理中',
      archived: '已归档',
      closed: '已关闭',
      deleted: '已删除',
      expired: '已过期'
    }[status] ?? status
  );
}

export function toolStatusLabel(status: ToolCallStatus): string {
  return (
    {
      pending: '待执行',
      running: '执行中',
      success: '成功',
      failed: '失败',
      timeout: '超时',
      cancelled: '已取消'
    }[status] ?? status
  );
}

export function ticketPriorityLabel(priority: TicketPriority): string {
  return {
    low: '低',
    medium: '中',
    high: '高',
    urgent: '紧急'
  }[priority];
}

export function refundStatusLabel(status: RefundStatus): string {
  return {
    pending_review: '待审核',
    approved: '已批准',
    rejected: '已拒绝',
    processing: '处理中',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消'
  }[status];
}

export function orderStatusLabel(status: string): string {
  return (
    {
      pending: '待支付',
      paid: '已支付',
      provisioning: '开通中',
      active: '生效中',
      expired: '已到期',
      cancelled: '已取消',
      refunded: '已退款'
    }[status] ?? status
  );
}

export function icpApplicationStatusLabel(status: IcpApplicationStatus): string {
  return {
    materials_pending: '待补材料',
    submitted: '已提交',
    reviewing: '审核中',
    approved: '已通过',
    rejected: '已驳回'
  }[status];
}

export function truncate(value: string, maxLength = 72): string {
  return value.length <= maxLength ? value : `${value.slice(0, maxLength)}...`;
}

export function formatRetryAfterHint(retryAfterMs?: number): string | null {
  if (typeof retryAfterMs !== 'number' || !Number.isFinite(retryAfterMs) || retryAfterMs <= 0) {
    return null;
  }

  return `建议约 ${Math.max(1, Math.ceil(retryAfterMs / 1000))} 秒后重试。`;
}
