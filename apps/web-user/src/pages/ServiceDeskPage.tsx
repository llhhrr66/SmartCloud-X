import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { fileService } from '../api/services/files';
import { serviceDeskService } from '../api/services/serviceDesk';
import { useAuth } from '../auth/AuthContext';
import { Badge } from '../components/Badge';
import { PageHeader } from '../components/PageHeader';
import { StatCard } from '../components/StatCard';
import {
  formatCurrency,
  formatDateTime,
  formatRetryAfterHint,
  icpApplicationStatusLabel,
  refundStatusLabel,
  ticketPriorityLabel
} from '../lib/format';
import { hasPermission } from '../lib/permissions';
import {
  applyCreatedTicketToWorkspace,
  applyIcpApplicationToWorkspace,
  applyRefundToWorkspace,
  applyTicketReplyToDetail,
  applyTicketReplyToWorkspace,
  buildChatAttachmentFromFileRecord,
  buildIcpMaterialFromFileRecord,
  isKnownIcpMaterialType,
  isKnownTicketCategory,
  isKnownTicketPriority,
  knownIcpMaterialTypes,
  knownTicketCategories,
  knownTicketPriorities,
  resolveSharedLoadStateRetryAfterMs,
  selectSharedLoadStateDomains,
  upsertChatAttachment,
  upsertIcpMaterial
} from '../shared-sdk';
import type { KnownIcpMaterialType, KnownTicketCategory } from '../shared-sdk';
import type {
  ChatAttachment,
  CreateIcpApplicationRequest,
  CreateRefundRequest,
  CreateTicketRequest,
  IcpMaterialCheckResult,
  IcpMaterialItem,
  ReplyTicketRequest,
  ServiceWorkspaceData,
  TicketDetail,
  UploadPolicy,
  UploadPolicyRequest
} from '../types/domain';

export type ServiceDeskPageMode = 'workspace' | 'tickets' | 'icp';

interface ServiceDeskPageProps {
  mode?: ServiceDeskPageMode;
}

const emptyWorkspace: ServiceWorkspaceData = {
  orders: [],
  refunds: [],
  tickets: [],
  icpApplications: []
};

const materialTypeLabels: Record<KnownIcpMaterialType, string> = {
  business_license: '营业执照',
  domain_certificate: '域名证书',
  website_responsible_id: '负责人身份证',
  personal_id: '个人身份证'
};

const ticketCategoryLabels: Record<KnownTicketCategory, string> = {
  technical_support: '技术支持',
  billing: '账单',
  order: '订单',
  icp: '备案'
};

const uploadBizTypeLabels: Record<'chat_attachment' | 'icp_material', string> = {
  chat_attachment: '通用附件',
  icp_material: 'ICP 材料'
};

const uploadBizTypesByMode: Record<ServiceDeskPageMode, Array<'chat_attachment' | 'icp_material'>> = {
  workspace: ['chat_attachment', 'icp_material'],
  tickets: ['chat_attachment'],
  icp: ['icp_material']
};

const workspaceFailureLabels: Record<'orders' | 'refunds' | 'tickets' | 'icp', string> = {
  orders: '订单列表',
  refunds: '退款记录',
  tickets: '工单列表',
  icp: 'ICP备案申请'
};

const visibleFailureDomainsByMode: Record<ServiceDeskPageMode, ReadonlyArray<keyof typeof workspaceFailureLabels>> = {
  workspace: ['orders', 'refunds', 'tickets', 'icp'],
  tickets: ['tickets'],
  icp: ['icp']
};
const icpWorkspaceDomains = ['icp'] as const;

const initialTicketForm: Omit<CreateTicketRequest, 'attachments'> = {
  subject: 'GPU 实例挂盘异常',
  content: '实例启动后未识别到新挂载的数据盘，请协助排查。',
  priority: 'high',
  category: 'technical_support'
};

const initialRefundForm: Omit<CreateRefundRequest, 'attachments'> = {
  orderNo: '',
  reason: '活动套餐不再需要，申请退回未使用部分。',
  amount: '29.00'
};

const initialIcpForm: CreateIcpApplicationRequest = {
  subjectType: 'enterprise',
  domain: 'llm-demo.smartcloud.local',
  websiteName: 'SmartCloud 模型体验站',
  contacts: ['李雷 138****0001'],
  materials: []
};

const pageCopy: Record<ServiceDeskPageMode, { eyebrow: string; title: string; description: string }> = {
  workspace: {
    eyebrow: 'Service Workspace',
    title: '服务台',
    description: '补齐订单、退款、工单、备案与附件凭据流程的用户侧 baseline，方便和业务工具服务做真实联调。'
  },
  tickets: {
    eyebrow: 'Ticket Center',
    title: '工单中心',
    description: '按主规范拆出独立工单路由，聚焦附件准备、工单提交、工单详情与补充回复。'
  },
  icp: {
    eyebrow: 'ICP Workspace',
    title: 'ICP备案',
    description: '按主规范拆出独立 ICP 路由，聚焦材料上传、预检查与申请跟踪。'
  }
};

function createInitialUploadForm(mode: ServiceDeskPageMode): {
  fileName: string;
  size: string;
  mimeType: string;
  bizType: UploadPolicyRequest['bizType'];
  materialType: KnownIcpMaterialType;
} {
  if (mode === 'icp') {
    return {
      fileName: 'business-license.pdf',
      size: '245760',
      mimeType: 'application/pdf',
      bizType: 'icp_material',
      materialType: 'business_license'
    };
  }

  return {
    fileName: 'support-screenshot.png',
    size: '102400',
    mimeType: 'image/png',
    bizType: 'chat_attachment',
    materialType: 'business_license'
  };
}

export function ServiceDeskPage({ mode = 'workspace' }: ServiceDeskPageProps): JSX.Element {
  const { isMock, session } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const [workspace, setWorkspace] = useState<ServiceWorkspaceData>(emptyWorkspace);
  const [loading, setLoading] = useState(true);
  const [pageError, setPageError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [ticketForm, setTicketForm] = useState(initialTicketForm);
  const [refundForm, setRefundForm] = useState(initialRefundForm);
  const [icpForm, setIcpForm] = useState(initialIcpForm);
  const [contactInput, setContactInput] = useState(initialIcpForm.contacts.join('\n'));
  const [availableAttachments, setAvailableAttachments] = useState<ChatAttachment[]>([]);
  const [icpMaterials, setIcpMaterials] = useState<IcpMaterialItem[]>([]);
  const [materialCheck, setMaterialCheck] = useState<IcpMaterialCheckResult | null>(null);
  const [uploadPolicy, setUploadPolicy] = useState<UploadPolicy | null>(null);
  const [uploadForm, setUploadForm] = useState(() => createInitialUploadForm(mode));
  const [ticketSubmitting, setTicketSubmitting] = useState(false);
  const [refundSubmitting, setRefundSubmitting] = useState(false);
  const [icpChecking, setIcpChecking] = useState(false);
  const [icpSubmitting, setIcpSubmitting] = useState(false);
  const [uploadSubmitting, setUploadSubmitting] = useState(false);
  const [uploadCompleting, setUploadCompleting] = useState(false);
  const [selectedTicketNo, setSelectedTicketNo] = useState<string | null>(null);
  const [selectedTicketDetail, setSelectedTicketDetail] = useState<TicketDetail | null>(null);
  const [ticketDetailLoading, setTicketDetailLoading] = useState(false);
  const [ticketDetailError, setTicketDetailError] = useState<string | null>(null);
  const [replyForm, setReplyForm] = useState<Omit<ReplyTicketRequest, 'attachments'>>({
    content: ''
  });
  const [replySubmitting, setReplySubmitting] = useState(false);
  const [ticketPrefillNotice, setTicketPrefillNotice] = useState<string | null>(null);
  const [appliedTicketPrefillKey, setAppliedTicketPrefillKey] = useState<string | null>(null);

  const isTicketMode = mode === 'tickets';
  const showUpload = true;
  const showTickets = mode === 'workspace' || mode === 'tickets';
  const showRefunds = mode === 'workspace';
  const showIcp = mode === 'workspace' || mode === 'icp';
  const allowedUploadBizTypes = uploadBizTypesByMode[mode];
  const canWriteTickets = hasPermission(session, 'user:ticket.write');
  const canWriteIcp = hasPermission(session, 'user:icp.write');
  const showIcpMaterialList = mode !== 'tickets';
  const uploadTargetLabel = uploadForm.bizType === 'icp_material' ? 'ICP 备案材料' : '工单 / 退款附件';
  const visibleWorkspaceDomains = visibleFailureDomainsByMode[mode];
  const degradedWorkspaceDomainKeys = selectSharedLoadStateDomains(
    workspace.loadState,
    visibleWorkspaceDomains
  );
  const fallbackWorkspaceDomainKeys = selectSharedLoadStateDomains(
    workspace.loadState,
    visibleWorkspaceDomains,
    'fallback'
  );
  const icpFallbackDomainKeys = selectSharedLoadStateDomains(
    workspace.loadState,
    icpWorkspaceDomains,
    'fallback'
  );
  const unavailableWorkspaceDomains = degradedWorkspaceDomainKeys.map(
    (item) => workspaceFailureLabels[item]
  );
  const fallbackWorkspaceDomains = fallbackWorkspaceDomainKeys.map(
    (item) => workspaceFailureLabels[item]
  );
  const usesIcpHistoryFallback = icpFallbackDomainKeys.includes('icp');
  const workspaceRetryAfterHint = formatRetryAfterHint(
    resolveSharedLoadStateRetryAfterMs(workspace.loadState, degradedWorkspaceDomainKeys)
  );
  const icpFallbackRetryAfterHint = formatRetryAfterHint(
    resolveSharedLoadStateRetryAfterMs(workspace.loadState, icpFallbackDomainKeys)
  );

  useEffect(() => {
    const nextBizType = allowedUploadBizTypes[0];
    setUploadForm((previous) =>
      allowedUploadBizTypes.includes(previous.bizType as 'chat_attachment' | 'icp_material')
        ? previous
        : {
            ...previous,
            bizType: nextBizType
          }
    );
  }, [allowedUploadBizTypes]);

  useEffect(() => {
    let mounted = true;

    const load = async () => {
      try {
        const data = await serviceDeskService.getWorkspace();
        if (!mounted) {
          return;
        }

        setWorkspace(data);
      } catch (error) {
        if (mounted) {
          setPageError(error instanceof Error ? error.message : '加载服务台数据失败');
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

  useEffect(() => {
    if (!refundForm.orderNo && workspace.orders.length) {
      setRefundForm((previous) => ({
        ...previous,
        orderNo: workspace.orders[0].orderNo,
        amount: workspace.orders[0].amount
      }));
    }
  }, [refundForm.orderNo, workspace.orders]);

  const ticketPrefillKey = useMemo(
    () =>
      ['subject', 'content', 'category', 'priority', 'prefill_notice']
        .map((key) => `${key}=${searchParams.get(key) ?? ''}`)
        .join('&'),
    [searchParams]
  );

  useEffect(() => {
    const subject = searchParams.get('subject');
    const content = searchParams.get('content');
    const category = searchParams.get('category');
    const priority = searchParams.get('priority');
    const prefillNotice = searchParams.get('prefill_notice');

    if (!subject && !content && !category && !priority && !prefillNotice) {
      if (ticketPrefillNotice !== null || appliedTicketPrefillKey !== null) {
        setTicketPrefillNotice(null);
        setAppliedTicketPrefillKey(null);
      }
      return;
    }

    if (ticketPrefillKey === appliedTicketPrefillKey) {
      return;
    }

    setTicketForm((previous) => ({
      subject: subject?.trim() || previous.subject,
      content: content?.trim() || previous.content,
      category: isKnownTicketCategory(category) ? category : previous.category,
      priority: isKnownTicketPriority(priority) ? priority : previous.priority
    }));
    setTicketPrefillNotice(prefillNotice?.trim() || '已从聊天页带入人工协助草稿，可直接补充细节后提交工单。');
    setAppliedTicketPrefillKey(ticketPrefillKey);
  }, [appliedTicketPrefillKey, searchParams, ticketPrefillKey, ticketPrefillNotice]);

  const selectedOrder = useMemo(
    () => workspace.orders.find((item) => item.orderNo === refundForm.orderNo),
    [refundForm.orderNo, workspace.orders]
  );

  const hasTicketPrefill = useMemo(
    () => ['subject', 'content', 'category', 'priority', 'prefill_notice'].some((key) => searchParams.has(key)),
    [searchParams]
  );

  useEffect(() => {
    if (!isTicketMode) {
      setSelectedTicketNo(null);
      setSelectedTicketDetail(null);
      setTicketDetailError(null);
      return;
    }

    if (!workspace.tickets.length) {
      setSelectedTicketNo(null);
      setSelectedTicketDetail(null);
      setTicketDetailError(null);
      return;
    }

    setSelectedTicketNo((previous) =>
      previous && workspace.tickets.some((item) => item.ticketNo === previous) ? previous : workspace.tickets[0].ticketNo
    );
  }, [isTicketMode, workspace.tickets]);

  useEffect(() => {
    if (!isTicketMode || !selectedTicketNo) {
      setSelectedTicketDetail(null);
      return;
    }

    let mounted = true;

    const loadDetail = async () => {
      setTicketDetailLoading(true);
      setTicketDetailError(null);
      setSelectedTicketDetail(null);

      try {
        const detail = await serviceDeskService.getTicketDetail(selectedTicketNo);
        if (mounted) {
          setSelectedTicketDetail(detail);
        }
      } catch (error) {
        if (mounted) {
          setSelectedTicketDetail(null);
          setTicketDetailError(error instanceof Error ? error.message : '加载工单详情失败');
        }
      } finally {
        if (mounted) {
          setTicketDetailLoading(false);
        }
      }
    };

    void loadDetail();

    return () => {
      mounted = false;
    };
  }, [isTicketMode, selectedTicketNo]);

  const clearFeedback = () => {
    setPageError(null);
    setSuccessMessage(null);
  };

  const handleRequestUploadPolicy = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    clearFeedback();
    setUploadSubmitting(true);

    try {
      const policy = await fileService.getUploadPolicy({
        fileName: uploadForm.fileName,
        size: Number(uploadForm.size),
        mimeType: uploadForm.mimeType,
        bizType: uploadForm.bizType
      });

      setUploadPolicy(policy);
      setSuccessMessage(
        isMock
          ? '已生成上传凭据。Mock 模式下可继续完成模拟上传。'
          : '已生成上传凭据。请先将文件上传到对象存储，再回到这里完成上传登记。'
      );
    } catch (error) {
      setPageError(error instanceof Error ? error.message : '申请上传凭据失败');
    } finally {
      setUploadSubmitting(false);
    }
  };

  const handleCompleteUploadRegistration = async () => {
    if (!uploadPolicy) {
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

      if (uploadForm.bizType === 'icp_material') {
        const material = buildIcpMaterialFromFileRecord(file, uploadForm.materialType);

        setIcpMaterials((previous) => upsertIcpMaterial(previous, material));
        setMaterialCheck(null);
        setSuccessMessage('上传登记已完成，材料已加入 ICP 备案表单。');
      } else {
        setAvailableAttachments((previous) => upsertChatAttachment(previous, attachment));
        setSuccessMessage('上传登记已完成，附件已加入工单 / 退款 / 工单回复表单。');
      }
    } catch (error) {
      setPageError(error instanceof Error ? error.message : '完成上传登记失败');
    } finally {
      setUploadCompleting(false);
    }
  };

  const handleRemoveAttachment = (fileId: string) => {
    setAvailableAttachments((previous) => previous.filter((item) => item.fileId !== fileId));
  };

  const handleRemoveMaterial = (fileId?: string, fileName?: string) => {
    setIcpMaterials((previous) =>
      previous.filter((item) =>
        fileId ? item.fileId !== fileId : !(item.fileName === fileName && !item.fileId)
      )
    );
    setMaterialCheck(null);
  };

  const handleCreateTicket = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canWriteTickets) {
      setPageError('当前账号仅开通工单只读能力，暂不可创建新工单。');
      return;
    }

    clearFeedback();
    setTicketSubmitting(true);

    try {
      const ticket = await serviceDeskService.createTicket({
        ...ticketForm,
        attachments: availableAttachments
      });

      setWorkspace((previous) => applyCreatedTicketToWorkspace(previous, ticket));
      setSelectedTicketNo(ticket.ticketNo);
      setSelectedTicketDetail(null);
      setReplyForm({
        content: ''
      });
      if (hasTicketPrefill) {
        const nextSearchParams = new URLSearchParams(searchParams);
        ['subject', 'content', 'category', 'priority', 'prefill_notice'].forEach((key) => nextSearchParams.delete(key));
        setSearchParams(nextSearchParams, { replace: true });
        setTicketPrefillNotice(null);
        setAppliedTicketPrefillKey(null);
      }
      setSuccessMessage('工单 ' + ticket.ticketNo + ' 已创建。');
    } catch (error) {
      setPageError(error instanceof Error ? error.message : '创建工单失败');
    } finally {
      setTicketSubmitting(false);
    }
  };

  const handleClearTicketPrefill = () => {
    const nextSearchParams = new URLSearchParams(searchParams);
    ['subject', 'content', 'category', 'priority', 'prefill_notice'].forEach((key) => nextSearchParams.delete(key));
    setSearchParams(nextSearchParams, { replace: true });
    setTicketPrefillNotice(null);
    setAppliedTicketPrefillKey(null);
  };

  const handleReplyTicket = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canWriteTickets) {
      setTicketDetailError('当前账号仅开通工单只读能力，暂不可追加回复。');
      return;
    }

    if (!selectedTicketNo) {
      setTicketDetailError('请先选择一条工单。');
      return;
    }

    const content = replyForm.content.trim();
    if (!content) {
      setTicketDetailError('请输入补充说明后再提交回复。');
      return;
    }

    clearFeedback();
    setTicketDetailError(null);
    setReplySubmitting(true);

    try {
      const reply = await serviceDeskService.replyTicket(selectedTicketNo, {
        content,
        attachments: availableAttachments
      });

      setSelectedTicketDetail((previous) => applyTicketReplyToDetail(previous, selectedTicketNo, reply));
      setWorkspace((previous) => applyTicketReplyToWorkspace(previous, selectedTicketNo, reply));
      setReplyForm({
        content: ''
      });
      setSuccessMessage('已为工单 ' + selectedTicketNo + ' 追加回复。');
    } catch (error) {
      setTicketDetailError(error instanceof Error ? error.message : '提交工单回复失败');
    } finally {
      setReplySubmitting(false);
    }
  };

  const handleCreateRefund = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    clearFeedback();
    setRefundSubmitting(true);

    try {
      const refund = await serviceDeskService.createRefund({
        ...refundForm,
        attachments: availableAttachments
      });

      setWorkspace((previous) => applyRefundToWorkspace(previous, refund));
      setSuccessMessage('退款申请 ' + refund.refundNo + ' 已提交。');
    } catch (error) {
      setPageError(error instanceof Error ? error.message : '创建退款申请失败');
    } finally {
      setRefundSubmitting(false);
    }
  };

  const handleCheckMaterials = async () => {
    if (!canWriteIcp) {
      setPageError('当前账号仅开通 ICP 只读能力，暂不可执行材料预检查。');
      return;
    }

    clearFeedback();
    setIcpChecking(true);

    try {
      const result = await serviceDeskService.checkIcpMaterials({
        subjectType: icpForm.subjectType,
        materials: icpMaterials
      });

      setMaterialCheck(result);
      if (result.passed) {
        setSuccessMessage('材料预检查通过，可以继续提交备案申请。');
      } else {
        setPageError('材料预检查未通过，请补齐后再提交。');
      }
    } catch (error) {
      setPageError(error instanceof Error ? error.message : '材料预检查失败');
    } finally {
      setIcpChecking(false);
    }
  };

  const handleCreateIcpApplication = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canWriteIcp) {
      setPageError('当前账号仅开通 ICP 只读能力，暂不可提交备案申请。');
      return;
    }

    clearFeedback();
    setIcpSubmitting(true);

    try {
      const contacts = contactInput
        .split(/\n+/)
        .map((item) => item.trim())
        .filter(Boolean);
      const currentCheck =
        materialCheck ??
        (await serviceDeskService.checkIcpMaterials({
          subjectType: icpForm.subjectType,
          materials: icpMaterials
        }));

      setMaterialCheck(currentCheck);
      if (!currentCheck.passed) {
        throw new Error('材料预检查未通过，请先补齐必需材料。');
      }

      const application = await serviceDeskService.createIcpApplication({
        ...icpForm,
        contacts,
        materials: icpMaterials
      });

      setWorkspace((previous) => applyIcpApplicationToWorkspace(previous, application));
      setSuccessMessage('备案申请 ' + application.applicationNo + ' 已提交。');
    } catch (error) {
      setPageError(error instanceof Error ? error.message : '提交备案申请失败');
    } finally {
      setIcpSubmitting(false);
    }
  };

  const copy = pageCopy[mode];

  const uploadSection = (
    <form className="card stack" onSubmit={handleRequestUploadPolicy}>
      <h3>附件 / 材料准备</h3>
      {allowedUploadBizTypes.length > 1 ? (
        <label className="field field--compact">
          <span>用途</span>
          <select
            value={uploadForm.bizType}
            onChange={(event) =>
              setUploadForm((previous) => ({
                ...previous,
                bizType: event.target.value as UploadPolicyRequest['bizType']
              }))
            }
          >
            {allowedUploadBizTypes.map((bizType) => (
              <option key={bizType} value={bizType}>
                {uploadBizTypeLabels[bizType]}
              </option>
            ))}
          </select>
        </label>
      ) : (
        <div className="card service-note">
          <span className="muted">当前用途</span>
          <strong>{uploadBizTypeLabels[allowedUploadBizTypes[0]]}</strong>
        </div>
      )}
      <label className="field">
        <span>文件名</span>
        <input value={uploadForm.fileName} onChange={(event) => setUploadForm((previous) => ({ ...previous, fileName: event.target.value }))} />
      </label>
      <div className="grid grid--2">
        <label className="field field--compact">
          <span>大小（bytes）</span>
          <input value={uploadForm.size} onChange={(event) => setUploadForm((previous) => ({ ...previous, size: event.target.value }))} />
        </label>
        <label className="field field--compact">
          <span>MIME</span>
          <input value={uploadForm.mimeType} onChange={(event) => setUploadForm((previous) => ({ ...previous, mimeType: event.target.value }))} />
        </label>
      </div>
      {uploadForm.bizType === 'icp_material' ? (
        <label className="field field--compact">
          <span>材料类型</span>
          <select
            value={uploadForm.materialType}
            onChange={(event) =>
              setUploadForm((previous) => ({
                ...previous,
                materialType: isKnownIcpMaterialType(event.target.value)
                  ? event.target.value
                  : previous.materialType
              }))
            }
          >
            {knownIcpMaterialTypes.map((value) => (
              <option key={value} value={value}>
                {materialTypeLabels[value]}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      <p className="muted">当前将为 {uploadTargetLabel} 申请上传凭据，避免把票据截图误当作 ICP 材料提交。</p>
      <button type="submit" className="button button--primary" disabled={uploadSubmitting}>
        {uploadSubmitting ? '申请中...' : '申请上传凭据'}
      </button>

      {uploadPolicy ? (
        <div className="task-card stack stack--sm">
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
          {!isMock ? <p className="muted">Live 模式下请先将文件上传到对象存储，再点击下方按钮完成登记。</p> : null}
          <button
            type="button"
            className="button button--ghost"
            onClick={() => void handleCompleteUploadRegistration()}
            disabled={uploadCompleting}
          >
            {uploadCompleting
              ? '处理中...'
              : isMock
                ? `完成 Mock 上传并加入${uploadTargetLabel}`
                : `完成上传登记并加入 ${uploadTargetLabel}`}
          </button>
        </div>
      ) : null}

      <div className="stack stack--sm">
        <strong>当前已就绪附件</strong>
        {availableAttachments.length ? (
          availableAttachments.map((item) => (
            <div key={item.fileId} className="list-row">
              <span>{item.fileName}</span>
              <span>{item.mimeType}</span>
              <span>{item.size} bytes</span>
              <button type="button" className="button button--ghost" onClick={() => handleRemoveAttachment(item.fileId)}>
                移除
              </button>
            </div>
          ))
        ) : (
          <p className="muted">尚未准备通用附件。这里的文件会附带到工单、退款和工单补充回复。</p>
        )}
      </div>

      {showIcpMaterialList ? (
        <div className="stack stack--sm">
          <strong>当前已准备 ICP 材料</strong>
          {icpMaterials.length ? (
            icpMaterials.map((item) => (
              <div key={(item.fileId ?? item.fileName) + '-' + item.type} className="list-row">
                <span>{item.fileName}</span>
                <span>{materialTypeLabels[item.type as KnownIcpMaterialType] ?? item.type}</span>
                <Badge tone={item.status === 'verified' ? 'success' : 'info'}>{item.status}</Badge>
                <button
                  type="button"
                  className="button button--ghost"
                  onClick={() => handleRemoveMaterial(item.fileId, item.fileName)}
                >
                  移除
                </button>
              </div>
            ))
          ) : (
            <p className="muted">尚未准备 ICP 材料。营业执照、域名证书等文件应单独登记到这里。</p>
          )}
        </div>
      ) : null}
    </form>
  );

  const ticketSection = (
    <div className="card stack">
      <h3>工单工作台</h3>
      {!canWriteTickets ? (
        <div className="warning-banner">当前账号缺少 `user:ticket.write`，可查看工单与时间线，但创建/回复操作已禁用。</div>
      ) : null}
      {ticketPrefillNotice ? (
        <div className="service-note card">
          <div className="task-card__header">
            <div>
              <strong>已导入聊天协助草稿</strong>
              <p className="muted">{ticketPrefillNotice}</p>
            </div>
            <button type="button" className="button button--ghost" onClick={handleClearTicketPrefill}>
              清除导入
            </button>
          </div>
        </div>
      ) : null}
      <form className="stack" onSubmit={handleCreateTicket}>
        <label className="field">
          <span>主题</span>
          <input value={ticketForm.subject} onChange={(event) => setTicketForm((previous) => ({ ...previous, subject: event.target.value }))} />
        </label>
        <label className="field">
          <span>内容</span>
          <textarea value={ticketForm.content} onChange={(event) => setTicketForm((previous) => ({ ...previous, content: event.target.value }))} rows={4} />
        </label>
        <div className="grid grid--2">
          <label className="field field--compact">
            <span>优先级</span>
            <select
              value={ticketForm.priority}
              onChange={(event) =>
                setTicketForm((previous) => ({
                  ...previous,
                  priority: isKnownTicketPriority(event.target.value)
                    ? event.target.value
                    : previous.priority
                }))
              }
            >
              {knownTicketPriorities.map((priority) => (
                <option key={priority} value={priority}>
                  {ticketPriorityLabel(priority)}
                </option>
              ))}
            </select>
          </label>
          <label className="field field--compact">
            <span>分类</span>
            <select
              value={ticketForm.category}
              onChange={(event) =>
                setTicketForm((previous) => ({
                  ...previous,
                  category: isKnownTicketCategory(event.target.value)
                    ? event.target.value
                    : previous.category
                }))
              }
            >
              {knownTicketCategories.map((category) => (
                <option key={category} value={category}>
                  {ticketCategoryLabels[category]}
                </option>
              ))}
            </select>
          </label>
        </div>
        <p className="muted">本次提交将附带 {availableAttachments.length} 个已准备附件。</p>
        <button type="submit" className="button button--primary" disabled={ticketSubmitting || !canWriteTickets}>
          {!canWriteTickets ? '缺少写权限' : ticketSubmitting ? '提交中...' : '创建工单'}
        </button>
      </form>

      <div className="stack stack--sm">
        <strong>最近工单</strong>
        {workspace.tickets.length ? (
          workspace.tickets.map((ticket) => (
            <button
              key={ticket.ticketNo}
              type="button"
              className={
                'task-card stack stack--sm ticket-list-item' +
                (ticket.ticketNo === selectedTicketNo ? ' ticket-list-item--active' : '')
              }
              onClick={() => {
                setSelectedTicketNo(ticket.ticketNo);
                setSelectedTicketDetail(null);
                setTicketDetailError(null);
              }}
            >
              <div className="task-card__header">
                <strong>{ticket.subject}</strong>
                <Badge tone={ticket.status === 'open' ? 'warning' : 'info'}>{ticket.status}</Badge>
              </div>
              <div className="list-row">
                <span>{ticket.category}</span>
                <span>{ticket.priority ? ticketPriorityLabel(ticket.priority) : '-'}</span>
                <span>{formatDateTime(ticket.updatedAt)}</span>
              </div>
              {ticket.content ? <p className="muted">{ticket.content}</p> : null}
              {isTicketMode ? <span className="muted">点击查看详情与回复时间线</span> : null}
            </button>
          ))
        ) : (
          <p className="muted">暂无工单记录。</p>
        )}
      </div>

      {isTicketMode ? (
        <div className="ticket-detail-panel card stack">
          <div className="task-card__header">
            <div>
              <strong>工单详情与回复</strong>
              <p className="muted">对齐用户侧工单详情与补充回复接口的闭环体验。</p>
            </div>
            {selectedTicketDetail ? (
              <Badge tone={selectedTicketDetail.ticket.status === 'resolved' ? 'success' : 'info'}>
                {selectedTicketDetail.ticket.status}
              </Badge>
            ) : null}
          </div>

          {ticketDetailError ? <div className="error-banner">{ticketDetailError}</div> : null}

          {ticketDetailLoading ? (
            <p className="muted">正在加载工单详情...</p>
          ) : selectedTicketDetail ? (
            <>
              <div className="grid grid--2">
                <div className="service-note card">
                  <span className="muted">工单号 / SLA</span>
                  <strong>{selectedTicketDetail.ticket.ticketNo}</strong>
                  <span className="muted">
                    {selectedTicketDetail.ticket.slaMinutes ? `${selectedTicketDetail.ticket.slaMinutes} 分钟` : '待分配'}
                  </span>
                </div>
                <div className="service-note card">
                  <span className="muted">分类 / 优先级</span>
                  <strong>{selectedTicketDetail.ticket.category}</strong>
                  <span className="muted">
                    {selectedTicketDetail.ticket.priority ? ticketPriorityLabel(selectedTicketDetail.ticket.priority) : '未设置'}
                  </span>
                </div>
              </div>

              <div className="task-card stack stack--sm">
                <strong>问题描述</strong>
                <p className="muted">{selectedTicketDetail.ticket.content ?? '暂无工单描述。'}</p>
                <div className="list-row">
                  <span>创建时间：{formatDateTime(selectedTicketDetail.ticket.createdAt ?? selectedTicketDetail.ticket.updatedAt)}</span>
                  <span>最近更新：{formatDateTime(selectedTicketDetail.ticket.updatedAt)}</span>
                </div>
                {selectedTicketDetail.ticket.attachments?.length ? (
                  <div className="stack stack--sm">
                    <span className="muted">问题附件</span>
                    {selectedTicketDetail.ticket.attachments.map((item) => (
                      <div key={item.fileId} className="list-row">
                        <span>{item.fileName}</span>
                        <span>{item.mimeType}</span>
                        <span>{item.size} bytes</span>
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>

              <div className="stack stack--sm">
                <strong>回复时间线</strong>
                {selectedTicketDetail.replies.length ? (
                  selectedTicketDetail.replies.map((reply) => (
                    <div key={reply.replyNo} className="ticket-reply stack stack--sm">
                      <div className="task-card__header">
                        <strong>{reply.operatorType === 'user' ? '用户补充' : reply.operatorType === 'support' ? '客服回复' : '系统通知'}</strong>
                        <span className="muted">{formatDateTime(reply.createdAt)}</span>
                      </div>
                      <p className="muted">{reply.content}</p>
                      {reply.attachments?.length ? (
                        <div className="stack stack--sm">
                          {reply.attachments.map((item) => (
                            <div key={reply.replyNo + '-' + item.fileId} className="list-row">
                              <span>{item.fileName}</span>
                              <span>{item.mimeType}</span>
                              <span>{item.size} bytes</span>
                            </div>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  ))
                ) : (
                  <p className="muted">暂无额外回复，您可以先补充实例 ID、报错时间等关键信息。</p>
                )}
              </div>

              <form className="task-card stack" onSubmit={handleReplyTicket}>
                <strong>补充回复</strong>
                <p className="muted">本次回复将附带当前已准备附件 {availableAttachments.length} 个。</p>
                <label className="field">
                  <span>回复内容</span>
                  <textarea
                    value={replyForm.content}
                    onChange={(event) =>
                      setReplyForm({
                        content: event.target.value
                      })
                    }
                    rows={4}
                    placeholder="补充实例 ID、报错时间、截图说明或希望客服继续协助的内容。"
                  />
                </label>
                {availableAttachments.length ? (
                  <div className="stack stack--sm">
                    <span className="muted">本次将附带以下附件</span>
                    {availableAttachments.map((item) => (
                      <div key={'reply-' + item.fileId} className="list-row">
                        <span>{item.fileName}</span>
                        <span>{item.mimeType}</span>
                        <span>{item.size} bytes</span>
                      </div>
                    ))}
                  </div>
                ) : null}
                <button
                  type="submit"
                  className="button button--primary"
                  disabled={
                    replySubmitting ||
                    !canWriteTickets ||
                    selectedTicketDetail.ticket.status === 'resolved' ||
                    selectedTicketDetail.ticket.status === 'closed'
                  }
                >
                  {!canWriteTickets ? '缺少写权限' : replySubmitting ? '提交中...' : '提交补充回复'}
                </button>
                {selectedTicketDetail.ticket.status === 'resolved' || selectedTicketDetail.ticket.status === 'closed' ? (
                  <p className="muted">该工单已完结，无法继续追加回复。</p>
                ) : !canWriteTickets ? (
                  <p className="muted">当前账号缺少 `user:ticket.write`，请联系管理员开通后再继续提交。</p>
                ) : null}
              </form>
            </>
          ) : (
            <p className="muted">选择一条工单后可查看详情与回复时间线。</p>
          )}
        </div>
      ) : null}
    </div>
  );

  const refundSection = (
    <div className="card stack">
      <h3>订单与退款</h3>
      <div className="stack stack--sm">
        <strong>订单列表</strong>
        {workspace.orders.length ? (
          workspace.orders.map((order) => (
            <div key={order.orderNo} className="task-card stack stack--sm">
              <div className="task-card__header">
                <strong>{order.productType}</strong>
                <Badge tone={order.eligibleForRefund ? 'success' : 'neutral'}>{order.eligibleForRefund ? '可退款' : '不可退款'}</Badge>
              </div>
              <div className="list-row">
                <span>{order.orderNo}</span>
                <span>{order.status}</span>
                <span>{formatCurrency(order.amount)}</span>
              </div>
              <p className="muted">下单时间：{formatDateTime(order.createdAt)}</p>
            </div>
          ))
        ) : (
          <p className="muted">暂无订单。</p>
        )}
      </div>

      <form className="stack" onSubmit={handleCreateRefund}>
        <strong>提交退款申请</strong>
        <label className="field field--compact">
          <span>订单</span>
          <select
            value={refundForm.orderNo}
            onChange={(event) => {
              const nextOrder = workspace.orders.find((item) => item.orderNo === event.target.value);
              setRefundForm((previous) => ({
                ...previous,
                orderNo: event.target.value,
                amount: nextOrder?.amount ?? previous.amount
              }));
            }}
          >
            {workspace.orders.map((order) => (
              <option key={order.orderNo} value={order.orderNo}>
                {order.orderNo} · {order.productType}
              </option>
            ))}
          </select>
        </label>
        <div className="grid grid--2">
          <label className="field field--compact">
            <span>退款金额</span>
            <input value={refundForm.amount} onChange={(event) => setRefundForm((previous) => ({ ...previous, amount: event.target.value }))} />
          </label>
          <div className="card service-note">
            <span className="muted">订单状态</span>
            <strong>{selectedOrder?.status ?? '-'}</strong>
          </div>
        </div>
        <label className="field">
          <span>退款原因</span>
          <textarea value={refundForm.reason} onChange={(event) => setRefundForm((previous) => ({ ...previous, reason: event.target.value }))} rows={3} />
        </label>
        <button type="submit" className="button button--primary" disabled={refundSubmitting || !refundForm.orderNo}>
          {refundSubmitting ? '提交中...' : '提交退款申请'}
        </button>
      </form>

      <div className="stack stack--sm">
        <strong>退款历史</strong>
        {workspace.refunds.length ? (
          workspace.refunds.map((refund) => (
            <div key={refund.refundNo} className="task-card stack stack--sm">
              <div className="task-card__header">
                <strong>{refund.refundNo}</strong>
                <Badge tone={refund.status === 'completed' ? 'success' : refund.status === 'rejected' ? 'danger' : 'warning'}>
                  {refundStatusLabel(refund.status)}
                </Badge>
              </div>
              <div className="list-row">
                <span>{refund.orderNo}</span>
                <span>{formatCurrency(refund.requestedAmount, refund.currency)}</span>
                <span>{formatDateTime(refund.createdAt)}</span>
              </div>
            </div>
          ))
        ) : (
          <p className="muted">暂无退款记录。</p>
        )}
      </div>
    </div>
  );

  const icpSection = (
    <div className="card stack">
      <h3>ICP备案工作台</h3>
      {!canWriteIcp ? (
        <div className="warning-banner">当前账号缺少 `user:icp.write`，可查看申请历史，但材料预检与提交操作已禁用。</div>
      ) : null}
      <form className="stack" onSubmit={handleCreateIcpApplication}>
        <div className="grid grid--2">
          <label className="field field--compact">
            <span>主体类型</span>
            <select
              value={icpForm.subjectType}
              onChange={(event) =>
                setIcpForm((previous) => ({
                  ...previous,
                  subjectType: event.target.value as CreateIcpApplicationRequest['subjectType']
                }))
              }
            >
              <option value="enterprise">Enterprise</option>
              <option value="individual">Individual</option>
            </select>
          </label>
          <label className="field field--compact">
            <span>域名</span>
            <input value={icpForm.domain} onChange={(event) => setIcpForm((previous) => ({ ...previous, domain: event.target.value }))} />
          </label>
        </div>
        <label className="field">
          <span>网站名称</span>
          <input value={icpForm.websiteName} onChange={(event) => setIcpForm((previous) => ({ ...previous, websiteName: event.target.value }))} />
        </label>
        <label className="field">
          <span>联系人（每行一位）</span>
          <textarea value={contactInput} onChange={(event) => setContactInput(event.target.value)} rows={3} />
        </label>

        <div className="stack stack--sm">
          <strong>已准备材料</strong>
          {icpMaterials.length ? (
            icpMaterials.map((item) => (
              <div key={(item.fileId ?? item.fileName) + '-' + item.type} className="list-row">
                <span>{item.fileName}</span>
                <span>{materialTypeLabels[item.type as KnownIcpMaterialType] ?? item.type}</span>
                <Badge tone={item.status === 'verified' ? 'success' : 'info'}>{item.status}</Badge>
                <button
                  type="button"
                  className="button button--ghost"
                  onClick={() => handleRemoveMaterial(item.fileId, item.fileName)}
                >
                  移除
                </button>
              </div>
            ))
          ) : (
            <p className="muted">先在左侧准备营业执照、域名证书等材料。</p>
          )}
        </div>

        <div className="page-header__actions">
          <button
            type="button"
            className="button button--ghost"
            onClick={() => void handleCheckMaterials()}
            disabled={icpChecking || !canWriteIcp}
          >
            {!canWriteIcp ? '缺少写权限' : icpChecking ? '检查中...' : '材料预检查'}
          </button>
          <button
            type="submit"
            className="button button--primary"
            disabled={icpSubmitting || !icpMaterials.length || !canWriteIcp}
          >
            {!canWriteIcp ? '缺少写权限' : icpSubmitting ? '提交中...' : '提交备案申请'}
          </button>
        </div>
      </form>

      {materialCheck ? (
        <div className="task-card stack stack--sm">
          <div className="task-card__header">
            <strong>预检查结果</strong>
            <Badge tone={materialCheck.passed ? 'success' : 'warning'}>{materialCheck.passed ? '通过' : '待补齐'}</Badge>
          </div>
          <p className="muted">必需材料：{materialCheck.requiredMaterials.join('、')}</p>
          {materialCheck.issues.length ? (
            materialCheck.issues.map((issue) => (
              <div key={issue.field + '-' + issue.message} className="error-banner">
                {issue.message}
              </div>
            ))
          ) : (
            <p className="muted">当前材料已满足最小提交要求。</p>
          )}
        </div>
      ) : null}

      <div className="stack stack--sm">
        <strong>申请历史</strong>
        {workspace.icpApplications.length ? (
          workspace.icpApplications.map((application) => (
            <div key={application.applicationNo} className="task-card stack stack--sm">
              <div className="task-card__header">
                <strong>{application.websiteName}</strong>
                <Badge tone={application.status === 'approved' ? 'success' : application.status === 'rejected' ? 'danger' : 'info'}>
                  {icpApplicationStatusLabel(application.status)}
                </Badge>
              </div>
              <div className="list-row">
                <span>{application.applicationNo}</span>
                <span>{application.currentStep}</span>
                <span>{formatDateTime(application.submittedAt ?? application.approvedAt ?? new Date().toISOString())}</span>
              </div>
              <p className="muted">{application.domain}</p>
            </div>
          ))
        ) : (
          <p className="muted">暂无备案申请记录。</p>
        )}
      </div>
    </div>
  );

  return (
    <>
      <PageHeader
        eyebrow={copy.eyebrow}
        title={copy.title}
        description={copy.description}
        actions={
          <div className="page-header__actions">
            {mode !== 'workspace' ? (
              <Link className="button button--ghost" to="/service-desk">
                返回综合服务台
              </Link>
            ) : null}
            {mode === 'tickets' ? (
              <Badge tone="info">详情 / 回复对齐 ticket-service</Badge>
            ) : !isMock && usesIcpHistoryFallback ? (
              <Badge tone="info">
                {`Live 模式下备案历史已回退到本地跟踪申请${icpFallbackRetryAfterHint ? `，${icpFallbackRetryAfterHint.replace(/。$/, '')}` : ''}`}
              </Badge>
            ) : null}
          </div>
        }
      />

      {pageError ? <div className="error-banner">{pageError}</div> : null}
      {!pageError && unavailableWorkspaceDomains.length ? (
        <div className="error-banner">
          部分服务台数据暂不可用，当前以下分区加载失败：
          <strong>{` ${unavailableWorkspaceDomains.join(' / ')}`}</strong>
          {workspaceRetryAfterHint ? ` ${workspaceRetryAfterHint}` : ''}
        </div>
      ) : null}
      {successMessage ? <div className="success-banner">{successMessage}</div> : null}

      <div className="card stack">
        <h3>专项入口</h3>
        <div className="quick-links">
          <Link className="quick-link" to="/service-desk">
            <strong>综合服务台</strong>
            <span>统一处理退款、工单、ICP 与附件流</span>
          </Link>
          <Link className="quick-link" to="/tickets">
            <strong>工单中心</strong>
            <span>聚焦附件准备、工单提交与最近售后记录</span>
          </Link>
          <Link className="quick-link" to="/icp">
            <strong>ICP备案</strong>
            <span>聚焦材料预检、备案提交与状态跟踪</span>
          </Link>
          <Link className="quick-link" to="/billing">
            <strong>账单与退款</strong>
            <span>查看消费明细并回到退款入口</span>
          </Link>
        </div>
      </div>

      <div className="grid grid--4">
        <StatCard label="可退款订单" value={loading ? '--' : String(workspace.orders.filter((item) => item.eligibleForRefund).length)} hint="基于订单列表与退款入口。" />
        <StatCard label="进行中工单" value={loading ? '--' : String(workspace.tickets.filter((item) => item.status !== 'closed').length)} hint="支撑技术支持/账单咨询提交。" />
        <StatCard label="退款记录" value={loading ? '--' : String(workspace.refunds.length)} hint="对齐 /api/v1/refunds 列表接口。" />
        <StatCard
          label="备案申请"
          value={loading ? '--' : String(workspace.icpApplications.length)}
          hint={usesIcpHistoryFallback ? '列表接口未就绪时回退到共享 ICP detail 跟踪。' : '优先使用共享 ICP 列表接口。'}
        />
      </div>

      {showUpload && showTickets ? <div className="grid grid--2">{uploadSection}{ticketSection}</div> : null}
      {showUpload && !showTickets && showIcp ? <div className="grid grid--2">{uploadSection}{icpSection}</div> : null}
      {showRefunds ? <div className="grid grid--2">{refundSection}{icpSection}</div> : null}
    </>
  );
}
