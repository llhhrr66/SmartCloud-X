const dateTimeFormatter = new Intl.DateTimeFormat("zh-CN", {
  dateStyle: "medium",
  timeStyle: "short",
});

const numberFormatter = new Intl.NumberFormat("zh-CN");

const metricLabelMap: Record<string, string> = {
  sources: "来源数",
  documents: "文档数",
  chunks: "分块数",
  ingestions: "导入任务",
  knowledgeBases: "知识库",
  adminJobs: "后台任务",
  pendingEvents: "待处理事件",
};

const statusLabelMap: Record<string, string> = {
  ok: "正常",
  ready: "已就绪",
  active: "活跃",
  published: "已发布",
  enabled: "已启用",
  success: "成功",
  disabled: "已停用",
  accepted: "已接收",
  pending: "待处理",
  queued: "排队中",
  processing: "处理中",
  completed: "已完成",
  running: "运行中",
  draft: "草稿",
  expired: "已过期",
  deleted: "已删除",
  imported: "已导入",
  reused: "已复用",
  failed: "失败",
  degraded: "降级",
  inactive: "未启用",
  unknown: "未知",
  loading: "加载中",
  create: "创建",
  update: "更新",
  reindex: "重建索引",
  manual: "手工录入",
  filesystem: "本地目录",
  file: "文件",
  minio: "对象存储",
  object_storage: "对象存储",
  product: "产品资料",
  configured: "已配置",
  unreachable: "不可达",
  blocked: "已阻塞",
  answerable: "可回答",
};

const resourceTypeLabelMap: Record<string, string> = {
  knowledge_base: "知识库",
  knowledge_document: "知识文档",
};

const serviceLabelMap: Record<string, string> = {
  "knowledge-service": "知识库服务",
  "rag-service": "检索服务",
};

function normalizeKey(value?: string | null): string {
  return value?.trim().toLowerCase().replace(/[\s-]+/g, "_") ?? "";
}

function titleize(value: string): string {
  return value
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((item) => item.slice(0, 1).toUpperCase() + item.slice(1))
    .join(" ");
}

export function formatDateTime(value?: string | null): string {
  if (!value) {
    return "—";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return dateTimeFormatter.format(date);
}

export function formatInteger(value?: number | null): string {
  return numberFormatter.format(value ?? 0);
}

export function formatMetricLabel(value: string): string {
  return metricLabelMap[value] ?? titleize(value);
}

export function formatStatusLabel(value?: string | null): string {
  if (!value) {
    return "未知";
  }

  const normalized = normalizeKey(value);
  return statusLabelMap[normalized] ?? value;
}

export function formatResourceTypeLabel(value?: string | null): string {
  if (!value) {
    return "全部资源";
  }

  const normalized = normalizeKey(value);
  return resourceTypeLabelMap[normalized] ?? formatStatusLabel(value);
}

export function formatServiceLabel(value?: string | null): string {
  if (!value) {
    return "服务";
  }

  return serviceLabelMap[value] ?? value;
}

export function formatSourceTypeLabel(value?: string | null): string {
  return formatStatusLabel(value ?? "manual");
}

export function getStatusTone(
  value?: string | null,
): "neutral" | "success" | "warning" | "danger" {
  const normalized = normalizeKey(value);

  if (!normalized) {
    return "neutral";
  }

  if (
    /fail|error|disabled|inactive|blocked|unreachable|forbidden|denied|invalid|expired|deleted/.test(normalized)
  ) {
    return "danger";
  }

  if (/ok|ready|completed|imported|reused|answerable|configured|active|published|enabled|success/.test(normalized)) {
    return "success";
  }

  if (/pending|queued|processing|accepted|degraded|warning|not_ready|running|draft|loading/.test(normalized)) {
    return "warning";
  }

  return "neutral";
}

export function joinLabels(values: string[]): string {
  return values.length > 0 ? values.join("、") : "—";
}
