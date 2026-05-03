import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft, AlertCircle, CloudUpload, FileText } from "lucide-react";
import { PageContainer } from "@/components/layout/PageContainer";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card, CardHeader } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { Loading } from "@/components/ui/Empty";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { businessApis } from "@/lib/sdk";
import { formatMoney } from "@/lib/format";
import { notifyError, notifySuccess } from "@/lib/errors";

const REASONS = [
  { value: "service_unusable", label: "服务无法正常使用" },
  { value: "billing_dispute", label: "账单金额有疑问" },
  { value: "duplicate_purchase", label: "重复购买" },
  { value: "product_mismatch", label: "实际功能与预期不符" },
  { value: "other", label: "其他" },
];

export default function RefundRequestPage() {
  const { orderNo } = useParams();
  const navigate = useNavigate();

  const orderQuery = useQuery({
    queryKey: ["orders", "detail", orderNo],
    enabled: !!orderNo,
    queryFn: () => businessApis.orders.getOrderDetail(orderNo!),
  });

  const [reason, setReason] = useState("service_unusable");
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");

  const refundMut = useMutation({
    mutationFn: () => businessApis.orders.createRefund({
      orderNo: orderNo!,
      amount,
      reason: note ? `${reason}: ${note}` : reason,
      attachments: [],
    }),
    onSuccess: (refund) => {
      notifySuccess("退款申请已提交");
      navigate(`/orders/refunds/${refund.refundNo}`);
    },
    onError: (e) => notifyError(e, "提交退款申请失败"),
  });

  if (orderQuery.isLoading) return <PageContainer><Loading /></PageContainer>;
  const d = orderQuery.data;
  if (!d) return null;

  return (
    <PageContainer size="narrow">
      <PageHeader
        title="退款申请"
        description="提交退款申请后，财务团队会在 1-3 个工作日内处理"
        breadcrumb={[{ label: "业务中心" }, { label: "我的订单", to: "/orders" }, { label: d.order.orderNo, to: `/orders/${d.order.orderNo}` }, { label: "退款申请" }]}
        extra={<Button variant="secondary" leftIcon={<ArrowLeft className="size-3.5" />} onClick={() => navigate(-1)}>返回</Button>}
      />

      <Card>
        <CardHeader title="订单信息" />
        <div className="grid grid-cols-2 gap-y-3 rounded-lg bg-slate-50 p-4 text-sm">
          <div className="text-slate-500">订单号</div>
          <div className="font-mono text-brand-600">{d.order.orderNo}</div>
          <div className="text-slate-500">产品</div>
          <div>{d.order.productType}</div>
          <div className="text-slate-500">订单金额</div>
          <div className="font-medium">{formatMoney(d.order.amount)}</div>
          <div className="text-slate-500">订单状态</div>
          <div><StatusBadge status={d.order.status} /></div>
        </div>
      </Card>

      <Card className="mt-5">
        <CardHeader title="退款申请详情" />
        <div className="space-y-4">
          <div>
            <label className="label">退款金额</label>
            <Input
              prefix={<span className="text-slate-500">¥</span>}
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder={`不超过订单金额 ${formatMoney(d.order.amount)}`}
              hint="请填写本次申请的退款金额，最多不超过订单金额"
            />
          </div>

          <div>
            <label className="label">退款原因</label>
            <div className="grid grid-cols-2 gap-2">
              {REASONS.map((r) => (
                <button
                  key={r.value}
                  type="button"
                  onClick={() => setReason(r.value)}
                  className={`rounded-lg border px-3 py-2 text-left text-sm transition ${
                    reason === r.value
                      ? "border-brand-500 bg-brand-50 text-brand-700"
                      : "border-slate-200 bg-white text-slate-700 hover:border-slate-300"
                  }`}
                >
                  {r.label}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="label">问题描述</label>
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={4}
              placeholder="请详细描述遇到的问题，便于团队快速处理（建议 50 字以上）"
              className="input min-h-[100px]"
            />
          </div>

          <div>
            <label className="label">凭证上传（可选）</label>
            <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50/40 px-6 py-8 text-center">
              <CloudUpload className="mx-auto mb-2 size-8 text-slate-400" />
              <div className="text-sm text-slate-600">点击上传或拖拽文件至此</div>
              <div className="mt-1 text-xs text-slate-400">支持 PNG / JPG / PDF，最多 5 个文件，单个不超过 10 MB</div>
            </div>
          </div>

          <div className="rounded-lg bg-warning-50 p-4 text-xs text-warning-600">
            <div className="mb-1 inline-flex items-center gap-1 font-medium"><AlertCircle className="size-3.5" />温馨提示</div>
            <ul className="ml-5 list-disc space-y-1">
              <li>提交后申请将进入财务审核流程，预计 1-3 个工作日处理完成</li>
              <li>退款金额会原路返回到您的支付账户</li>
              <li>不满足退款条件的申请会被驳回，请填写真实的退款原因</li>
            </ul>
          </div>

          <div className="flex justify-end gap-2 border-t border-slate-100 pt-4">
            <Button variant="secondary" onClick={() => navigate(-1)}>取消</Button>
            <Button
              loading={refundMut.isPending}
              disabled={!amount || Number(amount) <= 0}
              onClick={() => refundMut.mutate()}
              leftIcon={<FileText className="size-3.5" />}
            >
              提交退款申请
            </Button>
          </div>
        </div>
      </Card>
    </PageContainer>
  );
}
