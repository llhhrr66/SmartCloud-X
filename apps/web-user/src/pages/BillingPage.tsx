import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { billingService } from '../api/services/billing';
import { PageHeader } from '../components/PageHeader';
import { StatCard } from '../components/StatCard';
import { formatCurrency, formatDateTime } from '../lib/format';
import type { BillingDashboard } from '../types/domain';

const degradedDomainLabels: Record<string, string> = {
  summary: '账单汇总',
  details: '账单明细',
  invoices: '发票记录',
  orders: '订单列表',
  tickets: '相关工单'
};

export function BillingPage(): JSX.Element {
  const [dashboard, setDashboard] = useState<BillingDashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [pageError, setPageError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;

    const load = async () => {
      try {
        const data = await billingService.getDashboard();
        if (mounted) {
          setDashboard(data);
          setPageError(null);
        }
      } catch (error) {
        if (mounted) {
          setPageError(error instanceof Error ? error.message : '加载账单工作区失败');
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
  }, []);

  const hasRecords = Boolean(
    dashboard && (dashboard.details.length || dashboard.invoices.length || dashboard.orders.length || dashboard.tickets.length)
  );
  const failedDomainSet = new Set(dashboard?.loadState?.failedDomains ?? []);
  const degradedDomains = [...failedDomainSet].map((item) => degradedDomainLabels[item] ?? item);

  return (
    <>
      <PageHeader
        eyebrow="Billing Overview"
        title="账单结果页"
        description="展示账单总览、明细、发票、订单与售后入口，便于接入 Finance_Order_Agent 的结构化结果。"
        actions={
          <div className="page-header__actions">
            <Link className="button button--ghost" to="/orders">
              去订单中心
            </Link>
            <Link className="button button--ghost" to="/tickets">
              去工单中心
            </Link>
            <Link className="button button--primary" to="/chat">
              去聊天继续追问
            </Link>
          </div>
        }
      />

      {pageError ? <div className="error-banner">{pageError}</div> : null}
      {!pageError && dashboard?.loadState?.degraded ? (
        <div className="error-banner">
          部分账单数据暂不可用，当前已展示可成功加载的分区：
          <strong>{` ${degradedDomains.join(' / ')}`}</strong>
        </div>
      ) : null}

      <div className="grid grid--3">
        <StatCard
          label="本月总消费"
          value={loading || !dashboard || failedDomainSet.has('summary') ? '--' : formatCurrency(dashboard.summary.totalAmount)}
          hint="对应 billing/summary 接口。"
        />
        <StatCard
          label="发票记录"
          value={loading || !dashboard || failedDomainSet.has('invoices') ? '--' : String(dashboard.invoices.length)}
          hint="联动开票与发票查询。"
        />
        <StatCard
          label="相关工单"
          value={loading || !dashboard || failedDomainSet.has('tickets') ? '--' : String(dashboard.tickets.length)}
          hint="对接 ticket-service / 工单流程。"
        />
      </div>

      {!loading && !hasRecords && !dashboard?.loadState?.degraded ? (
        <div className="card empty-state">
          <h3>暂无账单数据</h3>
          <p className="muted">可从聊天页发起账单查询，或前往服务台创建退款/售后请求。</p>
          <div className="page-header__actions">
            <Link className="button button--primary" to="/chat">
              发起账单咨询
            </Link>
            <Link className="button button--ghost" to="/service-desk">
              打开服务台
            </Link>
          </div>
        </div>
      ) : null}

      <div className="grid grid--2">
        <div className="card stack">
          <h3>账单明细</h3>
          {dashboard?.details.length ? (
            <div className="table-wrapper">
              <table>
                <thead>
                  <tr>
                    <th>账单周期</th>
                    <th>产品</th>
                    <th>实例</th>
                    <th>金额</th>
                    <th>状态</th>
                  </tr>
                </thead>
                <tbody>
                  {dashboard.details.map((item) => (
                    <tr key={item.statementNo}>
                      <td>{item.billingCycle}</td>
                      <td>{item.productType}</td>
                      <td>{item.instanceName}</td>
                      <td>{formatCurrency(item.amount)}</td>
                      <td>{item.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="muted">
              {loading ? '加载中...' : failedDomainSet.has('details') ? '账单明细接口暂不可用。' : '暂无账单明细。'}
            </p>
          )}
        </div>

        <div className="card stack">
          <h3>发票 / 订单 / 工单</h3>
          <div className="stack stack--sm">
            <strong>发票</strong>
            {dashboard?.invoices.length ? (
              dashboard.invoices.map((item) => (
                <div key={item.invoiceNo} className="list-row">
                  <span>{item.invoiceNo}</span>
                  <span>{item.status}</span>
                  <span>{formatCurrency(item.amount)}</span>
                </div>
              ))
            ) : (
              <p className="muted">
                {loading ? '加载中...' : failedDomainSet.has('invoices') ? '发票接口暂不可用。' : '暂无发票记录。'}
              </p>
            )}
          </div>
          <div className="stack stack--sm">
            <strong>订单</strong>
            {dashboard?.orders.length ? (
              dashboard.orders.map((item) => (
                <div key={item.orderNo} className="list-row">
                  <span>{item.productType}</span>
                  <span>{item.status}</span>
                  <span>{formatDateTime(item.createdAt)}</span>
                </div>
              ))
            ) : (
              <p className="muted">
                {loading ? '加载中...' : failedDomainSet.has('orders') ? '订单接口暂不可用。' : '暂无订单记录。'}
              </p>
            )}
          </div>
          <div className="stack stack--sm">
            <strong>工单</strong>
            {dashboard?.tickets.length ? (
              dashboard.tickets.map((item) => (
                <div key={item.ticketNo} className="list-row">
                  <span>{item.subject}</span>
                  <span>{item.status}</span>
                  <span>{formatDateTime(item.updatedAt)}</span>
                </div>
              ))
            ) : (
              <p className="muted">
                {loading ? '加载中...' : failedDomainSet.has('tickets') ? '工单接口暂不可用。' : '暂无工单记录。'}
              </p>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
