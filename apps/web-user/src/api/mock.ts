import { readJson, storageKeys, writeJson } from '../lib/storage';
import { buildConversationTitle, chunkText, createId, sleep } from '../lib/utils';
import type {
  AccountType,
  AuthCodeScene,
  AuthSession,
  BillingDashboard,
  CheckIcpMaterialsRequest,
  ChatCompletionRequest,
  ChatMessage,
  ChatStreamEvent,
  ChangePasswordRequest,
  Citation,
  ConversationSummary,
  CreateIcpApplicationRequest,
  CreatePosterTaskRequest,
  CreateRefundRequest,
  CreateResearchTaskRequest,
  CreateTicketRequest,
  CurrentUser,
  ForgotPasswordChallenge,
  ForgotPasswordChallengeRequest,
  IcpApplication,
  IcpMaterialCheckResult,
  MarketingCampaign,
  MarketingCopyRequest,
  MarketingCopyResult,
  LoginRequest,
  OrderDetail,
  OrderRecord,
  PaginatedResult,
  PosterTask,
  ReplyTicketRequest,
  RefundRecord,
  ResearchTask,
  ResetPasswordRequest,
  Scene,
  SendCodeRequest,
  SendCodeResponse,
  ServiceWorkspaceData,
  TicketDetail,
  TicketReply,
  SessionCancelResult,
  SessionCreateRequest,
  SessionListQuery,
  SessionRetryResult,
  TicketRecord,
  ToolCallRecord
} from '../types/domain';

interface MockAuthCode {
  scene: AuthCodeScene;
  account: string;
  accountType: AccountType;
  code: string;
  expireAt: string;
}

interface MockPasswordResetChallenge {
  challengeId: string;
  account: string;
  verificationCode: string;
  expireAt: string;
}

interface MockAuthState {
  accounts: {
    primaryEmail: string;
    primaryMobile: string;
    username: string;
    password: string;
  };
  pendingCodes: MockAuthCode[];
  passwordResetChallenges: MockPasswordResetChallenge[];
}

interface MockDatabase {
  auth: MockAuthState;
  user: CurrentUser;
  conversations: ConversationSummary[];
  messages: Record<string, ChatMessage[]>;
  billing: BillingDashboard;
  refunds: RefundRecord[];
  ticketReplies: Record<string, TicketReply[]>;
  icpApplications: IcpApplication[];
  researchTasks: ResearchTask[];
  campaigns: MarketingCampaign[];
  posterTasks: PosterTask[];
}

const defaultUser: CurrentUser = {
  userId: 'u_10001',
  tenantId: 'default',
  name: 'SmartCloud 用户',
  email: 'demo@smartcloud.local',
  mobile: '138****0001',
  locale: 'zh-CN',
  timeZone: 'Asia/Shanghai',
  permissions: [
    'user:chat.use',
    'user:billing.read',
    'user:order.read',
    'user:ticket.read',
    'user:ticket.write',
    'user:icp.read',
    'user:icp.write',
    'user:marketing.read',
    'user:marketing.write',
    'user:research.read',
    'user:research.write'
  ]
};

const sceneAgentMap: Record<Scene, string> = {
  customer_service: 'Orchestrator',
  billing: 'Finance_Order_Agent',
  technical_support: 'Product_Tech_Agent',
  icp: 'ICP_Service_Agent',
  marketing: 'Ops_Marketing_Agent',
  research: 'Deep_Research_Agent'
};

function normalizeAccount(value: string): string {
  return value.trim().toLowerCase();
}

function maskAccount(account: string, accountType: AccountType): string {
  const normalized = account.trim();

  if (accountType === 'email') {
    const [localPart, domain = 'example.com'] = normalized.split('@');
    const visible = localPart.slice(0, 1) || '*';
    return `${visible}***@${domain}`;
  }

  const compact = normalized.replace(/\D/g, '');
  if (compact.length < 7) {
    return '***';
  }

  return `${compact.slice(0, 3)}****${compact.slice(-4)}`;
}

function nowIso(): string {
  return new Date().toISOString();
}

function pruneAuthState(auth: MockAuthState): MockAuthState {
  const now = Date.now();

  return {
    ...auth,
    pendingCodes: auth.pendingCodes.filter((item) => new Date(item.expireAt).getTime() > now),
    passwordResetChallenges: auth.passwordResetChallenges.filter((item) => new Date(item.expireAt).getTime() > now)
  };
}

function matchesMockAccount(db: MockDatabase, account: string): boolean {
  const normalized = normalizeAccount(account);
  const candidates = [
    db.auth.accounts.primaryEmail,
    db.auth.accounts.primaryMobile,
    db.auth.accounts.username,
    db.user.email,
    db.user.mobile,
    db.user.name
  ];

  return candidates.some((item) => normalizeAccount(item) === normalized);
}

function findPendingCode(db: MockDatabase, scene: AuthCodeScene, account: string): MockAuthCode | undefined {
  const normalized = normalizeAccount(account);
  return [...db.auth.pendingCodes]
    .reverse()
    .find((item) => item.scene === scene && normalizeAccount(item.account) === normalized);
}

function ensureVerificationCode(
  db: MockDatabase,
  scene: AuthCodeScene,
  account: string,
  verificationCode: string
): void {
  const trimmedCode = verificationCode.trim();
  if (!trimmedCode) {
    throw new Error('请输入验证码');
  }

  const pending = findPendingCode(db, scene, account);
  const allowedCodes = new Set(['123456']);
  if (pending?.code) {
    allowedCodes.add(pending.code);
  }

  if (!allowedCodes.has(trimmedCode)) {
    throw new Error('验证码错误或已过期');
  }
}

function getConversationMessages(db: MockDatabase, conversationId: string): ChatMessage[] {
  return db.messages[conversationId] ?? [];
}

function persistDatabase(db: MockDatabase): void {
  writeJson(storageKeys.mockDatabase, db);
}

function readDatabase(): MockDatabase {
  const seeded = seedDatabase();
  const stored = readJson<Partial<MockDatabase>>(storageKeys.mockDatabase, seeded);
  const database: MockDatabase = {
    auth: pruneAuthState({
      ...seeded.auth,
      ...(stored.auth ?? {}),
      accounts: {
        ...seeded.auth.accounts,
        ...(stored.auth?.accounts ?? {})
      },
      pendingCodes: Array.isArray(stored.auth?.pendingCodes) ? stored.auth.pendingCodes : seeded.auth.pendingCodes,
      passwordResetChallenges: Array.isArray(stored.auth?.passwordResetChallenges)
        ? stored.auth.passwordResetChallenges
        : seeded.auth.passwordResetChallenges
    }),
    user: stored.user ?? seeded.user,
    conversations:
      Array.isArray(stored.conversations) && stored.conversations.length ? stored.conversations : seeded.conversations,
    messages: stored.messages ?? seeded.messages,
    billing: {
      ...seeded.billing,
      ...(stored.billing ?? {}),
      summary: {
        ...seeded.billing.summary,
        ...(stored.billing?.summary ?? {})
      },
      details: Array.isArray(stored.billing?.details) ? stored.billing.details : seeded.billing.details,
      invoices: Array.isArray(stored.billing?.invoices) ? stored.billing.invoices : seeded.billing.invoices,
      orders: Array.isArray(stored.billing?.orders) ? stored.billing.orders : seeded.billing.orders,
      tickets: Array.isArray(stored.billing?.tickets) ? stored.billing.tickets : seeded.billing.tickets
    },
    refunds: Array.isArray(stored.refunds) ? stored.refunds : seeded.refunds,
    ticketReplies: {
      ...seeded.ticketReplies,
      ...(stored.ticketReplies ?? {})
    },
    icpApplications: Array.isArray(stored.icpApplications) ? stored.icpApplications : seeded.icpApplications,
    researchTasks: Array.isArray(stored.researchTasks) ? stored.researchTasks : seeded.researchTasks,
    campaigns: Array.isArray(stored.campaigns) ? stored.campaigns : seeded.campaigns,
    posterTasks: Array.isArray(stored.posterTasks) ? stored.posterTasks : seeded.posterTasks
  };

  if (!database.conversations.length) {
    persistDatabase(seeded);
    return seeded;
  }

  return database;
}

function syncConversation(db: MockDatabase, conversationId: string, patch?: Partial<ConversationSummary>): void {
  const messages = getConversationMessages(db, conversationId);
  const lastMessage = messages.at(-1);

  db.conversations = db.conversations.map((item) => {
    if (item.conversationId !== conversationId) {
      return item;
    }

    return {
      ...item,
      messageCount: messages.length,
      updatedAt: patch?.updatedAt ?? lastMessage?.createdAt ?? item.updatedAt,
      lastMessageAt: patch?.lastMessageAt ?? lastMessage?.createdAt ?? item.lastMessageAt,
      summary: patch?.summary ?? lastMessage?.content ?? item.summary,
      currentAgent: patch?.currentAgent ?? item.currentAgent,
      title: patch?.title ?? item.title,
      status: patch?.status ?? item.status
    };
  });

  db.conversations.sort((left, right) => new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime());
}

function sortByRecent<T>(items: T[], pickValue: (item: T) => string | undefined): T[] {
  return [...items].sort(
    (left, right) => new Date(pickValue(right) ?? 0).getTime() - new Date(pickValue(left) ?? 0).getTime()
  );
}

function seedDatabase(): MockDatabase {
  const supportConversationId = 'conv_seed_support';
  const billingConversationId = 'conv_seed_billing';
  const researchTaskId = 'task_seed_research';
  const posterTaskId = 'poster_seed_gpu';
  const billingTicketNo = 'tic_202604_001';
  const supportTicketNo = 'tic_202604_002';

  const supportMessages: ChatMessage[] = [
    {
      id: 'm_support_1',
      messageId: 'msg_support_1',
      conversationId: supportConversationId,
      role: 'user',
      messageType: 'text',
      content: '我想部署一个 7B 模型，帮我推荐 GPU 规格。',
      createdAt: new Date(Date.now() - 1000 * 60 * 90).toISOString(),
      status: 'completed'
    },
    {
      id: 'm_support_2',
      messageId: 'msg_support_2',
      conversationId: supportConversationId,
      role: 'assistant',
      messageType: 'markdown',
      content:
        '建议优先考虑单卡 24GB 显存起步，并配合高性能系统盘、对象存储和稳定公网出口，后续可升级到多卡推理集群。',
      createdAt: new Date(Date.now() - 1000 * 60 * 88).toISOString(),
      agentName: 'Product_Tech_Agent',
      status: 'completed',
      citations: [
        {
          id: 'cite_support_gpu',
          title: 'GPU 实例选型指南',
          sourceType: 'knowledge_base',
          docId: 'doc_gpu_guide',
          chunkId: 'chunk_gpu_001'
        }
      ]
    }
  ];

  const billingMessages: ChatMessage[] = [
    {
      id: 'm_billing_1',
      messageId: 'msg_billing_1',
      conversationId: billingConversationId,
      role: 'user',
      messageType: 'text',
      content: '帮我看一下最近三个月的云服务器账单。',
      createdAt: new Date(Date.now() - 1000 * 60 * 55).toISOString(),
      status: 'completed'
    },
    {
      id: 'm_billing_2',
      messageId: 'msg_billing_2',
      conversationId: billingConversationId,
      role: 'assistant',
      messageType: 'markdown',
      content:
        '最近三个月账单总额为 932.50 元，其中云服务器 780.00 元，公网带宽 152.50 元。已为您整理到账单页明细。',
      createdAt: new Date(Date.now() - 1000 * 60 * 53).toISOString(),
      agentName: 'Finance_Order_Agent',
      status: 'completed',
      citations: [
        {
          id: 'cite_billing_rule',
          title: '账单说明',
          sourceType: 'knowledge_base',
          docId: 'doc_billing_001',
          chunkId: 'chunk_billing_001'
        }
      ],
      toolCalls: [
        {
          toolName: 'billing.query_statement',
          toolCallId: 'tc_seed_billing',
          status: 'success',
          latencyMs: 842,
          dataPreview: {
            totalAmount: '932.50',
            currency: 'CNY'
          }
        }
      ]
    }
  ];

  const seededTicketReplies: Record<string, TicketReply[]> = {
    [billingTicketNo]: [
      {
        replyNo: 'reply_202604_001',
        content: '已收到您的带宽峰值咨询，正在帮您核对计费策略与突发规则。',
        createdAt: new Date(Date.now() - 1000 * 60 * 58).toISOString(),
        operatorType: 'support',
        status: 'processing'
      },
      {
        replyNo: 'reply_202604_002',
        content: '初步确认计费按带宽峰值日粒度统计，建议补充波动时间段以便进一步核查。',
        createdAt: new Date(Date.now() - 1000 * 60 * 26).toISOString(),
        operatorType: 'support',
        status: 'processing'
      }
    ],
    [supportTicketNo]: [
      {
        replyNo: 'reply_202604_003',
        content: '已为您创建紧急工单，建议先提供实例 ID、挂载盘 ID 与最近一次操作时间。',
        createdAt: new Date(Date.now() - 1000 * 60 * 42).toISOString(),
        operatorType: 'system',
        status: 'open'
      }
    ]
  };

  return {
    auth: {
      accounts: {
        primaryEmail: 'demo@smartcloud.local',
        primaryMobile: '13800000001',
        username: 'demo-user',
        password: 'smartcloud-demo'
      },
      pendingCodes: [],
      passwordResetChallenges: []
    },
    user: defaultUser,
    conversations: [
      {
        conversationId: billingConversationId,
        title: '最近三个月账单汇总',
        scene: 'billing',
        status: 'active',
        createdAt: new Date(Date.now() - 1000 * 60 * 56).toISOString(),
        currentAgent: 'Finance_Order_Agent',
        updatedAt: billingMessages.at(-1)?.createdAt ?? nowIso(),
        lastMessageAt: billingMessages.at(-1)?.createdAt ?? nowIso(),
        summary: '返回了最近三个月账单总额与关键成本构成。',
        messageCount: billingMessages.length
      },
      {
        conversationId: supportConversationId,
        title: '7B 模型 GPU 部署建议',
        scene: 'technical_support',
        status: 'active',
        createdAt: new Date(Date.now() - 1000 * 60 * 91).toISOString(),
        currentAgent: 'Product_Tech_Agent',
        updatedAt: supportMessages.at(-1)?.createdAt ?? nowIso(),
        lastMessageAt: supportMessages.at(-1)?.createdAt ?? nowIso(),
        summary: '完成 GPU 规格与基础部署建议。',
        messageCount: supportMessages.length
      }
    ],
    messages: {
      [supportConversationId]: supportMessages,
      [billingConversationId]: billingMessages
    },
    ticketReplies: seededTicketReplies,
    billing: {
      summary: {
        totalAmount: '328.00',
        currency: 'CNY',
        range: 'this_month',
        topProducts: [
          { productType: '云服务器', amount: '300.00', ratio: 0.91 },
          { productType: '公网带宽', amount: '28.00', ratio: 0.09 }
        ],
        topInstances: [
          { instanceId: 'ins_gpu_cn2_01', instanceName: 'gpu-training-01', amount: '188.00' },
          { instanceId: 'ins_web_cn2_03', instanceName: 'web-frontend-03', amount: '82.00' }
        ]
      },
      details: [
        {
          statementNo: 'st_202604_001',
          billingCycle: '2026-04',
          productType: '云服务器',
          instanceId: 'ins_gpu_cn2_01',
          instanceName: 'gpu-training-01',
          amount: '188.00',
          status: 'settled'
        },
        {
          statementNo: 'st_202604_002',
          billingCycle: '2026-04',
          productType: '云服务器',
          instanceId: 'ins_web_cn2_03',
          instanceName: 'web-frontend-03',
          amount: '82.00',
          status: 'settled'
        },
        {
          statementNo: 'st_202604_003',
          billingCycle: '2026-04',
          productType: '公网带宽',
          instanceId: 'bandwidth_01',
          instanceName: '公网带宽包-01',
          amount: '28.00',
          status: 'settled'
        }
      ],
      invoices: [
        {
          invoiceNo: 'inv_202604_001',
          status: 'pending',
          amount: '328.00',
          billingCycle: '2026-04',
          title: 'SmartCloud-X 技术有限公司'
        }
      ],
      orders: [
        {
          orderNo: 'ord_202604_001',
          productType: 'GPU 云服务器',
          status: 'paid',
          amount: '599.00',
          createdAt: new Date(Date.now() - 1000 * 60 * 60 * 24 * 3).toISOString(),
          eligibleForRefund: true
        },
        {
          orderNo: 'ord_202604_002',
          productType: '对象存储套餐',
          status: 'paid',
          amount: '129.00',
          createdAt: new Date(Date.now() - 1000 * 60 * 60 * 24 * 9).toISOString(),
          eligibleForRefund: false
        }
      ],
      tickets: [
        {
          ticketNo: billingTicketNo,
          subject: '公网带宽峰值异常咨询',
          status: 'processing',
          category: 'billing',
          priority: 'high',
          content: '峰值带宽波动较大，想确认计费与突发策略。',
          createdAt: new Date(Date.now() - 1000 * 60 * 60 * 20).toISOString(),
          slaMinutes: 30,
          updatedAt: new Date(Date.now() - 1000 * 60 * 32).toISOString()
        },
        {
          ticketNo: supportTicketNo,
          subject: 'GPU 实例挂盘异常',
          status: 'open',
          category: 'technical_support',
          priority: 'urgent',
          content: '实例启动后未识别到新挂载的数据盘，需要排查。',
          createdAt: new Date(Date.now() - 1000 * 60 * 60 * 4).toISOString(),
          slaMinutes: 15,
          updatedAt: new Date(Date.now() - 1000 * 60 * 48).toISOString()
        }
      ]
    },
    refunds: [
      {
        refundNo: 'ref_202604_001',
        orderNo: 'ord_202604_002',
        status: 'completed',
        requestedAmount: '29.00',
        approvedAmount: '29.00',
        currency: 'CNY',
        createdAt: new Date(Date.now() - 1000 * 60 * 60 * 24 * 5).toISOString(),
        finishedAt: new Date(Date.now() - 1000 * 60 * 60 * 24 * 4).toISOString(),
        timeline: [
          {
            status: 'pending_review',
            at: new Date(Date.now() - 1000 * 60 * 60 * 24 * 5).toISOString(),
            operatorType: 'user',
            note: '提交退款申请'
          },
          {
            status: 'completed',
            at: new Date(Date.now() - 1000 * 60 * 60 * 24 * 4).toISOString(),
            operatorType: 'finance',
            note: '原路退回成功'
          }
        ]
      }
    ],
    icpApplications: [
      {
        applicationNo: 'ICP202604160001',
        status: 'reviewing',
        currentStep: 'province_review',
        domain: 'llm-demo.smartcloud.local',
        websiteName: 'SmartCloud 模型体验站',
        subjectType: 'enterprise',
        contacts: ['李雷 138****0001'],
        materials: [
          {
            fileId: 'file_icp_license',
            fileName: 'business-license.pdf',
            type: 'business_license',
            status: 'verified',
            required: true
          },
          {
            fileId: 'file_icp_domain',
            fileName: 'domain-certificate.pdf',
            type: 'domain_certificate',
            status: 'verified',
            required: true
          }
        ],
        submittedAt: new Date(Date.now() - 1000 * 60 * 60 * 26).toISOString()
      }
    ],
    researchTasks: [
      {
        taskId: researchTaskId,
        topic: 'LangGraph vs CrewAI vs AutoGen',
        scope: '面向生产客服编排的工程能力对比',
        depth: 'standard',
        outputFormat: 'markdown',
        status: 'completed',
        progress: 100,
        summary: '已生成对比框架，建议以 LangGraph 作为主编排底座。',
        createdAt: new Date(Date.now() - 1000 * 60 * 95).toISOString(),
        reportFileId: 'file_report_langgraph_compare',
        updatedAt: new Date(Date.now() - 1000 * 60 * 80).toISOString(),
        referenceUrls: ['https://docs.langchain.com/oss/python/langgraph/overview']
      }
    ],
    campaigns: [
      {
        campaignId: 'camp_gpu_spring',
        name: '算力焕新季',
        productType: 'GPU 云服务器',
        status: 'published',
        startAt: new Date(Date.now() - 1000 * 60 * 60 * 24 * 7).toISOString(),
        endAt: new Date(Date.now() + 1000 * 60 * 60 * 24 * 21).toISOString(),
        landingPageUrl: 'https://smartcloud.local/campaigns/gpu-spring',
        highlights: ['GPU 折扣', '推荐文案', '海报生成']
      },
      {
        campaignId: 'camp_ecs_growth',
        name: '云主机成长计划',
        productType: '云服务器',
        status: 'published',
        startAt: new Date(Date.now() - 1000 * 60 * 60 * 24 * 3).toISOString(),
        endAt: new Date(Date.now() + 1000 * 60 * 60 * 24 * 14).toISOString(),
        landingPageUrl: 'https://smartcloud.local/campaigns/ecs-growth',
        highlights: ['低门槛试用', '技术咨询', '推广链接']
      }
    ],
    posterTasks: [
      {
        taskId: posterTaskId,
        campaignId: 'camp_gpu_spring',
        campaignName: '算力焕新季',
        theme: '工业级算力促销',
        slogan: '部署大模型，从稳定算力开始',
        size: '1024x1536',
        status: 'completed',
        createdAt: new Date(Date.now() - 1000 * 60 * 28).toISOString(),
        estimatedSeconds: 18,
        imageUrl: 'https://dummyimage.com/512x768/0f172a/ffffff&text=GPU+Campaign',
        updatedAt: new Date(Date.now() - 1000 * 60 * 25).toISOString()
      }
    ]
  };
}

function buildAgent(scene: Scene, userInput: string): string {
  const normalized = userInput.toLowerCase();

  if (/(账单|发票|订单|退款)/.test(normalized)) {
    return 'Finance_Order_Agent';
  }

  if (/(备案|icp|域名|实名认证)/.test(normalized)) {
    return 'ICP_Service_Agent';
  }

  if (/(活动|海报|推广|营销)/.test(normalized)) {
    return 'Ops_Marketing_Agent';
  }

  if (/(研究|对比|调研|报告)/.test(normalized)) {
    return 'Deep_Research_Agent';
  }

  if (/(gpu|故障|部署|配置|实例|模型)/.test(normalized)) {
    return 'Product_Tech_Agent';
  }

  return sceneAgentMap[scene];
}

function buildReasoningSummary(scene: Scene, agent: string): string {
  if (agent === 'Finance_Order_Agent') {
    return '识别到用户诉求涉及账单/订单信息，准备调用 billing tool 汇总消费与发票状态。';
  }

  if (agent === 'ICP_Service_Agent') {
    return '识别到备案流程问题，优先检查材料清单、状态与常见驳回原因。';
  }

  if (agent === 'Ops_Marketing_Agent') {
    return '用户问题涉及营销推荐或海报生成，准备结合活动信息与推广素材输出建议。';
  }

  if (agent === 'Deep_Research_Agent') {
    return '需要生成研究结论，先整理技术对比维度，再汇总引用与输出格式。';
  }

  if (scene === 'customer_service') {
    return 'Orchestrator 完成意图识别，准备切换到专业 Agent 处理产品与技术支持问题。';
  }

  return '识别到技术支持类问题，准备调取产品文档与部署 SOP 做综合回答。';
}

function buildToolCall(scene: Scene, agent: string): ToolCallRecord | null {
  if (agent === 'Finance_Order_Agent' || scene === 'billing') {
    return {
      toolName: 'billing.query_statement',
      toolCallId: createId('tc'),
      status: 'running',
      arguments: {
        range: 'last_3_months',
        user_id: defaultUser.userId
      }
    };
  }

  if (agent === 'ICP_Service_Agent') {
    return {
      toolName: 'icp.materials.check',
      toolCallId: createId('tc'),
      status: 'running',
      arguments: {
        subject_type: 'enterprise'
      }
    };
  }

  if (agent === 'Ops_Marketing_Agent') {
    return {
      toolName: 'marketing.campaign.recommend',
      toolCallId: createId('tc'),
      status: 'running',
      arguments: {
        product_type: 'gpu'
      }
    };
  }

  return null;
}

function buildRetrieval(scene: Scene, userInput: string): ChatStreamEvent {
  const baseSource = {
    docId: `doc_${scene}`,
    chunkId: `chunk_${scene}_001`,
    score: 0.92
  };

  return {
    event: 'retrieval',
    data: {
      query: userInput,
      topK: 5,
      sources: [
        {
          ...baseSource,
          title: scene === 'billing' ? '账单说明' : scene === 'icp' ? 'ICP备案材料清单' : '产品与服务指南'
        }
      ]
    }
  };
}

function buildCitations(scene: Scene): Citation[] {
  return [
    {
      id: createId('cite'),
      title:
        scene === 'billing'
          ? '账单说明'
          : scene === 'icp'
            ? 'ICP备案材料清单'
            : scene === 'marketing'
              ? '营销活动配置说明'
              : scene === 'research'
                ? '研究报告模板'
                : '产品与技术支持知识库',
      sourceType: 'knowledge_base',
      docId: `doc_${scene}`,
      chunkId: `chunk_${scene}_001`
    }
  ];
}

function buildAnswer(scene: Scene, agent: string, userInput: string): string {
  if (agent === 'Finance_Order_Agent' || scene === 'billing') {
    return '结合当前账单工具结果，最近三个月总消费为 932.50 元，其中云服务器 780.00 元，公网带宽 152.50 元。建议您继续在账单页面查看实例级明细，并在开票前确认抬头信息。';
  }

  if (agent === 'ICP_Service_Agent') {
    return `针对“${userInput}”，建议先完成主体证件、域名证书与负责人联系方式的材料预检查，再进入正式备案流程；若已有申请号，可继续查询当前步骤与驳回原因。`;
  }

  if (agent === 'Ops_Marketing_Agent' || scene === 'marketing') {
    return '当前可优先推荐“算力焕新季”等活动，适合 GPU 与大模型部署场景。您可以继续生成推广文案、海报任务，并同步落地页链接给销售或渠道伙伴。';
  }

  if (agent === 'Deep_Research_Agent' || scene === 'research') {
    return '我已按研究任务模板整理技术对比脉络：如果目标是工业级生产编排，建议优先采用 LangGraph 作为核心工作流引擎，再按需要补充外部搜索与导出能力。';
  }

  if (scene === 'customer_service') {
    return `我已将问题路由到专业 Agent。针对“${userInput}”，建议先确认部署目标、地域、实例规格与网络策略，再结合产品文档与知识库输出配置建议。`;
  }

  return `针对“${userInput}”，推荐优先确认实例规格、网络与镜像策略，并参考部署 SOP 逐步完成初始化、监控与故障排查配置。`;
}

export async function mockLogin(input: LoginRequest): Promise<AuthSession> {
  const account = input.account.trim();
  if (!account) {
    throw new Error('请输入账号');
  }

  const db = readDatabase();
  if (!matchesMockAccount(db, account)) {
    throw new Error('账号不存在或未绑定');
  }

  if (input.loginType === 'password') {
    const password = input.password?.trim() ?? '';
    if (!password) {
      throw new Error('请输入密码');
    }

    if (password !== db.auth.accounts.password) {
      throw new Error('用户名或密码错误');
    }
  } else {
    ensureVerificationCode(db, 'login', account, input.verificationCode ?? '');
  }

  return {
    accessToken: createId('mock_access'),
    refreshToken: createId('mock_refresh'),
    expiresIn: 7_200,
    expiresAt: new Date(Date.now() + 7_200 * 1000).toISOString(),
    user: db.user
  };
}

export async function mockSendAuthCode(input: SendCodeRequest): Promise<SendCodeResponse> {
  const account = input.account.trim();
  if (!account) {
    throw new Error('请输入手机号或邮箱');
  }

  const db = readDatabase();
  if (!matchesMockAccount(db, account)) {
    throw new Error('账号不存在或未绑定');
  }

  const nextCode: MockAuthCode = {
    scene: input.scene,
    account,
    accountType: input.accountType,
    code: '123456',
    expireAt: new Date(Date.now() + 5 * 60 * 1000).toISOString()
  };

  db.auth.pendingCodes = pruneAuthState(db.auth).pendingCodes.filter(
    (item) => !(item.scene === input.scene && normalizeAccount(item.account) === normalizeAccount(account))
  );
  db.auth.pendingCodes.push(nextCode);
  persistDatabase(db);

  return {
    scene: input.scene,
    maskedAccount: maskAccount(account, input.accountType),
    expireIn: 300
  };
}

export async function mockCreatePasswordResetChallenge(
  input: ForgotPasswordChallengeRequest
): Promise<ForgotPasswordChallenge> {
  const account = input.account.trim();
  if (!account) {
    throw new Error('请输入账号');
  }

  const db = readDatabase();
  if (!matchesMockAccount(db, account)) {
    throw new Error('账号不存在或未绑定');
  }

  ensureVerificationCode(db, 'reset_password', account, input.verificationCode);

  const expireIn = 600;
  const challengeId = createId('pwd_challenge');
  db.auth.passwordResetChallenges = pruneAuthState(db.auth).passwordResetChallenges.filter(
    (item) => normalizeAccount(item.account) !== normalizeAccount(account)
  );
  db.auth.passwordResetChallenges.push({
    challengeId,
    account,
    verificationCode: input.verificationCode.trim(),
    expireAt: new Date(Date.now() + expireIn * 1000).toISOString()
  });
  persistDatabase(db);

  return {
    challengeId,
    expireIn
  };
}

export async function mockResetPassword(input: ResetPasswordRequest): Promise<{ success: true }> {
  const account = input.account.trim();
  if (!account) {
    throw new Error('请输入账号');
  }

  if (!input.challengeId.trim()) {
    throw new Error('缺少重置挑战，请先校验验证码');
  }

  if (!input.newPassword.trim()) {
    throw new Error('请输入新密码');
  }

  if (input.newPassword !== input.confirmPassword) {
    throw new Error('两次输入的新密码不一致');
  }

  const db = readDatabase();
  const challenge = pruneAuthState(db.auth).passwordResetChallenges.find(
    (item) =>
      item.challengeId === input.challengeId &&
      normalizeAccount(item.account) === normalizeAccount(account) &&
      item.verificationCode === input.verificationCode.trim()
  );

  if (!challenge) {
    throw new Error('重置挑战不存在或已过期');
  }

  db.auth.accounts.password = input.newPassword;
  db.auth.passwordResetChallenges = db.auth.passwordResetChallenges.filter((item) => item.challengeId !== input.challengeId);
  db.auth.pendingCodes = db.auth.pendingCodes.filter(
    (item) => !(item.scene === 'reset_password' && normalizeAccount(item.account) === normalizeAccount(account))
  );
  persistDatabase(db);

  return { success: true };
}

export async function mockChangePassword(input: ChangePasswordRequest): Promise<{ success: true }> {
  if (!input.oldPassword.trim()) {
    throw new Error('请输入当前密码');
  }

  if (!input.newPassword.trim()) {
    throw new Error('请输入新密码');
  }

  if (input.newPassword !== input.confirmPassword) {
    throw new Error('两次输入的新密码不一致');
  }

  const db = readDatabase();
  if (input.oldPassword !== db.auth.accounts.password) {
    throw new Error('当前密码错误');
  }

  db.auth.accounts.password = input.newPassword;
  persistDatabase(db);
  return { success: true };
}

export async function mockListSessions(query: SessionListQuery = {}): Promise<PaginatedResult<ConversationSummary>> {
  const db = readDatabase();
  let items = [...db.conversations];

  if (query.scene) {
    items = items.filter((item) => item.scene === query.scene);
  }

  if (query.status) {
    items = items.filter((item) => item.status === query.status);
  }

  if (query.keyword) {
    const keyword = query.keyword.trim().toLowerCase();
    items = items.filter((item) => `${item.title}${item.summary}`.toLowerCase().includes(keyword));
  }

  items.sort((left, right) => new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime());

  const page = query.page ?? 1;
  const pageSize = query.pageSize ?? 20;
  const start = (page - 1) * pageSize;
  const paged = items.slice(start, start + pageSize);

  return {
    items: paged,
    total: items.length,
    page,
    pageSize
  };
}

export async function mockCreateSession(input: SessionCreateRequest): Promise<ConversationSummary> {
  const db = readDatabase();
  const timestamp = nowIso();
  const session: ConversationSummary = {
    conversationId: createId('conv'),
    title: input.title || '新建会话',
    scene: input.scene,
    status: 'active',
    createdAt: timestamp,
    currentAgent: sceneAgentMap[input.scene],
    updatedAt: timestamp,
    lastMessageAt: timestamp,
    summary: input.initialContext ?? '等待首轮提问',
    messageCount: 0
  };

  db.conversations.unshift(session);
  db.messages[session.conversationId] = [];
  persistDatabase(db);
  return session;
}

export async function mockGetMessages(conversationId: string): Promise<ChatMessage[]> {
  const db = readDatabase();
  if (!db.conversations.find((item) => item.conversationId === conversationId)) {
    throw new Error('会话不存在');
  }
  return [...getConversationMessages(db, conversationId)];
}

export async function mockGetSession(conversationId: string): Promise<ConversationSummary> {
  const db = readDatabase();
  const target = db.conversations.find((item) => item.conversationId === conversationId);
  if (!target) {
    throw new Error('会话不存在');
  }

  return target;
}

export async function mockRenameSession(conversationId: string, title: string): Promise<ConversationSummary> {
  const db = readDatabase();
  const target = db.conversations.find((item) => item.conversationId === conversationId);
  if (!target) {
    throw new Error('会话不存在');
  }

  syncConversation(db, conversationId, {
    title,
    updatedAt: nowIso()
  });
  persistDatabase(db);

  return db.conversations.find((item) => item.conversationId === conversationId)!;
}

export async function mockArchiveSession(conversationId: string): Promise<ConversationSummary> {
  const db = readDatabase();
  const target = db.conversations.find((item) => item.conversationId === conversationId);
  if (!target) {
    throw new Error('会话不存在');
  }

  syncConversation(db, conversationId, {
    status: 'archived',
    updatedAt: nowIso()
  });
  persistDatabase(db);

  return db.conversations.find((item) => item.conversationId === conversationId)!;
}

export async function mockRestoreSession(conversationId: string): Promise<ConversationSummary> {
  const db = readDatabase();
  const target = db.conversations.find((item) => item.conversationId === conversationId);
  if (!target) {
    throw new Error('会话不存在');
  }

  syncConversation(db, conversationId, {
    status: 'active',
    updatedAt: nowIso()
  });
  persistDatabase(db);

  return db.conversations.find((item) => item.conversationId === conversationId)!;
}

export async function mockDeleteSession(conversationId: string): Promise<{ success: true }> {
  const db = readDatabase();
  db.conversations = db.conversations.filter((item) => item.conversationId !== conversationId);
  delete db.messages[conversationId];
  persistDatabase(db);
  return { success: true };
}

export async function mockCancelSessionMessage(
  conversationId: string,
  _messageId: string
): Promise<SessionCancelResult> {
  const db = readDatabase();
  const target = db.conversations.find((item) => item.conversationId === conversationId);
  if (!target) {
    return { status: 'not_found' };
  }

  return { status: 'cancelled' };
}

export async function mockRetrySessionMessage(
  conversationId: string,
  messageId: string,
  overrideInput?: string
): Promise<SessionRetryResult> {
  const db = readDatabase();
  const messages = getConversationMessages(db, conversationId);
  const conversation = db.conversations.find((item) => item.conversationId === conversationId);

  if (!conversation) {
    throw new Error('会话不存在');
  }

  if (conversation.status !== 'active') {
    throw new Error('当前会话不可重试，请先恢复后再继续。');
  }

  const target = messages.find((item) => item.messageId === messageId);
  if (!target) {
    throw new Error('消息不存在');
  }

  const retryMessageId = createId('msg');
  const timestamp = nowIso();
  const targetIndex = messages.findIndex((item) => item.messageId === messageId);
  const fallbackUserMessage =
    target.role === 'user'
      ? target
      : [...messages.slice(0, Math.max(targetIndex, 0))].reverse().find((item) => item.role === 'user');
  const userInput = overrideInput?.trim() || fallbackUserMessage?.content || target.content;
  const retryUserMessage: ChatMessage = {
    id: createId('m'),
    messageId: retryMessageId,
    parentMessageId: messageId,
    conversationId,
    role: 'user',
    messageType: 'text',
    content: userInput,
    createdAt: timestamp,
    updatedAt: timestamp,
    status: 'completed'
  };

  const selectedAgent = buildAgent(conversation.scene, userInput);
  const toolCall = buildToolCall(conversation.scene, selectedAgent);
  const completedToolCall = toolCall
    ? {
        ...toolCall,
        status: 'success' as const,
        latencyMs: selectedAgent === 'Finance_Order_Agent' ? 842 : 615,
        dataPreview:
          selectedAgent === 'Finance_Order_Agent'
            ? { totalAmount: '932.50', currency: 'CNY' }
            : { status: 'ok' }
      }
    : null;
  const citations = buildCitations(conversation.scene);
  const answer = buildAnswer(conversation.scene, selectedAgent, userInput);
  const assistantTimestamp = nowIso();
  const assistantMessage: ChatMessage = {
    id: createId('m'),
    messageId: createId('msg'),
    conversationId,
    role: 'assistant',
    messageType: 'markdown',
    content: answer,
    createdAt: assistantTimestamp,
    updatedAt: assistantTimestamp,
    agentName: selectedAgent,
    status: 'completed',
    citations,
    toolCalls: completedToolCall ? [completedToolCall] : undefined,
    finishReason: 'stop'
  };

  db.messages[conversationId] = [...messages, retryUserMessage, assistantMessage];
  syncConversation(db, conversationId, {
    currentAgent: selectedAgent,
    summary: answer.slice(0, 120),
    updatedAt: assistantTimestamp,
    lastMessageAt: assistantTimestamp
  });
  persistDatabase(db);

  return {
    messageId: retryMessageId,
    status: 'completed',
    resolution: 'success',
    answer,
    finishReason: 'stop',
    agentName: selectedAgent,
    toolCalls: completedToolCall ? [completedToolCall] : undefined,
    citations
  };
}

export async function mockGetBillingDashboard(): Promise<BillingDashboard> {
  return readDatabase().billing;
}

export async function mockGetServiceWorkspace(): Promise<ServiceWorkspaceData> {
  const db = readDatabase();
  return {
    orders: sortByRecent(db.billing.orders, (item) => item.createdAt),
    refunds: sortByRecent(db.refunds, (item) => item.createdAt),
    tickets: sortByRecent(db.billing.tickets, (item) => item.updatedAt ?? item.createdAt),
    icpApplications: sortByRecent(db.icpApplications, (item) => item.submittedAt ?? item.approvedAt)
  };
}

export async function mockGetOrderDetail(orderNo: string): Promise<OrderDetail> {
  const db = readDatabase();
  const order = db.billing.orders.find((item) => item.orderNo === orderNo);

  if (!order) {
    throw new Error('订单不存在');
  }

  return {
    order,
    instanceName: order.productType.includes('GPU') ? 'gpu-train-01' : 'object-storage-pack-01',
    region: order.productType.includes('GPU') ? 'cn-shanghai-1' : 'global',
    billingMode: order.productType.includes('GPU') ? '包年包月' : '套餐包',
    renewType: order.eligibleForRefund ? '手动续费' : '自动续费',
    servicePeriod: order.productType.includes('GPU') ? '1 个月' : '年度促销套餐',
    payTime: new Date(new Date(order.createdAt).getTime() + 1000 * 60 * 3).toISOString(),
    configurationSummary: order.productType.includes('GPU')
      ? ['GPU: 1 × 24GB', 'CPU: 16 vCPU', '内存: 64GB', '系统盘: 200GB SSD']
      : ['容量: 5TB', '请求包: 500 万次/月', '冗余: 多可用区'],
    refunds: sortByRecent(
      db.refunds.filter((item) => item.orderNo === orderNo),
      (item) => item.createdAt
    )
  };
}

export async function mockGetRefundDetail(refundNo: string): Promise<RefundRecord> {
  const db = readDatabase();
  const refund = db.refunds.find((item) => item.refundNo === refundNo);

  if (!refund) {
    throw new Error('退款申请不存在');
  }

  return refund;
}

export async function mockCreateTicket(input: CreateTicketRequest): Promise<TicketRecord> {
  const db = readDatabase();
  const timestamp = nowIso();
  const ticket: TicketRecord = {
    ticketNo: `TK${Date.now()}`,
    subject: input.subject,
    status: 'open',
    category: input.category,
    priority: input.priority,
    content: input.content,
    createdAt: timestamp,
    updatedAt: timestamp,
    slaMinutes: input.priority === 'urgent' ? 15 : input.priority === 'high' ? 30 : 120,
    attachments: input.attachments
  };

  db.billing.tickets.unshift(ticket);
  db.ticketReplies[ticket.ticketNo] = [
    {
      replyNo: `TR${Date.now()}`,
      content: '工单已创建成功，客服将尽快跟进处理。',
      createdAt: timestamp,
      operatorType: 'system',
      status: ticket.status,
      attachments: input.attachments
    }
  ];
  persistDatabase(db);
  return ticket;
}

export async function mockGetTicketDetail(ticketNo: string): Promise<TicketDetail> {
  const db = readDatabase();
  const ticket = db.billing.tickets.find((item) => item.ticketNo === ticketNo);

  if (!ticket) {
    throw new Error('工单不存在');
  }

  return {
    ticket,
    replies: [...(db.ticketReplies[ticketNo] ?? [])].sort(
      (left, right) => new Date(left.createdAt).getTime() - new Date(right.createdAt).getTime()
    )
  };
}

export async function mockReplyTicket(
  ticketNo: string,
  input: ReplyTicketRequest
): Promise<TicketReply> {
  const db = readDatabase();
  const ticket = db.billing.tickets.find((item) => item.ticketNo === ticketNo);

  if (!ticket) {
    throw new Error('工单不存在');
  }

  if (ticket.status === 'resolved' || ticket.status === 'closed') {
    throw new Error('已完结工单不可回复');
  }

  const timestamp = nowIso();
  const nextStatus: TicketRecord['status'] = ticket.status === 'open' ? 'processing' : ticket.status;
  const reply: TicketReply = {
    replyNo: `TR${Date.now()}`,
    content: input.content,
    createdAt: timestamp,
    operatorType: 'user',
    attachments: input.attachments,
    status: nextStatus
  };

  db.ticketReplies[ticketNo] = [...(db.ticketReplies[ticketNo] ?? []), reply];
  db.billing.tickets = db.billing.tickets.map((item) =>
    item.ticketNo === ticketNo
      ? {
          ...item,
          status: nextStatus,
          updatedAt: timestamp
        }
      : item
  );

  persistDatabase(db);
  return reply;
}

export async function mockCreateRefund(input: CreateRefundRequest): Promise<RefundRecord> {
  const db = readDatabase();
  const order = db.billing.orders.find((item) => item.orderNo === input.orderNo);
  if (!order) {
    throw new Error('订单不存在');
  }

  const refund: RefundRecord = {
    refundNo: `RF${Date.now()}`,
    orderNo: input.orderNo,
    status: 'pending_review',
    requestedAmount: input.amount,
    currency: 'CNY',
    createdAt: nowIso(),
    timeline: [
      {
        status: 'pending_review',
        at: nowIso(),
        operatorType: 'user',
        note: `退款原因：${input.reason}`
      }
    ]
  };

  db.refunds.unshift(refund);
  db.billing.orders = db.billing.orders.map((item) =>
    item.orderNo === input.orderNo
      ? {
          ...item,
          eligibleForRefund: false
        }
      : item
  );
  persistDatabase(db);
  return refund;
}

export async function mockCheckIcpMaterials(
  input: CheckIcpMaterialsRequest
): Promise<IcpMaterialCheckResult> {
  const requiredMaterials =
    input.subjectType === 'enterprise'
      ? ['business_license', 'domain_certificate', 'website_responsible_id']
      : ['personal_id', 'domain_certificate'];
  const providedTypes = new Set(input.materials.map((item) => item.type));
  const missingTypes = requiredMaterials.filter((item) => !providedTypes.has(item));

  return {
    passed: missingTypes.length === 0,
    requiredMaterials,
    issues: missingTypes.map((item) => ({
      field: item,
      severity: 'error' as const,
      message: `缺少必需材料：${item}`
    }))
  };
}

export async function mockListIcpApplications(): Promise<IcpApplication[]> {
  return sortByRecent(readDatabase().icpApplications, (item) => item.submittedAt ?? item.approvedAt);
}

export async function mockGetIcpApplication(applicationNo: string): Promise<IcpApplication> {
  const application = readDatabase().icpApplications.find((item) => item.applicationNo === applicationNo);
  if (!application) {
    throw new Error('备案申请不存在');
  }

  return application;
}

export async function mockCreateIcpApplication(
  input: CreateIcpApplicationRequest
): Promise<IcpApplication> {
  const db = readDatabase();
  const precheck = await mockCheckIcpMaterials({
    subjectType: input.subjectType,
    materials: input.materials
  });

  if (!precheck.passed) {
    throw new Error('材料预检查未通过，请补齐缺失材料后再提交。');
  }

  const application: IcpApplication = {
    applicationNo: `ICP${Date.now()}`,
    status: 'submitted',
    currentStep: 'waiting_review',
    domain: input.domain,
    websiteName: input.websiteName,
    subjectType: input.subjectType,
    contacts: input.contacts,
    materials: input.materials,
    submittedAt: nowIso()
  };

  db.icpApplications.unshift(application);
  persistDatabase(db);
  return application;
}

export async function mockListResearchTasks(): Promise<ResearchTask[]> {
  return [...readDatabase().researchTasks].sort(
    (left, right) => new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime()
  );
}

export async function mockCreateResearchTask(input: CreateResearchTaskRequest): Promise<ResearchTask> {
  const db = readDatabase();
  const task: ResearchTask = {
    taskId: createId('task'),
    topic: input.topic,
    scope: input.scope,
    depth: input.depth,
    outputFormat: input.outputFormat,
    status: 'completed',
    progress: 100,
    summary: `已生成“${input.topic}”研究草稿，建议优先输出结论、对比矩阵与实施建议。`,
    createdAt: nowIso(),
    reportFileId: createId('file_report'),
    updatedAt: nowIso(),
    referenceUrls: input.referenceUrls
  };

  db.researchTasks.unshift(task);
  persistDatabase(db);
  return task;
}

export async function mockListCampaigns(): Promise<MarketingCampaign[]> {
  return [...readDatabase().campaigns];
}

export async function mockGenerateMarketingCopy(input: MarketingCopyRequest): Promise<MarketingCopyResult> {
  const campaigns = await mockListCampaigns();
  const campaign = campaigns.find((item) => item.campaignId === input.campaignId) ?? campaigns[0];
  const keywords = input.keywords.length ? input.keywords : ['稳定上云', '弹性扩容', '成本可控'];
  const headlinePrefix =
    input.tone === 'launch' ? '新品首发' : input.tone === 'growth' ? '增长加速' : '企业上云';

  return {
    copyId: createId('copy'),
    campaignId: campaign?.campaignId ?? input.campaignId,
    campaignName: campaign?.name ?? '营销活动',
    topic: input.topic,
    audience: input.audience,
    tone: input.tone,
    headline: `${headlinePrefix}｜${input.topic}`,
    summary: `面向${input.audience}，突出${keywords.slice(0, 2).join('、')}等核心卖点。`,
    body: [
      `${campaign?.name ?? '当前活动'}现已开放，围绕“${input.topic}”提供更贴近业务落地的推广素材。`,
      `重点强调 ${keywords.join('、')}，帮助${input.audience}快速理解活动价值与适用场景。`,
      '建议将该文案用于落地页首屏、社群推送或销售跟进话术，并结合海报任务统一视觉输出。'
    ].join('\n\n'),
    callToAction: input.tone === 'launch' ? '立即预约新品权益' : '立即领取活动方案',
    keywords,
    landingPageUrl: campaign?.landingPageUrl,
    createdAt: nowIso()
  };
}

export async function mockListPosterTasks(): Promise<PosterTask[]> {
  return [...readDatabase().posterTasks].sort(
    (left, right) => new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime()
  );
}

export async function mockCreatePosterTask(input: CreatePosterTaskRequest): Promise<PosterTask> {
  const db = readDatabase();
  const campaign = db.campaigns.find((item) => item.campaignId === input.campaignId);
  if (!campaign) {
    throw new Error('营销活动不存在');
  }

  const task: PosterTask = {
    taskId: createId('poster'),
    campaignId: campaign.campaignId,
    campaignName: campaign.name,
    theme: input.theme,
    slogan: input.slogan,
    size: input.size,
    status: 'completed',
    createdAt: nowIso(),
    estimatedSeconds: 20,
    imageUrl: `https://dummyimage.com/640x960/0f172a/ffffff&text=${encodeURIComponent(campaign.name)}`,
    updatedAt: nowIso()
  };

  db.posterTasks.unshift(task);
  persistDatabase(db);
  return task;
}

export async function* mockStreamChatCompletion(
  request: ChatCompletionRequest,
  signal?: AbortSignal
): AsyncGenerator<ChatStreamEvent> {
  const db = readDatabase();
  const timestamp = nowIso();
  const conversation = db.conversations.find((item) => item.conversationId === request.conversationId);

  if (!conversation) {
    throw new Error('会话不存在，请先创建会话');
  }

  if (conversation.status !== 'active') {
    throw new Error('当前会话不可继续对话，请先恢复或新建会话');
  }

  const userMessage: ChatMessage = {
    id: createId('m'),
    messageId: request.messageId,
    conversationId: request.conversationId,
    role: 'user',
    messageType: 'text',
    content: request.userInput,
    createdAt: timestamp,
    updatedAt: timestamp,
    status: 'completed'
  };

  db.messages[request.conversationId] = [...getConversationMessages(db, request.conversationId), userMessage];
  syncConversation(db, request.conversationId, {
    title: conversation.title || buildConversationTitle(request.userInput),
    summary: request.userInput,
    updatedAt: timestamp,
    lastMessageAt: timestamp
  });
  persistDatabase(db);

  const selectedAgent = buildAgent(request.scene, request.userInput);
  const traceId = createId('trace');
  const toolCall = request.options.useTools ? buildToolCall(request.scene, selectedAgent) : null;
  const completedToolCall = toolCall
    ? {
        ...toolCall,
        status: 'success' as const,
        latencyMs: selectedAgent === 'Finance_Order_Agent' ? 842 : 615,
        dataPreview:
          selectedAgent === 'Finance_Order_Agent'
            ? { totalAmount: '932.50', currency: 'CNY' }
            : { status: 'ok' }
      }
    : null;
  const citations = buildCitations(request.scene);
  const answer = buildAnswer(request.scene, selectedAgent, request.userInput);

  await sleep(120, signal);
  yield {
    event: 'meta',
    data: {
      conversationId: request.conversationId,
      messageId: request.messageId,
      traceId,
      agent: 'Orchestrator'
    }
  };

  if (selectedAgent !== 'Orchestrator') {
    await sleep(80, signal);
    yield {
      event: 'route',
      data: {
        fromAgent: 'Orchestrator',
        toAgent: selectedAgent,
        reason: '根据意图识别结果切换到专业 Agent 执行。'
      }
    };
  }

  await sleep(160, signal);
  yield {
    event: 'reasoning',
    data: {
      agent: selectedAgent,
      summary: buildReasoningSummary(request.scene, selectedAgent),
      step: 1
    }
  };

  if (toolCall) {
    await sleep(140, signal);
    yield {
      event: 'tool_call',
      data: toolCall
    };

    await sleep(180, signal);
    yield {
      event: 'tool_result',
      data: completedToolCall!
    };
  }

  if (request.options.useRag) {
    await sleep(120, signal);
    yield buildRetrieval(request.scene, request.userInput);
  }

  for (const piece of chunkText(answer, 22)) {
    await sleep(90, signal);
    yield {
      event: 'delta',
      data: {
        content: piece
      }
    };
  }

  await sleep(120, signal);
  yield {
    event: 'citation',
    data: {
      citations
    }
  };

  await sleep(60, signal);
  yield {
    event: 'done',
    data: {
      finishReason: 'stop',
      usage: {
        promptTokens: 986,
        completionTokens: 212,
        totalTokens: 1198
      }
    }
  };

  const assistantMessage: ChatMessage = {
    id: createId('m'),
    messageId: createId('msg'),
    conversationId: request.conversationId,
    role: 'assistant',
    messageType: 'markdown',
    content: answer,
    createdAt: nowIso(),
    agentName: selectedAgent,
    status: 'completed',
    citations,
    toolCalls: completedToolCall ? [completedToolCall] : undefined,
    finishReason: 'stop',
    updatedAt: nowIso()
  };

  const nextDb = readDatabase();
  nextDb.messages[request.conversationId] = [...getConversationMessages(nextDb, request.conversationId), assistantMessage];
  syncConversation(nextDb, request.conversationId, {
    currentAgent: selectedAgent,
    summary: answer.slice(0, 120),
    updatedAt: assistantMessage.createdAt,
    lastMessageAt: assistantMessage.createdAt
  });
  persistDatabase(nextDb);
}
