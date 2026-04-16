import { randomUUID } from 'node:crypto';
import { createServer } from 'node:http';
import { setTimeout as delay } from 'node:timers/promises';

const host = '127.0.0.1';
const port = Number(process.env.PLAYWRIGHT_API_PORT ?? 38090);

const fullPermissions = [
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
];

const sceneAgentMap = {
  customer_service: 'Orchestrator',
  billing: 'Finance_Order_Agent',
  technical_support: 'Product_Tech_Agent',
  icp: 'ICP_Service_Agent',
  marketing: 'Ops_Marketing_Agent',
  research: 'Deep_Research_Agent'
};

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET,POST,PATCH,DELETE,OPTIONS',
  'Access-Control-Allow-Headers':
    'Authorization, Content-Type, Accept, X-Request-Id, X-Client-Platform, X-Client-Version, X-Tenant-Id, X-User-Id, Idempotency-Key'
};

function nowIso(offsetMs = 0) {
  return new Date(Date.now() + offsetMs).toISOString();
}

function generateRequestId() {
  return `req_${randomUUID()}`;
}

function buildEnvelope(data, requestId = generateRequestId()) {
  return {
    code: 0,
    message: 'ok',
    data,
    request_id: requestId,
    timestamp: nowIso()
  };
}

function buildErrorEnvelope(message, code, details, requestId = generateRequestId()) {
  return {
    code,
    message,
    error: details ?? null,
    request_id: requestId,
    timestamp: nowIso()
  };
}

function sendJson(res, status, payload, extraHeaders = {}) {
  res.writeHead(status, {
    ...corsHeaders,
    'Content-Type': 'application/json; charset=utf-8',
    ...extraHeaders
  });
  res.end(JSON.stringify(payload));
}

function sendSuccess(res, data, status = 200, extraHeaders = {}) {
  const requestId = generateRequestId();
  sendJson(res, status, buildEnvelope(data, requestId), {
    'X-Request-Id': requestId,
    ...extraHeaders
  });
}

function sendError(res, status, message, code, details, extraHeaders = {}) {
  const requestId = generateRequestId();
  sendJson(res, status, buildErrorEnvelope(message, code, details, requestId), {
    'X-Request-Id': requestId,
    ...extraHeaders
  });
}

async function readBody(req) {
  const chunks = [];
  for await (const chunk of req) {
    chunks.push(Buffer.from(chunk));
  }

  if (!chunks.length) {
    return {};
  }

  const text = Buffer.concat(chunks).toString('utf8').trim();
  if (!text) {
    return {};
  }

  try {
    return JSON.parse(text);
  } catch {
    return {};
  }
}

function paginate(items, searchParams) {
  const page = Number(searchParams.get('page') ?? 1);
  const rawPageSize = searchParams.get('page_size') ?? searchParams.get('pageSize');
  const pageSize = Number(rawPageSize ?? (items.length || 20));
  const start = Math.max(0, (page - 1) * pageSize);
  return {
    items: items.slice(start, start + pageSize),
    total: items.length,
    page,
    page_size: pageSize
  };
}

function sortByUpdatedAt(items, field = 'updated_at') {
  return [...items].sort((left, right) => new Date(right[field] ?? 0).getTime() - new Date(left[field] ?? 0).getTime());
}

function buildUser(profile = 'full') {
  const permissions =
    profile === 'limited_marketing'
      ? fullPermissions.filter((permission) => permission !== 'user:marketing.read' && permission !== 'user:marketing.write')
      : fullPermissions;

  return {
    user_id: 'u_e2e_001',
    tenant_id: 'default',
    name: profile === 'limited_marketing' ? 'E2E 限权用户' : 'E2E 演示用户',
    email: 'demo@smartcloud.local',
    mobile: '13800000001',
    locale: 'zh-CN',
    time_zone: 'Asia/Shanghai',
    permissions
  };
}

function buildInitialState({ profile = 'full', scenarios = [] } = {}) {
  const user = buildUser(profile);
  const supportConversationId = 'conv_seed_support';
  const supportMessages = [
    {
      id: 'm_seed_support_1',
      message_id: 'msg_seed_support_1',
      conversation_id: supportConversationId,
      role: 'user',
      message_type: 'text',
      content: '我的 GPU 实例挂载数据盘失败了，请帮我看一下。',
      created_at: nowIso(-60 * 60 * 1000),
      status: 'completed'
    },
    {
      id: 'm_seed_support_2',
      message_id: 'msg_seed_support_2',
      conversation_id: supportConversationId,
      role: 'assistant',
      message_type: 'markdown',
      content: '建议先确认磁盘已在控制台完成挂载，再检查实例内的分区识别和文件系统步骤。',
      created_at: nowIso(-59 * 60 * 1000),
      agent_name: 'Product_Tech_Agent',
      status: 'completed',
      citations: [
        {
          id: 'cite_support_gpu',
          title: '云服务器挂载排障指引',
          source_type: 'knowledge_base',
          doc_id: 'doc_support_001',
          chunk_id: 'chunk_support_001'
        }
      ]
    }
  ];

  const orders = [
    {
      order_no: 'ord_202604_001',
      product_type: 'GPU 云服务器',
      status: 'paid',
      amount: '299.00',
      created_at: nowIso(-48 * 60 * 60 * 1000),
      eligible_for_refund: true
    }
  ];

  const refunds = [
    {
      refund_no: 'ref_202604_001',
      order_no: 'ord_202604_001',
      status: 'processing',
      requested_amount: '29.00',
      currency: 'CNY',
      created_at: nowIso(-12 * 60 * 60 * 1000),
      timeline: [
        {
          status: 'pending_review',
          at: nowIso(-12 * 60 * 60 * 1000),
          operator_type: 'user',
          note: '套餐暂不继续使用'
        }
      ]
    }
  ];

  const seededTicket = {
    ticket_no: 'tic_202604_001',
    subject: 'GPU 实例挂盘异常',
    status: 'processing',
    category: 'technical_support',
    priority: 'high',
    content: '实例启动后未识别到新挂载的数据盘，请协助排查。',
    created_at: nowIso(-6 * 60 * 60 * 1000),
    updated_at: nowIso(-90 * 60 * 1000),
    sla_minutes: 30,
    attachments: []
  };

  return {
    profile,
    scenarios: new Set(scenarios),
    counters: {
      nextConversation: 2,
      nextTicket: 2,
      nextReply: 2,
      nextRefund: 2,
      nextPoster: 2,
      nextResearch: 2,
      nextIcp: 2,
      nextFile: 2,
      refreshVersion: 1,
      billingSummary401Used: false,
      streamDisconnectUsed: false,
      researchTaskPolls: {}
    },
    auth: {
      user,
      password: 'smartcloud-demo',
      accessToken: 'access_demo_v1',
      refreshToken: 'refresh_demo_v1',
      expiresIn: 7200,
      passwordResetChallenge: null
    },
    sessions: [
      {
        conversation_id: supportConversationId,
        title: 'GPU 挂载排障',
        scene: 'technical_support',
        status: 'active',
        created_at: nowIso(-60 * 60 * 1000),
        current_agent: 'Product_Tech_Agent',
        updated_at: nowIso(-59 * 60 * 1000),
        last_message_at: nowIso(-59 * 60 * 1000),
        summary: supportMessages[1].content,
        message_count: supportMessages.length
      }
    ],
    messages: {
      [supportConversationId]: supportMessages
    },
    billing: {
      summary: {
        total_amount: '932.50',
        currency: 'CNY',
        range: 'this_month',
        top_products: [
          {
            product_type: 'GPU 云服务器',
            amount: '780.00',
            ratio: 0.84
          }
        ],
        top_instances: [
          {
            instance_id: 'ins_gpu_001',
            instance_name: 'gpu-prod-01',
            amount: '780.00'
          }
        ]
      },
      details: {
        items: [
          {
            statement_no: 'stmt_202604_001',
            billing_cycle: '2026-04',
            product_type: 'GPU 云服务器',
            instance_id: 'ins_gpu_001',
            instance_name: 'gpu-prod-01',
            amount: '780.00',
            status: 'settled'
          }
        ]
      },
      invoices: [
        {
          invoice_no: 'inv_202604_001',
          status: 'issued',
          amount: '932.50',
          billing_cycle: '2026-04',
          title: 'SmartCloud-X 演示租户'
        }
      ]
    },
    orders,
    orderDetails: {
      ord_202604_001: {
        order: orders[0],
        instance_name: 'gpu-prod-01',
        region: 'cn-shanghai-1',
        billing_mode: 'postpaid',
        renew_type: 'manual',
        service_period: '2026-04',
        pay_time: nowIso(-47 * 60 * 60 * 1000),
        configuration_summary: ['1x NVIDIA L40', '8 vCPU', '64 GiB RAM'],
        refunds
      }
    },
    refunds,
    refundDetails: {
      ref_202604_001: refunds[0]
    },
    tickets: [seededTicket],
    ticketDetails: {
      tic_202604_001: {
        ticket: seededTicket,
        replies: [
          {
            reply_no: 'reply_202604_001',
            content: '已收到问题，正在协助核对实例磁盘挂载链路。',
            created_at: nowIso(-70 * 60 * 1000),
            operator_type: 'support',
            status: 'processing',
            attachments: []
          }
        ]
      }
    },
    icpApplications: [],
    files: {
      file_seed_001: {
        file_id: 'file_seed_001',
        file_name: 'report-e2e.md',
        size: 2048,
        mime_type: 'text/markdown',
        download_url: 'https://downloads.smartcloud.local/reports/report-e2e.md',
        expires_at: nowIso(10 * 60 * 1000),
        status: 'ready',
        scan_status: 'passed'
      }
    },
    citations: {
      cite_demo_001: {
        citation_id: 'cite_demo_001',
        title: '账单说明（E2E 引用详情）',
        source_type: 'knowledge_base',
        doc_id: 'doc_billing_001',
        chunk_id: 'chunk_billing_001',
        snippet: '账单汇总来自财务账单知识片段，可继续联动账单页和发票记录进行核对。',
        url: 'https://docs.smartcloud.local/billing/guide',
        version_no: 'v2026.04'
      },
      cite_support_gpu: {
        citation_id: 'cite_support_gpu',
        title: '云服务器挂载排障指引',
        source_type: 'knowledge_base',
        doc_id: 'doc_support_001',
        chunk_id: 'chunk_support_001',
        snippet: '确认控制台挂载、系统识别分区和文件系统后，再执行挂载命令。',
        url: 'https://docs.smartcloud.local/support/mount-disk',
        version_no: 'v2026.04'
      }
    },
    marketing: {
      campaigns: [
        {
          campaign_id: 'camp_gpu_2026',
          name: '算力焕新季',
          product_type: 'GPU 云服务器',
          status: 'published',
          start_at: nowIso(-10 * 24 * 60 * 60 * 1000),
          end_at: nowIso(20 * 24 * 60 * 60 * 1000),
          landing_page_url: 'https://market.smartcloud.local/gpu-spring',
          highlights: ['GPU 试用', '弹性扩容', '专属架构支持']
        }
      ],
      posterTasks: {}
    },
    researchTasks: {}
  };
}

let state = buildInitialState();

function resetState(options = {}) {
  state = buildInitialState(options);
  return state;
}

function findConversation(conversationId) {
  return state.sessions.find((item) => item.conversation_id === conversationId);
}

function getConversationMessages(conversationId) {
  return state.messages[conversationId] ?? [];
}

function upsertConversation(conversation) {
  const existingIndex = state.sessions.findIndex((item) => item.conversation_id === conversation.conversation_id);
  if (existingIndex >= 0) {
    state.sessions[existingIndex] = conversation;
  } else {
    state.sessions.unshift(conversation);
  }
  state.sessions = sortByUpdatedAt(state.sessions);
}

function syncConversationFromMessages(conversationId) {
  const conversation = findConversation(conversationId);
  if (!conversation) {
    return;
  }

  const messages = getConversationMessages(conversationId);
  const lastMessage = messages.at(-1);
  if (!lastMessage) {
    return;
  }

  conversation.message_count = messages.length;
  conversation.updated_at = lastMessage.created_at;
  conversation.last_message_at = lastMessage.created_at;
  conversation.summary = lastMessage.content;
  conversation.current_agent = lastMessage.agent_name ?? conversation.current_agent;
  upsertConversation(conversation);
}

function extractToken(req) {
  const header = req.headers.authorization ?? '';
  return header.startsWith('Bearer ') ? header.slice(7) : '';
}

function ensureAuthorized(req, res) {
  const token = extractToken(req);
  if (!token || token !== state.auth.accessToken) {
    sendError(res, 401, '登录态已失效，请刷新令牌后重试。', 4010002);
    return false;
  }

  return true;
}

function createUploadPolicy({ fileName, size, mimeType }) {
  const fileId = `file_e2e_${String(state.counters.nextFile).padStart(3, '0')}`;
  state.counters.nextFile += 1;
  const objectKey = `uploads/${fileId}/${fileName}`;
  state.files[fileId] = {
    file_id: fileId,
    file_name: fileName,
    size,
    mime_type: mimeType,
    status: 'uploaded',
    scan_status: 'pending'
  };

  return {
    file_id: fileId,
    upload_url: `https://uploads.smartcloud.local/${objectKey}`,
    form_fields: {
      key: objectKey
    },
    object_key: objectKey,
    expire_at: nowIso(10 * 60 * 1000)
  };
}

function buildFileRecord(fileId, fallback = {}) {
  const existing = state.files[fileId] ?? {};
  return {
    file_id: fileId,
    file_name: existing.file_name ?? fallback.file_name ?? fileId,
    size: existing.size ?? fallback.size ?? 0,
    mime_type: existing.mime_type ?? fallback.mime_type ?? 'application/octet-stream',
    download_url: existing.download_url ?? fallback.download_url,
    expires_at: existing.expires_at ?? fallback.expires_at ?? nowIso(10 * 60 * 1000),
    status: existing.status ?? fallback.status ?? 'ready',
    scan_status: existing.scan_status ?? fallback.scan_status ?? 'passed'
  };
}

function listVisibleResearchTasks() {
  return Object.values(state.researchTasks);
}

function listVisiblePosterTasks() {
  return Object.values(state.marketing.posterTasks);
}

function normalizeAccount(value) {
  return String(value ?? '').trim().toLowerCase();
}

function maskAccount(account) {
  if (account.includes('@')) {
    const [localPart, domain] = account.split('@');
    return `${localPart.slice(0, 1)}***@${domain}`;
  }

  return `${account.slice(0, 3)}****${account.slice(-4)}`;
}

function buildChatAnswer(scene, userInput) {
  if (scene === 'billing') {
    return {
      agent: 'Finance_Order_Agent',
      content: '最近三个月账单总额为 932.50 元，其中云服务器 780.00 元。',
      citations: [
        {
          citation_id: 'cite_demo_001',
          title: '账单说明',
          doc_id: 'doc_billing_001',
          chunk_id: 'chunk_billing_001'
        }
      ]
    };
  }

  if (scene === 'icp') {
    return {
      agent: 'ICP_Service_Agent',
      content: '已为您整理 ICP 备案材料建议，建议优先准备营业执照和域名证书。',
      citations: []
    };
  }

  return {
    agent: sceneAgentMap[scene] ?? 'Orchestrator',
    content: `已收到问题：“${userInput}”。这是浏览器 E2E 测试返回的演示答复。`,
    citations: []
  };
}

function appendUserMessageIfNeeded(conversationId, messageId, userInput) {
  const messages = getConversationMessages(conversationId);
  if (messages.some((item) => item.message_id === messageId && item.role === 'user')) {
    return;
  }

  const nextMessage = {
    id: `m_${messageId}`,
    message_id: messageId,
    conversation_id: conversationId,
    role: 'user',
    message_type: 'text',
    content: userInput,
    created_at: nowIso(),
    status: 'completed'
  };

  state.messages[conversationId] = [...messages, nextMessage];
  syncConversationFromMessages(conversationId);
}

function appendAssistantMessage(conversationId, messageId, scene, content, citations) {
  const assistantMessageId = `assistant_${messageId}`;
  const messages = getConversationMessages(conversationId);
  if (messages.some((item) => item.message_id === assistantMessageId)) {
    return;
  }

  state.messages[conversationId] = [
    ...messages,
    {
      id: `m_${assistantMessageId}`,
      message_id: assistantMessageId,
      conversation_id: conversationId,
      role: 'assistant',
      message_type: 'markdown',
      content,
      created_at: nowIso(),
      agent_name: sceneAgentMap[scene] ?? 'Orchestrator',
      status: 'completed',
      citations
    }
  ];
  syncConversationFromMessages(conversationId);
}

async function streamChatCompletion(res, body) {
  const conversationId = body.conversation_id;
  const messageId = body.message_id;
  const scene = body.scene ?? 'customer_service';
  const userInput = body.user_input ?? '';
  const answer = buildChatAnswer(scene, userInput);
  const attemptKey = `${conversationId}:${messageId}`;

  state.counters.streamAttempts ??= {};
  state.counters.streamAttempts[attemptKey] = (state.counters.streamAttempts[attemptKey] ?? 0) + 1;

  appendUserMessageIfNeeded(conversationId, messageId, userInput);

  res.writeHead(200, {
    ...corsHeaders,
    'Content-Type': 'text/event-stream; charset=utf-8',
    'Cache-Control': 'no-cache',
    Connection: 'keep-alive'
  });

  const writeEvent = async (event, data, waitMs = 80) => {
    res.write(`event: ${event}\n`);
    res.write(`data: ${JSON.stringify(data)}\n\n`);
    await delay(waitMs);
  };

  await writeEvent('message.started', {
    conversation_id: conversationId,
    message_id: messageId,
    agent: answer.agent,
    trace_id: `trace_${messageId}`
  });

  if (state.scenarios.has('stream_disconnect_once') && !state.counters.streamDisconnectUsed) {
    state.counters.streamDisconnectUsed = true;
    await writeEvent('message.delta', { delta: '最近三个月账单总额为 ' }, 120);
    res.destroy();
    return;
  }

  const segments = answer.content.split(/(?<=。)/).filter(Boolean);
  for (const segment of segments) {
    await writeEvent('message.delta', { delta: segment.trim() });
  }

  if (answer.citations.length) {
    for (const citation of answer.citations) {
      await writeEvent('citation.delta', citation, 60);
    }
  }

  await writeEvent(
    'message.completed',
    {
      message_id: messageId,
      finish_reason: 'stop',
      usage: {
        prompt_tokens: 432,
        completion_tokens: 128,
        total_tokens: 560
      },
      citations: answer.citations,
      tool_calls: []
    },
    40
  );

  appendAssistantMessage(
    conversationId,
    messageId,
    scene,
    answer.content,
    answer.citations.map((citation) => ({
      id: citation.citation_id,
      title: citation.title,
      source_type: 'knowledge_base',
      doc_id: citation.doc_id,
      chunk_id: citation.chunk_id
    }))
  );

  res.end();
}

async function handleApiRequest(req, res, url) {
  const { pathname, searchParams } = url;
  const segments = pathname.split('/').filter(Boolean);

  if (pathname === '/__test/health') {
    sendSuccess(res, { status: 'ok' });
    return;
  }

  if (pathname === '/__test/reset' && req.method === 'POST') {
    const body = await readBody(req);
    resetState({
      profile: body.profile ?? 'full',
      scenarios: Array.isArray(body.scenarios) ? body.scenarios : []
    });
    sendSuccess(res, {
      status: 'reset',
      profile: state.profile,
      scenarios: [...state.scenarios]
    });
    return;
  }

  if (pathname === '/__test/state') {
    sendSuccess(res, {
      profile: state.profile,
      scenarios: [...state.scenarios]
    });
    return;
  }

  if (!pathname.startsWith('/api/v1/')) {
    sendError(res, 404, 'Not found', 4040000);
    return;
  }

  if (req.method === 'OPTIONS') {
    res.writeHead(204, corsHeaders);
    res.end();
    return;
  }

  if (pathname === '/api/v1/auth/login' && req.method === 'POST') {
    const body = await readBody(req);
    if (
      normalizeAccount(body.account) !== 'demo@smartcloud.local' &&
      normalizeAccount(body.account) !== '13800000001' &&
      normalizeAccount(body.account) !== 'demo'
    ) {
      sendError(res, 401, '账号或密码错误。', 4010001);
      return;
    }

    if (body.login_type === 'password' && body.password !== state.auth.password) {
      sendError(res, 401, '账号或密码错误。', 4010001);
      return;
    }

    if (body.login_type !== 'password' && body.sms_code !== '123456' && body.email_code !== '123456') {
      sendError(res, 401, '验证码错误。', 4010003);
      return;
    }

    sendSuccess(res, {
      access_token: state.auth.accessToken,
      refresh_token: state.auth.refreshToken,
      expires_in: state.auth.expiresIn,
      user: state.auth.user
    });
    return;
  }

  if (pathname === '/api/v1/auth/send-code' && req.method === 'POST') {
    const body = await readBody(req);
    sendSuccess(res, {
      scene: body.scene ?? 'login',
      masked_account: maskAccount(String(body.account ?? 'demo@smartcloud.local')),
      expire_in: 300
    });
    return;
  }

  if (pathname === '/api/v1/auth/password/forgot' && req.method === 'POST') {
    const body = await readBody(req);
    const challengeId = `challenge_${randomUUID()}`;
    state.auth.passwordResetChallenge = {
      challengeId,
      account: normalizeAccount(String(body.account ?? '')),
      verificationCode: String(body.verification_code ?? '123456')
    };
    sendSuccess(res, {
      challenge_id: challengeId,
      expire_in: 600
    });
    return;
  }

  if (pathname === '/api/v1/auth/password/reset' && req.method === 'POST') {
    const body = await readBody(req);
    const challenge = state.auth.passwordResetChallenge;

    if (!challenge) {
      sendError(res, 400, '密码重置挑战不存在或已失效。', 4001001);
      return;
    }

    if (
      body.challenge_id !== challenge.challengeId ||
      normalizeAccount(String(body.account ?? '')) !== challenge.account ||
      String(body.verification_code ?? '') !== challenge.verificationCode
    ) {
      sendError(res, 400, '密码重置挑战无效。', 4001002);
      return;
    }

    if (!body.new_password || body.new_password !== body.confirm_password) {
      sendError(res, 400, '两次输入的新密码不一致。', 4001003);
      return;
    }

    state.auth.password = String(body.new_password);
    state.auth.passwordResetChallenge = null;
    sendSuccess(res, { success: true });
    return;
  }

  if (pathname === '/api/v1/auth/refresh' && req.method === 'POST') {
    const body = await readBody(req);
    if (body.refresh_token !== state.auth.refreshToken) {
      sendError(res, 401, '刷新令牌无效。', 4010002);
      return;
    }

    state.counters.refreshVersion += 1;
    state.auth.accessToken = `access_demo_v${state.counters.refreshVersion}`;

    sendSuccess(res, {
      access_token: state.auth.accessToken,
      refresh_token: state.auth.refreshToken,
      expires_in: state.auth.expiresIn,
      user: state.auth.user
    });
    return;
  }

  if (pathname === '/api/v1/auth/logout' && req.method === 'POST') {
    sendSuccess(res, { success: true });
    return;
  }

  if (!ensureAuthorized(req, res)) {
    return;
  }

  if (pathname === '/api/v1/auth/me' && req.method === 'GET') {
    sendSuccess(res, state.auth.user);
    return;
  }

  if (pathname === '/api/v1/users/me' && req.method === 'PATCH') {
    const body = await readBody(req);
    state.auth.user = {
      ...state.auth.user,
      name: body.name ?? state.auth.user.name,
      locale: body.locale ?? state.auth.user.locale,
      time_zone: body.time_zone ?? state.auth.user.time_zone
    };
    sendSuccess(res, state.auth.user);
    return;
  }

  if (pathname === '/api/v1/users/me/change-password' && req.method === 'POST') {
    const body = await readBody(req);

    if (body.old_password !== state.auth.password) {
      sendError(res, 400, '旧密码错误。', 4002001);
      return;
    }

    if (!body.new_password || body.new_password !== body.confirm_password) {
      sendError(res, 400, '两次输入的新密码不一致。', 4002002);
      return;
    }

    state.auth.password = String(body.new_password);
    sendSuccess(res, { success: true });
    return;
  }

  if (pathname === '/api/v1/chat/sessions' && req.method === 'GET') {
    const keyword = String(searchParams.get('keyword') ?? '').trim().toLowerCase();
    const scene = searchParams.get('scene');
    const status = searchParams.get('status');
    let items = state.sessions;

    if (keyword) {
      items = items.filter(
        (item) =>
          item.title.toLowerCase().includes(keyword) ||
          String(item.summary ?? '').toLowerCase().includes(keyword)
      );
    }

    if (scene) {
      items = items.filter((item) => item.scene === scene);
    }

    if (status) {
      items = items.filter((item) => item.status === status);
    }

    sendSuccess(res, paginate(sortByUpdatedAt(items), searchParams));
    return;
  }

  if (pathname === '/api/v1/chat/sessions' && req.method === 'POST') {
    const body = await readBody(req);
    const conversationId = `conv_e2e_${String(state.counters.nextConversation).padStart(3, '0')}`;
    state.counters.nextConversation += 1;
    const conversation = {
      conversation_id: conversationId,
      title: body.title ?? '未命名会话',
      scene: body.scene ?? 'customer_service',
      status: 'active',
      created_at: nowIso(),
      current_agent: sceneAgentMap[body.scene] ?? 'Orchestrator',
      updated_at: nowIso(),
      last_message_at: nowIso(),
      summary: body.initial_context ?? '',
      message_count: 0
    };
    state.messages[conversationId] = [];
    upsertConversation(conversation);
    sendSuccess(res, conversation, 201);
    return;
  }

  if (segments[0] === 'api' && segments[1] === 'v1' && segments[2] === 'chat' && segments[3] === 'sessions' && segments[4]) {
    const conversationId = decodeURIComponent(segments[4]);
    const conversation = findConversation(conversationId);
    if (!conversation) {
      sendError(res, 404, '会话不存在', 'CHAT_CONVERSATION_NOT_FOUND');
      return;
    }

    if (segments.length === 5 && req.method === 'GET') {
      sendSuccess(res, conversation);
      return;
    }

    if (segments.length === 5 && req.method === 'PATCH') {
      const body = await readBody(req);
      conversation.title = body.title ?? conversation.title;
      conversation.updated_at = nowIso();
      upsertConversation(conversation);
      sendSuccess(res, conversation);
      return;
    }

    if (segments.length === 5 && req.method === 'DELETE') {
      state.sessions = state.sessions.filter((item) => item.conversation_id !== conversationId);
      delete state.messages[conversationId];
      sendSuccess(res, { success: true });
      return;
    }

    if (segments[5] === 'messages' && req.method === 'GET') {
      sendSuccess(res, {
        items: getConversationMessages(conversationId)
      });
      return;
    }

    if (segments[5] === 'archive' && req.method === 'POST') {
      conversation.status = 'archived';
      conversation.updated_at = nowIso();
      upsertConversation(conversation);
      sendSuccess(res, conversation);
      return;
    }

    if (segments[5] === 'restore' && req.method === 'POST') {
      conversation.status = 'active';
      conversation.updated_at = nowIso();
      upsertConversation(conversation);
      sendSuccess(res, conversation);
      return;
    }

    if (segments[5] === 'cancel' && req.method === 'POST') {
      sendSuccess(res, { status: 'cancelled' });
      return;
    }

    if (segments[5] === 'retry' && req.method === 'POST') {
      const body = await readBody(req);
      const retriedMessageId = `retry_${body.message_id ?? 'latest'}`;
      const answer = '已重新生成上一轮回复，建议继续核对账单周期和实例维度。';
      appendAssistantMessage(conversationId, retriedMessageId, conversation.scene, answer, []);
      sendSuccess(res, {
        message_id: retriedMessageId,
        status: 'completed',
        answer,
        finish_reason: 'stop',
        agent_name: conversation.current_agent,
        citations: [],
        tool_calls: []
      });
      return;
    }
  }

  if (pathname === '/api/v1/chat/completions' && req.method === 'POST') {
    const body = await readBody(req);
    await streamChatCompletion(res, body);
    return;
  }

  if (pathname === '/api/v1/citations/cite_demo_001' && req.method === 'GET') {
    if (state.scenarios.has('citation_detail_forbidden')) {
      sendError(res, 403, '当前账号无权查看该引用原文。', 4031001);
      return;
    }
  }

  if (segments[0] === 'api' && segments[1] === 'v1' && segments[2] === 'citations' && segments[3] && req.method === 'GET') {
    const citationId = decodeURIComponent(segments[3]);
    const detail = state.citations[citationId];
    if (!detail) {
      sendError(res, 404, '引用不存在。', 4041004);
      return;
    }
    sendSuccess(res, detail);
    return;
  }

  if (pathname === '/api/v1/billing/summary' && req.method === 'GET') {
    if (state.scenarios.has('billing_summary_requires_refresh_once') && !state.counters.billingSummary401Used) {
      state.counters.billingSummary401Used = true;
      sendError(res, 401, '账单汇总请求需要刷新登录态后重试。', 4010002);
      return;
    }
    sendSuccess(res, state.billing.summary);
    return;
  }

  if (pathname === '/api/v1/billing/details' && req.method === 'GET') {
    sendSuccess(res, state.billing.details);
    return;
  }

  if (pathname === '/api/v1/billing/invoices' && req.method === 'GET') {
    sendSuccess(res, paginate(state.billing.invoices, searchParams));
    return;
  }

  if (pathname === '/api/v1/orders' && req.method === 'GET') {
    sendSuccess(res, paginate(sortByUpdatedAt(state.orders, 'created_at'), searchParams));
    return;
  }

  if (segments[0] === 'api' && segments[1] === 'v1' && segments[2] === 'orders' && segments[3] && segments.length === 4 && req.method === 'GET') {
    const orderNo = decodeURIComponent(segments[3]);
    const detail = state.orderDetails[orderNo];
    if (!detail) {
      sendError(res, 404, '订单不存在。', 4042001);
      return;
    }
    sendSuccess(res, detail);
    return;
  }

  if (segments[0] === 'api' && segments[1] === 'v1' && segments[2] === 'orders' && segments[3] && segments[4] === 'refunds' && req.method === 'POST') {
    const orderNo = decodeURIComponent(segments[3]);
    const body = await readBody(req);
    const refundNo = `ref_e2e_${String(state.counters.nextRefund).padStart(3, '0')}`;
    state.counters.nextRefund += 1;
    const refund = {
      refund_no: refundNo,
      order_no: orderNo,
      status: 'pending_review',
      requested_amount: body.amount ?? '0',
      currency: 'CNY',
      created_at: nowIso(),
      timeline: [
        {
          status: 'pending_review',
          at: nowIso(),
          operator_type: 'user',
          note: body.reason ?? '用户提交退款申请'
        }
      ]
    };
    state.refunds.unshift(refund);
    state.refundDetails[refundNo] = refund;
    sendSuccess(res, refund, 201);
    return;
  }

  if (pathname === '/api/v1/refunds' && req.method === 'GET') {
    sendSuccess(res, paginate(sortByUpdatedAt(state.refunds, 'created_at'), searchParams));
    return;
  }

  if (segments[0] === 'api' && segments[1] === 'v1' && segments[2] === 'refunds' && segments[3] && req.method === 'GET') {
    const refundNo = decodeURIComponent(segments[3]);
    const detail = state.refundDetails[refundNo];
    if (!detail) {
      sendError(res, 404, '退款申请不存在。', 4042002);
      return;
    }
    sendSuccess(res, detail);
    return;
  }

  if (pathname === '/api/v1/tickets' && req.method === 'GET') {
    sendSuccess(res, paginate(sortByUpdatedAt(state.tickets), searchParams));
    return;
  }

  if (pathname === '/api/v1/tickets' && req.method === 'POST') {
    const body = await readBody(req);
    const ticketNo = `tic_e2e_${String(state.counters.nextTicket).padStart(3, '0')}`;
    state.counters.nextTicket += 1;
    const attachments = Array.isArray(body.attachments)
      ? body.attachments.map((item) => buildFileRecord(item.file_id))
      : [];
    const ticket = {
      ticket_no: ticketNo,
      subject: body.subject ?? '未命名工单',
      status: 'open',
      category: body.category ?? 'technical_support',
      priority: body.priority ?? 'medium',
      content: body.content ?? '',
      created_at: nowIso(),
      updated_at: nowIso(),
      sla_minutes: 30,
      attachments
    };
    state.tickets.unshift(ticket);
    state.ticketDetails[ticketNo] = {
      ticket,
      replies: []
    };
    sendSuccess(res, ticket, 201);
    return;
  }

  if (segments[0] === 'api' && segments[1] === 'v1' && segments[2] === 'tickets' && segments[3] && segments.length === 4 && req.method === 'GET') {
    const ticketNo = decodeURIComponent(segments[3]);
    const detail = state.ticketDetails[ticketNo];
    if (!detail) {
      sendError(res, 404, '工单不存在。', 4043001);
      return;
    }
    sendSuccess(res, detail);
    return;
  }

  if (segments[0] === 'api' && segments[1] === 'v1' && segments[2] === 'tickets' && segments[3] && segments[4] === 'replies' && req.method === 'POST') {
    const ticketNo = decodeURIComponent(segments[3]);
    const detail = state.ticketDetails[ticketNo];
    if (!detail) {
      sendError(res, 404, '工单不存在。', 4043001);
      return;
    }
    const body = await readBody(req);
    const replyNo = `reply_e2e_${String(state.counters.nextReply).padStart(3, '0')}`;
    state.counters.nextReply += 1;
    const reply = {
      reply_no: replyNo,
      content: body.content ?? '',
      created_at: nowIso(),
      operator_type: 'user',
      status: 'processing',
      attachments: Array.isArray(body.attachments)
        ? body.attachments.map((item) => buildFileRecord(item.file_id))
        : []
    };
    detail.ticket = {
      ...detail.ticket,
      status: 'processing',
      updated_at: reply.created_at
    };
    detail.replies.push(reply);
    state.tickets = state.tickets.map((item) =>
      item.ticket_no === ticketNo ? detail.ticket : item
    );
    sendSuccess(res, reply, 201);
    return;
  }

  if (pathname === '/api/v1/files/upload-policy' && req.method === 'POST') {
    const body = await readBody(req);
    sendSuccess(
      res,
      createUploadPolicy({
        fileName: body.file_name ?? 'e2e-upload.bin',
        size: Number(body.size ?? 0),
        mimeType: body.mime_type ?? 'application/octet-stream'
      }),
      201
    );
    return;
  }

  if (pathname === '/api/v1/files/complete' && req.method === 'POST') {
    const body = await readBody(req);
    const fileRecord = buildFileRecord(body.file_id, {
      file_name: String(body.object_key ?? body.file_id).split('/').at(-1),
      size: Number(body.size ?? 0),
      status: 'ready',
      scan_status: 'passed'
    });
    state.files[body.file_id] = fileRecord;
    sendSuccess(res, fileRecord);
    return;
  }

  if (segments[0] === 'api' && segments[1] === 'v1' && segments[2] === 'files' && segments[3] && req.method === 'GET') {
    const fileId = decodeURIComponent(segments[3]);
    if (state.scenarios.has('research_report_file_missing') && fileId === 'file_seed_001') {
      sendError(res, 404, '研究报告文件不存在。', 4044001);
      return;
    }
    const fileRecord = state.files[fileId];
    if (!fileRecord) {
      sendError(res, 404, '文件不存在。', 4044001);
      return;
    }
    sendSuccess(res, fileRecord);
    return;
  }

  if (pathname === '/api/v1/icp/materials/check' && req.method === 'POST') {
    const body = await readBody(req);
    const materials = Array.isArray(body.materials) ? body.materials : [];
    const hasBusinessLicense = materials.some((item) => item.type === 'business_license');

    if (!hasBusinessLicense) {
      sendSuccess(res, {
        passed: false,
        required_materials: ['营业执照'],
        issues: [
          {
            field: 'materials',
            severity: 'error',
            message: '缺少营业执照，请先完成材料上传登记。'
          }
        ]
      });
      return;
    }

    sendSuccess(res, {
      passed: true,
      required_materials: ['营业执照'],
      issues: []
    });
    return;
  }

  if (pathname === '/api/v1/icp/applications' && req.method === 'POST') {
    const body = await readBody(req);
    const applicationNo = `ICP_E2E_${String(state.counters.nextIcp).padStart(3, '0')}`;
    state.counters.nextIcp += 1;
    const application = {
      application_no: applicationNo,
      status: 'submitted',
      current_step: 'waiting_review',
      domain: body.domain ?? '',
      website_name: body.website_name ?? '',
      subject_type: body.subject_type ?? 'enterprise',
      contacts: Array.isArray(body.contacts) ? body.contacts : [],
      materials: Array.isArray(body.materials) ? body.materials : [],
      submitted_at: nowIso()
    };
    state.icpApplications.unshift(application);
    sendSuccess(res, application, 201);
    return;
  }

  if (segments[0] === 'api' && segments[1] === 'v1' && segments[2] === 'icp' && segments[3] === 'applications' && segments[4] && req.method === 'GET') {
    const applicationNo = decodeURIComponent(segments[4]);
    const application = state.icpApplications.find((item) => item.application_no === applicationNo);
    if (!application) {
      sendError(res, 404, '备案申请不存在。', 4045001);
      return;
    }
    sendSuccess(res, application);
    return;
  }

  if (pathname === '/api/v1/marketing/campaigns' && req.method === 'GET') {
    sendSuccess(res, paginate(state.marketing.campaigns, searchParams));
    return;
  }

  if (pathname === '/api/v1/marketing/copy/generate' && req.method === 'POST') {
    if (state.scenarios.has('marketing_copy_rate_limited')) {
      sendError(
        res,
        429,
        '营销文案生成触发限流，请 30 秒后重试。',
        4291001,
        {
          retry_after_seconds: 30
        },
        {
          'Retry-After': '30'
        }
      );
      return;
    }

    const body = await readBody(req);
    sendSuccess(res, {
      copy_id: `copy_${randomUUID()}`,
      campaign_name: '算力焕新季',
      headline: '面向企业技术负责人的大模型上云方案',
      summary: '围绕稳定算力、弹性扩容和专属支持输出一段可复用的推广文案。',
      body: `面向 ${body.audience ?? '企业技术负责人'}，现在即可体验 SmartCloud GPU 云服务器。\n稳定算力、弹性扩容、专属支持，帮助团队更快完成大模型上线。`,
      call_to_action: '立即申请 GPU 试用',
      landing_page_url: 'https://market.smartcloud.local/gpu-spring',
      created_at: nowIso()
    });
    return;
  }

  if (pathname === '/api/v1/marketing/posters' && req.method === 'POST') {
    const body = await readBody(req);
    const taskId = `poster_e2e_${String(state.counters.nextPoster).padStart(3, '0')}`;
    state.counters.nextPoster += 1;
    const task = {
      task_id: taskId,
      campaign_id: body.campaign_id ?? 'camp_gpu_2026',
      campaign_name: '算力焕新季',
      theme: body.theme ?? '工业级上云活动',
      slogan: body.slogan ?? '部署大模型，从稳定算力开始',
      size: body.size ?? '1024x1536',
      status: 'queued',
      created_at: nowIso(),
      estimated_seconds: 45,
      updated_at: nowIso()
    };
    state.marketing.posterTasks[taskId] = task;
    sendSuccess(res, task, 201);
    return;
  }

  if (segments[0] === 'api' && segments[1] === 'v1' && segments[2] === 'marketing' && segments[3] === 'posters' && segments[4] && req.method === 'GET') {
    const taskId = decodeURIComponent(segments[4]);
    const task = state.marketing.posterTasks[taskId];
    if (!task) {
      sendError(res, 404, '海报任务不存在。', 4046001);
      return;
    }
    sendSuccess(res, task);
    return;
  }

  if (pathname === '/api/v1/research/tasks' && req.method === 'POST') {
    const body = await readBody(req);
    const taskId = `research_e2e_${String(state.counters.nextResearch).padStart(3, '0')}`;
    state.counters.nextResearch += 1;
    const task = {
      task_id: taskId,
      topic: body.topic ?? '未命名任务',
      scope: body.scope ?? '',
      depth: body.depth ?? 'standard',
      output_format: body.output_format ?? 'markdown',
      status: 'queued',
      progress: 0,
      summary: '研究任务已创建，等待后端服务完成生成。',
      created_at: nowIso(),
      updated_at: nowIso(),
      reference_urls: Array.isArray(body.reference_urls) ? body.reference_urls : []
    };
    state.researchTasks[taskId] = task;
    sendSuccess(res, task, 201);
    return;
  }

  if (segments[0] === 'api' && segments[1] === 'v1' && segments[2] === 'research' && segments[3] === 'tasks' && segments[4] && req.method === 'GET') {
    const taskId = decodeURIComponent(segments[4]);
    const task = state.researchTasks[taskId];
    if (!task) {
      sendError(res, 404, '研究任务不存在。', 4047001);
      return;
    }

    if (state.scenarios.has('research_task_completes_with_report') && task.status !== 'completed') {
      state.counters.researchTaskPolls[taskId] = (state.counters.researchTaskPolls[taskId] ?? 0) + 1;
      if (state.counters.researchTaskPolls[taskId] >= 1) {
        task.status = 'completed';
        task.progress = 100;
        task.summary = '研究任务已完成，可预览导出报告。';
        task.report_file_id = 'file_seed_001';
        task.started_at ??= nowIso(-2 * 60 * 1000);
        task.finished_at = nowIso();
        task.updated_at = nowIso();
      }
    }

    sendSuccess(res, task);
    return;
  }

  sendError(res, 404, `Unhandled route: ${req.method} ${pathname}`, 4049999);
}

const server = createServer((req, res) => {
  const url = new URL(req.url ?? '/', `http://${req.headers.host ?? `${host}:${port}`}`);

  if (req.method === 'OPTIONS') {
    res.writeHead(204, corsHeaders);
    res.end();
    return;
  }

  void handleApiRequest(req, res, url).catch((error) => {
    // eslint-disable-next-line no-console
    console.error('[mock-api-server] request failed', error);
    if (!res.headersSent) {
      sendError(res, 500, error instanceof Error ? error.message : 'Unexpected server error', 5009000);
      return;
    }
    res.destroy();
  });
});

server.listen(port, host, () => {
  // eslint-disable-next-line no-console
  console.log(`[mock-api-server] listening on http://${host}:${port}`);
});

const shutdown = () => {
  server.close(() => process.exit(0));
};

process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
