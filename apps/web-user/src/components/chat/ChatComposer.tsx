import type { KeyboardEvent } from 'react';
import type { Scene } from '../../types/domain';
import { sceneLabels } from '../../lib/format';

interface ChatComposerProps {
  value: string;
  scene: Scene;
  sceneLocked: boolean;
  disabled: boolean;
  isSubmitting: boolean;
  isStreaming: boolean;
  onChange: (value: string) => void;
  onSceneChange: (scene: Scene) => void;
  onSend: () => void;
  onStop: () => void;
}

const sceneOptions: Scene[] = [
  'customer_service',
  'technical_support',
  'billing',
  'icp',
  'marketing',
  'research'
];

export function ChatComposer({
  value,
  scene,
  sceneLocked,
  disabled,
  isSubmitting,
  isStreaming,
  onChange,
  onSceneChange,
  onSend,
  onStop
}: ChatComposerProps): JSX.Element {
  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
      event.preventDefault();
      if (!disabled) {
        onSend();
      }
    }
  };

  return (
    <div className="card composer">
      <div className="composer__toolbar">
        <label className="field field--compact">
          <span>场景</span>
          <select value={scene} onChange={(event) => onSceneChange(event.target.value as Scene)} disabled={sceneLocked || isStreaming || isSubmitting}>
            {sceneOptions.map((option) => (
              <option key={option} value={option}>
                {sceneLabels[option]}
              </option>
            ))}
          </select>
        </label>
        <p className="muted">
          {isSubmitting ? '正在创建会话并准备流式请求，请稍候。' : '支持 Ctrl / Cmd + Enter 发送。附件、文件与结构化操作待后端接入。'}
        </p>
      </div>

      <textarea
        className="composer__input"
        placeholder="请输入问题，例如：帮我查询最近三个月的云服务器账单。"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={handleKeyDown}
        disabled={isStreaming || isSubmitting}
        rows={4}
      />

      <div className="composer__actions">
        <button type="button" className="button button--ghost" disabled>
          附件待接入
        </button>
        <div className="composer__action-group">
          {isStreaming ? (
            <button type="button" className="button button--danger" onClick={onStop}>
              停止生成
            </button>
          ) : null}
          <button type="button" className="button button--primary" onClick={onSend} disabled={disabled}>
            {isSubmitting ? '准备中...' : isStreaming ? '生成中...' : '发送消息'}
          </button>
        </div>
      </div>
    </div>
  );
}
