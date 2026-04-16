import { Link } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { getFeatureDefinition, hasPermission, type AppFeatureKey } from '../lib/permissions';
import { Badge } from './Badge';

interface AccessDeniedCardProps {
  feature: AppFeatureKey;
}

export function AccessDeniedCard({ feature }: AccessDeniedCardProps): JSX.Element {
  const { session } = useAuth();
  const definition = getFeatureDefinition(feature);
  const permissionRule = definition.permissionRule;
  const allOfPermissions = permissionRule?.allOf ?? [];
  const anyOfPermissions = permissionRule?.anyOf ?? [];
  const missingAllOf = allOfPermissions.filter((permission) => !hasPermission(session, permission));
  const missingAnyOf = anyOfPermissions.some((permission) => hasPermission(session, permission)) ? [] : anyOfPermissions;

  return (
    <div className="card empty-state access-denied">
      <Badge tone="warning">权限不足</Badge>
      <h2>{definition.label}暂未开通</h2>
      <p className="muted">{definition.description}</p>
      <p className="muted">当前账号未满足访问该页面所需的用户侧权限，请在个人中心核对当前 RBAC 返回值。</p>

      {missingAllOf.length ? (
        <div className="access-denied__permissions stack stack--sm">
          <strong>需要补齐以下权限</strong>
          <div className="permission-grid">
            {missingAllOf.map((permission) => (
              <Badge key={permission} tone="info">
                {permission}
              </Badge>
            ))}
          </div>
        </div>
      ) : null}

      {missingAnyOf.length ? (
        <div className="access-denied__permissions stack stack--sm">
          <strong>至少需要以下任一权限</strong>
          <div className="permission-grid">
            {missingAnyOf.map((permission) => (
              <Badge key={permission} tone="info">
                {permission}
              </Badge>
            ))}
          </div>
        </div>
      ) : null}

      <div className="hero__actions">
        <Link className="button button--primary" to="/profile">
          查看权限概览
        </Link>
        <Link className="button button--ghost" to="/">
          返回总览
        </Link>
      </div>
    </div>
  );
}
