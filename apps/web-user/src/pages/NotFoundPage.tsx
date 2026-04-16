import { Link } from 'react-router-dom';

export function NotFoundPage(): JSX.Element {
  return (
    <div className="card empty-state">
      <h2>页面不存在</h2>
      <p className="muted">请返回工作台或聊天页继续使用 SmartCloud-X 用户端。</p>
      <div className="hero__actions">
        <Link className="button button--primary" to="/">
          返回总览
        </Link>
        <Link className="button button--ghost" to="/chat">
          去聊天页
        </Link>
      </div>
    </div>
  );
}
