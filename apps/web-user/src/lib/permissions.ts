import type { AuthSession } from '../types/domain';

export interface PermissionRule {
  allOf?: string[];
  anyOf?: string[];
}

export type AppFeatureKey =
  | 'dashboard'
  | 'chat'
  | 'sessions'
  | 'billing'
  | 'orders'
  | 'tickets'
  | 'icp'
  | 'serviceDesk'
  | 'research'
  | 'marketing'
  | 'profile';

export interface AppFeatureDefinition {
  key: AppFeatureKey;
  route: string;
  label: string;
  description: string;
  permissionRule?: PermissionRule;
}

export const appFeatureDefinitions: Record<AppFeatureKey, AppFeatureDefinition> = {
  dashboard: {
    key: 'dashboard',
    route: '/',
    label: '总览',
    description: '查看用户工作台与能力概况。'
  },
  chat: {
    key: 'chat',
    route: '/chat',
    label: '聊天',
    description: '进入智能客服主对话链路。',
    permissionRule: {
      allOf: ['user:chat.use']
    }
  },
  sessions: {
    key: 'sessions',
    route: '/sessions',
    label: '会话',
    description: '查看历史会话并继续上下文。',
    permissionRule: {
      allOf: ['user:chat.use']
    }
  },
  billing: {
    key: 'billing',
    route: '/billing',
    label: '账单',
    description: '查看账单总览、明细与发票。',
    permissionRule: {
      allOf: ['user:billing.read']
    }
  },
  orders: {
    key: 'orders',
    route: '/orders',
    label: '订单',
    description: '查看订单详情并处理退款流程。',
    permissionRule: {
      allOf: ['user:order.read']
    }
  },
  tickets: {
    key: 'tickets',
    route: '/tickets',
    label: '工单',
    description: '查看与跟进工单、人工协助入口。',
    permissionRule: {
      allOf: ['user:ticket.read']
    }
  },
  icp: {
    key: 'icp',
    route: '/icp',
    label: 'ICP',
    description: '查看备案材料与申请状态。',
    permissionRule: {
      allOf: ['user:icp.read']
    }
  },
  serviceDesk: {
    key: 'serviceDesk',
    route: '/service-desk',
    label: '服务台',
    description: '统一处理订单、工单与 ICP 工作区。',
    permissionRule: {
      anyOf: ['user:order.read', 'user:ticket.read', 'user:icp.read']
    }
  },
  research: {
    key: 'research',
    route: '/research',
    label: '研究',
    description: '查看研究任务并跟踪报告。',
    permissionRule: {
      allOf: ['user:research.read']
    }
  },
  marketing: {
    key: 'marketing',
    route: '/marketing',
    label: '营销',
    description: '查看活动、文案与海报任务。',
    permissionRule: {
      allOf: ['user:marketing.read']
    }
  },
  profile: {
    key: 'profile',
    route: '/profile',
    label: '个人中心',
    description: '查看权限、资料与密码状态。'
  }
};

export const navFeatureKeys: AppFeatureKey[] = [
  'dashboard',
  'chat',
  'sessions',
  'billing',
  'orders',
  'tickets',
  'icp',
  'serviceDesk',
  'research',
  'marketing',
  'profile'
];

export const dashboardQuickLinkFeatureKeys: AppFeatureKey[] = [
  'chat',
  'sessions',
  'billing',
  'orders',
  'tickets',
  'icp',
  'serviceDesk',
  'marketing',
  'research',
  'profile'
];

export function getFeatureDefinition(feature: AppFeatureKey): AppFeatureDefinition {
  return appFeatureDefinitions[feature];
}

export function hasPermission(session: AuthSession | null, permission: string): boolean {
  return Boolean(session?.user.permissions.includes(permission));
}

export function matchesPermissionRule(session: AuthSession | null, rule?: PermissionRule): boolean {
  if (!rule) {
    return true;
  }

  const matchesAllOf = rule.allOf ? rule.allOf.every((permission) => hasPermission(session, permission)) : true;
  const matchesAnyOf = rule.anyOf ? rule.anyOf.some((permission) => hasPermission(session, permission)) : true;

  return matchesAllOf && matchesAnyOf;
}

export function canAccessFeature(session: AuthSession | null, feature: AppFeatureKey): boolean {
  return matchesPermissionRule(session, getFeatureDefinition(feature).permissionRule);
}

export function listAccessibleFeatureDefinitions(
  session: AuthSession | null,
  features: AppFeatureKey[] = navFeatureKeys
): AppFeatureDefinition[] {
  return features.map(getFeatureDefinition).filter((feature) => canAccessFeature(session, feature.key));
}

export function listRestrictedFeatureDefinitions(
  session: AuthSession | null,
  features: AppFeatureKey[] = navFeatureKeys
): AppFeatureDefinition[] {
  return features.map(getFeatureDefinition).filter((feature) => !canAccessFeature(session, feature.key));
}

