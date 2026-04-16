import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { fileService } from '../api/services/files';
import { serviceDeskService } from '../api/services/serviceDesk';
import { useAuth } from '../auth/AuthContext';
import { Badge } from '../components/Badge';
import { PageHeader } from '../components/PageHeader';
import { StatCard } from '../components/StatCard';
import {
  buildChatAttachmentFromFileRecord,
  buildOrderDetailFallback,
  mergeOrderDetailWithRefunds,
  resolveSharedLoadStateRetryAfterMs,
  selectSharedLoadStateDomains,
  sortRefundRecordsByCreatedAt,
  upsertChatAttachment
} from '../shared-sdk';
import {
  formatCurrency,
  formatDateTime,
  formatRetryAfterHint,
  orderStatusLabel,
  refundStatusLabel
} from '../lib/format';
import type { ChatAttachment, OrderDetail, OrderRecord, RefundRecord, ServiceWorkspaceData, UploadPolicy } from '../types/domain';

const emptyWorkspace: ServiceWorkspaceData = {
  orders: [],
  refunds: [],
  tickets: [],
  icpApplications: []
};

const initialUploadForm = {
  fileName: 'refund-proof.png',
  size: '102400',
  mimeType: 'image/png'
};

const initialRefundForm = {
  amount: '',
  reason: '套餐资源与当前业务需求不匹配，申请退回未使用部分。'
};

const workspaceFailureLabels: Record<'orders' | 'refunds', string> = {
  orders: '订单列表',
  refunds: '退款记录'
};
const visibleWorkspaceDomains = ['orders', 'refunds'] as const;

export function OrdersPage(): JSX.Element {
  const { isMock } = useAuth();
  const [workspace, setWorkspace] = useState<ServiceWorkspaceData>(emptyWorkspace);
  const [loading, setLoading] = useState(true);
  const [pageError, setPageError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [keyword, setKeyword] = useState('');
  const [eligibility, setEligibility] = useState<'all' | 'refundable' | 'locked'>('all');
  const [selectedOrderNo, setSelectedOrderNo] = useState<string | null>(null);
  const [detailOpen, setDetailOpen] = useState(true);
  const [orderDetail, setOrderDetail] = useState<OrderDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [selectedRefundNo, setSelectedRefundNo] = useState<string | null>(null);
  const [refundDetail, setRefundDetail] = useState<RefundRecord | null>(null);
  const [refundDetailLoading, setRefundDetailLoading] = useState(false);
  const [refundDetailError, setRefundDetailError] = useState<string | null>(null);
  const [refundForm, setRefundForm] = useState(initialRefundForm);
  const [refundSubmitting, setRefundSubmitting] = useState(false);
  const [uploadForm, setUploadForm] = useState(initialUploadForm);
  const [uploadPolicy, setUploadPolicy] = useState<UploadPolicy | null>(null);
  const [availableAttachments, setAvailableAttachments] = useState<ChatAttachment[]>([]);
  const [uploadSubmitting, setUploadSubmitting] = useState(false);
  const [uploadCompleting, setUploadCompleting] = useState(false);

  const clearFeedback = () => {
    setPageError(null);
    setSuccessMessage(null);
  };

  const loadWorkspace = useCallback(async () => {
    const data = await serviceDeskService.getWorkspace();
    setWorkspace(data);
    return data;
  }, []);

  useEffect(() => {
    let mounted = true;

    const load = async () => {
      try {
        const data = await loadWorkspace();
        if (!mounted) {
          return;
        }

        setSelectedOrderNo((previous) =>
          previous && data.orders.some((item) => item.orderNo === previous) ? previous : data.orders[0]?.orderNo ?? null
        );
      } catch (error) {
        if (mounted) {
          setPageError(error instanceof Error ? error.message : '加载订单工作区失败');
        }
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    };

    void load();

    return () => {
      mounted = false;
    };
  }, [loadWorkspace]);

  const filteredOrders = useMemo(() => {
    const trimmedKeyword = keyword.trim().toLowerCase();

    return workspace.orders.filter((item) => {
      const matchesKeyword =
        !trimmedKeyword ||
        item.orderNo.toLowerCase().includes(trimmedKeyword) ||
        item.productType.toLowerCase().includes(trimmedKeyword);
      const matchesEligibility =
        eligibility === 'all'
          ? true
          : eligibility === 'refundable'
            ? Boolean(item.eligibleForRefund)
            : !item.eligibleForRefund;

      return matchesKeyword && matchesEligibility;
    });
  }, [eligibility, keyword, workspace.orders]);

  const selectedOrder = useMemo<OrderRecord | null>(
    () => workspace.orders.find((item) => item.orderNo === selectedOrderNo) ?? null,
    [selectedOrderNo, workspace.orders]
  );
  const degradedWorkspaceDomainKeys = selectSharedLoadStateDomains(
    workspace.loadState,
    visibleWorkspaceDomains
  );
  const unavailableWorkspaceDomains = degradedWorkspaceDomainKeys.map(
    (item) => workspaceFailureLabels[item]
  );
  const workspaceRetryAfterHint = formatRetryAfterHint(
    resolveSharedLoadStateRetryAfterMs(workspace.loadState, degradedWorkspaceDomainKeys)
  );

  const fallbackRefunds = useMemo(
    () => sortRefundRecordsByCreatedAt(workspace.refunds.filter((item) => item.orderNo === selectedOrderNo)),
    [selectedOrderNo, workspace.refunds]
  );

  useEffect(() => {
    if (!selectedOrderNo) {
      setOrderDetail(null);
      setDetailError(null);
      setSelectedRefundNo(null);
      setRefundDetail(null);
      setRefundDetailError(null);
      return;
    }

    setRefundForm((previous) => ({
      ...previous,
      amount: selectedOrder?.amount ?? previous.amount
    }));

    if (!detailOpen) {
      return;
    }

    let mounted = true;

    const load = async () => {
      setDetailLoading(true);
      setDetailError(null);
      setOrderDetail(null);
      setSelectedRefundNo(null);
      setRefundDetail(null);
      setRefundDetailError(null);

      try {
        const detail = await serviceDeskService.getOrderDetail(selectedOrderNo);
        const mergedDetail = mergeOrderDetailWithRefunds(detail, fallbackRefunds);

        if (mounted) {
          setOrderDetail(mergedDetail);
          setSelectedRefundNo((previous) =>
            previous && mergedDetail.refunds.some((item) => item.refundNo === previous)
              ? previous
              : mergedDetail.refunds[0]?.refundNo ?? null
          );
        }
      } catch (error) {
        if (mounted) {
          setDetailError(error instanceof Error ? error.message : '加载订单详情失败，已展示列表级数据。');
          setOrderDetail(buildOrderDetailFallback(selectedOrder, fallbackRefunds));
          setSelectedRefundNo((previous) =>
            previous && fallbackRefunds.some((item) => item.refundNo === previous) ? previous : fallbackRefunds[0]?.refundNo ?? null
          );
        }
      } finally {
        if (mounted) {
          setDetailLoading(false);
        }
      }
    };

    void load();

    return () => {
      mounted = false;
    };
  }, [detailOpen, fallbackRefunds, selectedOrder, selectedOrderNo]);

  const visibleRefunds = orderDetail?.refunds.length ? orderDetail.refunds : fallbackRefunds;

  useEffect(() => {
    if (!selectedRefundNo) {
      setRefundDetail(null);
      setRefundDetailError(null);
      return;
    }

    let mounted = true;

    const load = async () => {
      setRefundDetailLoading(true);
      setRefundDetailError(null);
      setRefundDetail(null);

      try {
        const detail = await serviceDeskService.getRefundDetail(selectedRefundNo);
        if (mounted) {
          setRefundDetail(detail);
        }
      } catch (error) {
        if (mounted) {
          setRefundDetail(
            visibleRefunds.find((item) => item.refundNo === selectedRefundNo) ?? null
          );
          setRefundDetailError(error instanceof Error ? error.message : '退款详情接口暂不可用，已回退到列表数据。');
        }
      } finally {
        if (mounted) {
          setRefundDetailLoading(false);
        }
      }
    };

    void load();

    return () => {
      mounted = false;
    };
  }, [selectedRefundNo, visibleRefunds]);

  const handleRequestUploadPolicy = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    clearFeedback();
    setUploadSubmitting(true);

    try {
      const policy = await fileService.getUploadPolicy({
        fileName: uploadForm.fileName,
        size: Number(uploadForm.size),
        mimeType: uploadForm.mimeType,
        bizType: 'chat_attachment'
      });

      setUploadPolicy(policy);
      setSuccessMessage('已生成退款附件上传凭据。');
    } catch (error) {
      setPageError(error instanceof Error ? error.message : '申请上传凭据失败');
    } finally {
      setUploadSubmitting(false);
    }
  };

  const handleCompleteMockUpload = async () => {
    if (!uploadPolicy || !isMock) {
      return;
    }

    clearFeedback();
    setUploadCompleting(true);

    try {
      const file = await fileService.completeUpload({
        fileId: uploadPolicy.fileId,
        objectKey: uploadPolicy.objectKey,
        checksum: 'mock-checksum',
        size: Number(uploadForm.size)
      });

      const attachment = buildChatAttachmentFromFileRecord(file);

      setAvailableAttachments((previous) => upsertChatAttachment(previous, attachment));
      setSuccessMessage('退款附件已完成模拟上传。');
    } catch (error) {
      setPageError(error instanceof Error ? error.message : '模拟上传失败');
    } finally {
      setUploadCompleting(false);
    }
  };

  const handleRemoveAttachment = (fileId: string) => {
    setAvailableAttachments((previous) => previous.filter((item) => item.fileId !== fileId));
  };

  const handleCreateRefund = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedOrder) {
      setPageError('请先选择一笔订单。');
      return;
    }

    clearFeedback();
    setRefundSubmitting(true);

    try {
      const refund = await serviceDeskService.createRefund({
        orderNo: selectedOrder.orderNo,
        amount: refundForm.amount || selectedOrder.amount,
        reason: refundForm.reason.trim(),
        attachments: availableAttachments
      });

      await loadWorkspace();
      setSelectedOrderNo(selectedOrder.orderNo);
      setSelectedRefundNo(refund.refundNo);
      setRefundForm((previous) => ({
        ...previous,
        amount: selectedOrder.amount
      }));
      setSuccessMessage(`退款申请 ${refund.refundNo} 已提交，并已刷新订单详情与退款列表。`);
    } catch (error) {
      setPageError(error instanceof Error ? error.message : '提交退款申请失败');
    } finally {
      setRefundSubmitting(false);
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="Orders Workspace"
        title="订单中心"
        description="按规范补齐订单列表、详情面板、退款申请与退款详情联动，让用户侧可直接对齐 `/orders/*` 与 `/refunds/*`。"
        actions={
          <div className="page-header__actions">
            <Link className="button button--ghost" to="/billing">
              返回账单中心
            </Link>
            <Link className="button button--primary" to="/service-desk">
              打开综合服务台
            </Link>
          </div>
        }
      />

      {pageError ? <div className="error-banner">{pageError}</div> : null}
      {!pageError && unavailableWorkspaceDomains.length ? (
        <div className="error-banner">
          部分订单工作区数据暂不可用，当前以下分区加载失败：
          <strong>{` ${unavailableWorkspaceDomains.join(' / ')}`}</strong>
          {workspaceRetryAfterHint ? ` ${workspaceRetryAfterHint}` : ''}
        </div>
      ) : null}
      {successMessage ? <div className="success-banner">{successMessage}</div> : null}

      <div className="grid grid--3">
        <StatCard label="订单总数" value={loading ? '--' : String(workspace.orders.length)} hint="与 `/api/v1/orders` 列表保持一致。" />
        <StatCard
          label="可退款订单"
          value={loading ? '--' : String(workspace.orders.filter((item) => item.eligibleForRefund).length)}
          hint="用于退款入口的前端准入提示。"
        />
        <StatCard label="退款申请" value={loading ? '--' : String(workspace.refunds.length)} hint="支持联动退款详情与时间线。" />
      </div>

      <div className="grid grid--2 orders-page__layout">
        <div className="stack">
          <div className="card filters filters--inline">
            <label className="field field--compact">
              <span>关键词</span>
              <input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="搜索订单号 / 产品名" />
            </label>
            <label className="field field--compact">
              <span>退款状态</span>
              <select value={eligibility} onChange={(event) => setEligibility(event.target.value as typeof eligibility)}>
                <option value="all">全部订单</option>
                <option value="refundable">可退款</option>
                <option value="locked">不可退款</option>
              </select>
            </label>
          </div>

          <div className="card stack">
            <div className="orders-page__section-header">
              <div>
                <h3>订单列表</h3>
                <p className="muted">关闭右侧详情面板不会影响当前筛选条件与列表状态。</p>
              </div>
              <Badge tone={isMock ? 'warning' : 'info'}>{isMock ? 'Mock 明细' : 'Live API / 回退'}</Badge>
            </div>

            {loading ? (
              <p className="muted">正在加载订单列表...</p>
            ) : filteredOrders.length ? (
              <div className="table-wrapper">
                <table>
                  <thead>
                    <tr>
                      <th>订单号</th>
                      <th>产品</th>
                      <th>状态</th>
                      <th>金额</th>
                      <th>创建时间</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredOrders.map((order) => (
                      <tr key={order.orderNo} className={order.orderNo === selectedOrderNo ? 'table-row--active' : ''}>
                        <td>{order.orderNo}</td>
                        <td>{order.productType}</td>
                        <td>
                          <Badge tone={order.eligibleForRefund ? 'success' : 'neutral'}>{orderStatusLabel(order.status)}</Badge>
                        </td>
                        <td>{formatCurrency(order.amount)}</td>
                        <td>{formatDateTime(order.createdAt)}</td>
                        <td>
                          <button
                            type="button"
                            className="button button--ghost"
                            onClick={() => {
                              setSelectedOrderNo(order.orderNo);
                              setDetailOpen(true);
                              clearFeedback();
                            }}
                          >
                            查看详情
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="empty-state">
                <h3>暂无匹配订单</h3>
                <p className="muted">可调整筛选条件，或前往账单页查看近期消费。</p>
              </div>
            )}
          </div>
        </div>

        <div className="stack">
          <div className="card stack">
            <div className="orders-page__section-header">
              <div>
                <h3>订单详情抽屉</h3>
                <p className="muted">对齐 `/api/v1/orders/{'{order_no}'}`；若接口未就绪，则回退到列表级基础信息。</p>
              </div>
              <button
                type="button"
                className="button button--ghost"
                onClick={() => setDetailOpen((previous) => !previous)}
                disabled={!selectedOrderNo}
              >
                {detailOpen ? '关闭详情' : '打开详情'}
              </button>
            </div>

            {!selectedOrderNo ? (
              <p className="muted">请选择一笔订单查看详情。</p>
            ) : !detailOpen ? (
              <p className="muted">详情抽屉已关闭，列表筛选仍然保留。</p>
            ) : detailLoading && !orderDetail ? (
              <p className="muted">正在加载订单详情...</p>
            ) : orderDetail ? (
              <div className="stack stack--sm">
                {detailError ? <div className="warning-banner">{detailError}</div> : null}
                <div className="info-pair">
                  <span>订单号</span>
                  <code className="mono">{orderDetail.order.orderNo}</code>
                </div>
                <div className="info-pair">
                  <span>产品</span>
                  <span>{orderDetail.order.productType}</span>
                </div>
                <div className="info-pair">
                  <span>状态</span>
                  <Badge tone={orderDetail.order.eligibleForRefund ? 'success' : 'neutral'}>
                    {orderStatusLabel(orderDetail.order.status)}
                  </Badge>
                </div>
                <div className="info-pair">
                  <span>金额</span>
                  <strong>{formatCurrency(orderDetail.order.amount)}</strong>
                </div>
                <div className="info-pair">
                  <span>地域</span>
                  <span>{orderDetail.region ?? '--'}</span>
                </div>
                <div className="info-pair">
                  <span>实例 / 套餐</span>
                  <span>{orderDetail.instanceName ?? '--'}</span>
                </div>
                <div className="info-pair">
                  <span>计费方式</span>
                  <span>{orderDetail.billingMode ?? '--'}</span>
                </div>
                <div className="info-pair">
                  <span>服务周期</span>
                  <span>{orderDetail.servicePeriod ?? '--'}</span>
                </div>
                <div className="info-pair">
                  <span>支付时间</span>
                  <span>{orderDetail.payTime ? formatDateTime(orderDetail.payTime) : '--'}</span>
                </div>
                {orderDetail.configurationSummary.length ? (
                  <div className="stack stack--sm">
                    <strong>配置摘要</strong>
                    <ul className="feature-list">
                      {orderDetail.configurationSummary.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </div>
            ) : (
              <p className="muted">订单详情暂不可用。</p>
            )}
          </div>

          <form className="card stack" onSubmit={handleRequestUploadPolicy}>
            <div className="orders-page__section-header">
              <div>
                <h3>退款附件准备</h3>
                <p className="muted">先申请上传凭据，再把已完成上传的附件挂到退款表单上。</p>
              </div>
              <Badge tone={isMock ? 'warning' : 'info'}>{isMock ? '支持模拟 complete' : '需真实对象存储上传'}</Badge>
            </div>
            <label className="field field--compact">
              <span>文件名</span>
              <input
                value={uploadForm.fileName}
                onChange={(event) => setUploadForm((previous) => ({ ...previous, fileName: event.target.value }))}
              />
            </label>
            <div className="grid grid--2">
              <label className="field field--compact">
                <span>大小（bytes）</span>
                <input
                  value={uploadForm.size}
                  onChange={(event) => setUploadForm((previous) => ({ ...previous, size: event.target.value }))}
                />
              </label>
              <label className="field field--compact">
                <span>MIME</span>
                <input
                  value={uploadForm.mimeType}
                  onChange={(event) => setUploadForm((previous) => ({ ...previous, mimeType: event.target.value }))}
                />
              </label>
            </div>
            <button type="submit" className="button button--ghost" disabled={uploadSubmitting}>
              {uploadSubmitting ? '生成中...' : '申请上传凭据'}
            </button>

            {uploadPolicy ? (
              <div className="card stack stack--sm orders-page__upload-policy">
                <div className="info-pair">
                  <span>file_id</span>
                  <code className="mono">{uploadPolicy.fileId}</code>
                </div>
                <div className="info-pair">
                  <span>object_key</span>
                  <code className="mono">{uploadPolicy.objectKey}</code>
                </div>
                <div className="info-pair">
                  <span>过期时间</span>
                  <span>{formatDateTime(uploadPolicy.expireAt)}</span>
                </div>
                {isMock ? (
                  <button type="button" className="button button--primary" onClick={() => void handleCompleteMockUpload()} disabled={uploadCompleting}>
                    {uploadCompleting ? '处理中...' : '完成模拟上传'}
                  </button>
                ) : (
                  <p className="muted">Live 模式下请先把文件上传到对象存储，再调用后端 complete 接口。</p>
                )}
              </div>
            ) : null}

            {availableAttachments.length ? (
              <div className="stack stack--sm">
                <strong>已准备附件</strong>
                {availableAttachments.map((item) => (
                  <div key={item.fileId} className="list-row">
                    <span>{item.fileName}</span>
                    <div className="page-header__actions">
                      <span className="muted">{Math.ceil(item.size / 1024)} KB</span>
                      <button type="button" className="button button--ghost" onClick={() => handleRemoveAttachment(item.fileId)}>
                        移除
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="muted">当前未挂载退款附件。</p>
            )}
          </form>

          <div className="card stack">
            <div className="orders-page__section-header">
              <div>
                <h3>退款申请</h3>
                <p className="muted">提交成功后会立即刷新当前订单详情与退款列表。</p>
              </div>
              {selectedOrder ? (
                <Badge tone={selectedOrder.eligibleForRefund ? 'success' : 'warning'}>
                  {selectedOrder.eligibleForRefund ? '当前可退款' : '当前不可退款'}
                </Badge>
              ) : null}
            </div>

            {selectedOrder ? (
              <form className="stack" onSubmit={handleCreateRefund}>
                <div className="info-pair">
                  <span>当前订单</span>
                  <code className="mono">{selectedOrder.orderNo}</code>
                </div>
                <label className="field">
                  <span>退款金额</span>
                  <input
                    value={refundForm.amount}
                    onChange={(event) => setRefundForm((previous) => ({ ...previous, amount: event.target.value }))}
                    placeholder="例如 29.00"
                  />
                </label>
                <label className="field">
                  <span>退款原因</span>
                  <textarea
                    rows={4}
                    value={refundForm.reason}
                    onChange={(event) => setRefundForm((previous) => ({ ...previous, reason: event.target.value }))}
                  />
                </label>
                <p className="muted">本次提交将附带 {availableAttachments.length} 个已准备附件。</p>
                <button
                  type="submit"
                  className="button button--primary"
                  disabled={refundSubmitting || !selectedOrder.eligibleForRefund}
                >
                  {refundSubmitting ? '提交中...' : '提交退款申请'}
                </button>
              </form>
            ) : (
              <p className="muted">请先从左侧选择一笔订单。</p>
            )}
          </div>

          <div className="card stack">
            <div className="orders-page__section-header">
              <div>
                <h3>退款记录</h3>
                <p className="muted">点击记录时优先读取 `/api/v1/refunds/{'{refund_no}'}`，失败时回退到列表数据。</p>
              </div>
              <Badge tone="info">{visibleRefunds.length} 条</Badge>
            </div>

            {visibleRefunds.length ? (
              visibleRefunds.map((refund) => (
                <button
                  key={refund.refundNo}
                  type="button"
                  className={`task-card task-card--button${refund.refundNo === selectedRefundNo ? ' task-card--active' : ''}`}
                  onClick={() => setSelectedRefundNo(refund.refundNo)}
                >
                  <div className="list-row">
                    <strong>{refund.refundNo}</strong>
                    <Badge tone={refund.status === 'completed' ? 'success' : refund.status === 'rejected' ? 'danger' : 'warning'}>
                      {refundStatusLabel(refund.status)}
                    </Badge>
                  </div>
                  <div className="list-row muted">
                    <span>{formatCurrency(refund.requestedAmount, refund.currency)}</span>
                    <span>{formatDateTime(refund.createdAt)}</span>
                  </div>
                </button>
              ))
            ) : (
              <p className="muted">当前订单暂无退款记录。</p>
            )}

            {refundDetailLoading ? <p className="muted">正在加载退款详情...</p> : null}
            {refundDetailError ? <div className="warning-banner">{refundDetailError}</div> : null}
            {refundDetail ? (
              <div className="card stack stack--sm orders-page__refund-detail">
                <div className="info-pair">
                  <span>退款单号</span>
                  <code className="mono">{refundDetail.refundNo}</code>
                </div>
                <div className="info-pair">
                  <span>订单号</span>
                  <code className="mono">{refundDetail.orderNo}</code>
                </div>
                <div className="info-pair">
                  <span>申请金额</span>
                  <strong>{formatCurrency(refundDetail.requestedAmount, refundDetail.currency)}</strong>
                </div>
                <div className="info-pair">
                  <span>状态</span>
                  <span>{refundStatusLabel(refundDetail.status)}</span>
                </div>
                <div className="stack stack--sm">
                  <strong>时间线</strong>
                  {refundDetail.timeline.length ? (
                    refundDetail.timeline.map((item, index) => (
                      <div key={`${refundDetail.refundNo}-${index}`} className="timeline-item">
                        <div className="timeline-item__dot" />
                        <div>
                          <strong>{refundStatusLabel(item.status)}</strong>
                          <p className="muted">{item.note}</p>
                          <small className="muted">
                            {item.operatorType} · {formatDateTime(item.at)}
                          </small>
                        </div>
                      </div>
                    ))
                  ) : (
                    <p className="muted">暂无退款时间线。</p>
                  )}
                </div>
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </>
  );
}
