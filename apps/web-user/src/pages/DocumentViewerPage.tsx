import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

interface KnowledgeDocument {
  id: string;
  title: string;
  content: string;
  tags?: string[];
  updatedAt?: string;
  createdAt?: string;
}

interface ApiEnvelope<T> {
  success?: boolean;
  data?: T;
  error?: unknown;
}

interface TocItem {
  id: string;
  text: string;
  level: number;
}

const PUBLIC_KNOWLEDGE_BASE_URL = '/api/public/knowledge';

function readParam(name: string): string {
  if (typeof window === 'undefined') return '';
  return new URLSearchParams(window.location.search).get(name) ?? '';
}

function slugify(text: string, index: number): string {
  return `section-${index}-${text.replace(/[^\w\u4e00-\u9fa5]+/g, '-').replace(/^-|-$/g, '')}`;
}

function extractToc(markdown: string): TocItem[] {
  return markdown
    .split('\n')
    .map((line, index) => ({ line: line.trim(), index }))
    .filter(({ line }) => /^#{1,3}\s+/.test(line))
    .map(({ line, index }) => {
      const level = line.match(/^#+/)?.[0].length ?? 1;
      const text = line.replace(/^#{1,3}\s+/, '').trim();
      return { id: slugify(text, index), text, level };
    });
}

function normalizeCodeFence(line: string): string | null {
  const text = line.trim();
  if (/^``[a-zA-Z0-9_-]+$/.test(text) && !text.startsWith('```')) {
    return `\`\`\`${text.slice(2)}`;
  }
  if (text === '`') return '```';
  return null;
}

function isPipeTableLine(text: string): boolean {
  return /^\|.*\|$/.test(text);
}

function isTableSeparator(text: string): boolean {
  return /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$/.test(text);
}

function makeTableSeparator(headerLine: string): string {
  const cells = headerLine.split('|').filter((cell) => cell.trim().length > 0);
  return `| ${cells.map(() => '---').join(' | ')} |`;
}

function normalizeDocumentMarkdown(markdown: string, title: string): string {
  const lines = markdown.replace(/\r\n/g, '\n').split('\n');
  const output: string[] = [];
  let seenTitle = false;
  let inFence = false;
  let previousWasHeading = false;
  let previousWasList = false;
  let previousWasTable = false;
  let previousTableLineWasHeader = false;

  const h2Texts = new Set([
    '概述', '前置条件', '创建步骤', '创建后操作', '安全加固建议', '常见问题', '相关文档', '连接实例',
  ]);
  const h3Texts = new Set([
    '选择地域和可用区', '选择实例规格', '选择镜像', '选择网络类型', '配置安全组', '分配公网 IP',
    '公网 IP', '系统盘', '数据盘(可选)', '密钥对登录(推荐)', '密码登录', 'Linux 实例', 'Windows 实例',
    'GPU 实例初始化检查',
  ]);

  const pushBlank = () => {
    if (output.length && output[output.length - 1] !== '') output.push('');
  };

  const pushHeading = (level: 1 | 2 | 3, text: string) => {
    pushBlank();
    output.push(`${'#'.repeat(level)} ${text}`);
    output.push('');
    previousWasHeading = true;
    previousWasList = false;
    previousWasTable = false;
  };

  const pushLine = (line: string) => {
    output.push(line);
    previousWasHeading = false;
    previousWasList = /^\s*(?:[-*]|\d+\.)\s+/.test(line.trim());
    previousWasTable = false;
  };

  const pushTableLine = (line: string) => {
    output.push(line);
    previousWasHeading = false;
    previousWasList = false;
    previousWasTable = true;
    previousTableLineWasHeader = !isTableSeparator(line);
  };

  const pushListLine = (text: string) => {
    pushLine(text);
  };

  for (let index = 0; index < lines.length; index += 1) {
    const rawLine = lines[index];
    const line = rawLine.trimEnd();
    const text = line.trim();

    const fixedFence = normalizeCodeFence(line);
    if (fixedFence) {
      pushBlank();
      output.push(fixedFence);
      inFence = !inFence;
      previousWasHeading = false;
      previousWasList = false;
      previousWasTable = false;
      previousTableLineWasHeader = false;
      continue;
    }

    if (inFence) {
      pushLine(line);
      continue;
    }

    if (!text) {
      pushBlank();
      previousWasHeading = false;
      previousWasList = false;
      previousWasTable = false;
      previousTableLineWasHeader = false;
      continue;
    }

    if (!seenTitle && text === title) {
      pushHeading(1, text);
      seenTitle = true;
      continue;
    }

    if (text.startsWith('#')) {
      pushBlank();
      pushLine(text);
      output.push('');
      continue;
    }

    if (h2Texts.has(text) || /^步骤[一二三四五六七八九十]+[:：]/.test(text)) {
      pushHeading(2, text.replace(':', '：'));
      continue;
    }

    if (h3Texts.has(text)) {
      pushHeading(3, text);
      continue;
    }

    if (/^\*\*Q\d+[:：]/.test(text)) {
      pushHeading(3, text.replace(/^\*\*|\*\*$/g, ''));
      continue;
    }

    if (isPipeTableLine(text)) {
      if (!previousWasTable) pushBlank();
      const next = lines[index + 1]?.trim() ?? '';
      const isFirstTableLine = !previousWasTable;
      pushTableLine(text);
      if (isFirstTableLine && next && isPipeTableLine(next) && !isTableSeparator(next) && !isTableSeparator(text)) {
        pushTableLine(makeTableSeparator(text));
        previousTableLineWasHeader = false;
      }
      continue;
    }

    if (/^\d+\.\s+/.test(text) || /^[-*]\s+/.test(text) || /^>\s+/.test(text)) {
      pushListLine(text);
      continue;
    }

    if (previousWasList && /^[-*]\s+/.test(`- ${text}`) && /^(SSH|HTTP|HTTPS|自定义应用端口)[:：]/.test(text)) {
      pushListLine(`  - ${text}`);
      continue;
    }

    if (previousWasHeading) {
      pushLine(text);
      continue;
    }

    pushLine(text);
  }

  const normalized = output.join('\n').replace(/\n{3,}/g, '\n\n').trim();
  return seenTitle || !title ? normalized : `# ${title}\n\n${normalized}`;
}

function estimateReadMinutes(content: string): number {
  return Math.max(1, Math.ceil(content.length / 500));
}

/* ── Collapse icon ──────────────────────────────────────────────────────── */
function ChevronIcon({ open }: { open: boolean }) {
  return (
    <svg
      className={`h-3.5 w-3.5 shrink-0 text-ink-400 transition-transform duration-200 ${open ? 'rotate-90' : ''}`}
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2}
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
    </svg>
  );
}

/* ── Build TOC tree: group h2/h3 under their parent h1 ─────────────────── */
interface TocGroup {
  h1: TocItem;
  children: TocItem[];
}

function buildTocGroups(toc: TocItem[]): TocGroup[] {
  const groups: TocGroup[] = [];
  let current: TocGroup | null = null;

  for (const item of toc) {
    if (item.level === 1) {
      current = { h1: item, children: [] };
      groups.push(current);
    } else if (current) {
      current.children.push(item);
    } else {
      // orphan child before any h1 — wrap in a synthetic group
      current = { h1: { id: item.id, text: item.text, level: 1 }, children: [] };
      groups.push(current);
    }
  }
  return groups;
}

/* ── Desktop sidebar TOC with collapsible groups ────────────────────────── */
function DesktopTocNav({ toc, activeId }: { toc: TocItem[]; activeId: string }) {
  const groups = useMemo(() => buildTocGroups(toc), [toc]);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const toggleGroup = useCallback((id: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }, []);

  return (
    <nav className="space-y-1">
      {groups.map((group) => {
        const isCollapsed = collapsed.has(group.h1.id);
        const h1IsActive = activeId === group.h1.id;
        return (
          <div key={group.h1.id}>
            {/* H1 row: bold label + collapse toggle */}
            <div className="flex items-center gap-1">
              <a
                className={`flex-1 rounded-md py-1.5 text-sm transition-colors ${
                  h1IsActive ? 'font-bold text-brand-600' : 'font-bold text-ink-700 hover:text-brand-600'
                }`}
                href={`#${group.h1.id}`}
              >
                {group.h1.text}
              </a>
              {group.children.length > 0 && (
                <button
                  type="button"
                  onClick={(e) => { e.preventDefault(); toggleGroup(group.h1.id); }}
                  className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md transition-colors hover:bg-slate-100"
                  aria-label={isCollapsed ? '展开子目录' : '收起子目录'}
                >
                  <ChevronIcon open={!isCollapsed} />
                </button>
              )}
            </div>

            {/* Children */}
            {!isCollapsed && group.children.length > 0 && (
              <div className="ml-3 border-l border-slate-200 space-y-0.5">
                {group.children.map((child) => {
                  const childIsActive = activeId === child.id;
                  return (
                    <a
                      key={child.id}
                      className={`block border-l-2 py-1.5 text-sm transition-colors ${
                        childIsActive
                          ? 'border-brand-500 font-medium text-brand-600'
                          : 'border-transparent text-ink-500 hover:border-slate-300 hover:text-ink-700'
                      }`}
                      style={{
                        marginLeft: `${(child.level - 2) * 12}px`,
                        paddingLeft: '10px',
                      }}
                      href={`#${child.id}`}
                    >
                      {child.text}
                    </a>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </nav>
  );
}

/* ── Mobile TOC drawer ─────────────────────────────────────────────────── */
function MobileToc({ toc, activeId }: { toc: TocItem[]; activeId: string }) {
  const [open, setOpen] = useState(false);
  const groups = useMemo(() => buildTocGroups(toc), [toc]);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const toggleGroup = useCallback((id: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }, []);

  if (!toc.length) return null;

  return (
    <div className="mb-6 lg:hidden">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-sm font-medium text-ink-700 transition-colors hover:bg-slate-100"
      >
        <span className="text-base font-bold">目录</span>
        <svg className={`h-4 w-4 text-ink-500 transition-transform ${open ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {open && (
        <nav className="mt-2 space-y-0.5 rounded-lg border border-slate-200 bg-white p-3">
          {groups.map((group) => {
            const isCollapsed = collapsed.has(group.h1.id);
            const h1IsActive = activeId === group.h1.id;
            return (
              <div key={group.h1.id}>
                <div className="flex items-center gap-1">
                  {group.children.length > 0 && (
                    <button
                      type="button"
                      onClick={(e) => { e.preventDefault(); toggleGroup(group.h1.id); }}
                      className="flex h-5 w-5 shrink-0 items-center justify-center rounded hover:bg-slate-100"
                      aria-label={isCollapsed ? '展开' : '收起'}
                    >
                      <ChevronIcon open={!isCollapsed} />
                    </button>
                  )}
                  <a
                    className={`flex-1 rounded-md py-1.5 text-sm transition-colors ${
                      h1IsActive ? 'font-bold text-brand-600' : 'font-bold text-ink-700 hover:text-brand-600'
                    }`}
                    href={`#${group.h1.id}`}
                    onClick={() => setOpen(false)}
                  >
                    {group.h1.text}
                  </a>
                </div>
                {!isCollapsed && group.children.length > 0 && (
                  <div className="ml-6 space-y-0.5">
                    {group.children.map((child) => {
                      const childIsActive = activeId === child.id;
                      return (
                        <a
                          key={child.id}
                          className={`block rounded-md py-1.5 text-sm transition-colors ${
                            childIsActive ? 'bg-brand-50 font-medium text-brand-600' : 'text-ink-500 hover:bg-slate-50 hover:text-ink-700'
                          }`}
                          style={{ paddingLeft: `${(child.level - 2) * 12}px` }}
                          href={`#${child.id}`}
                          onClick={() => setOpen(false)}
                        >
                          {child.text}
                        </a>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </nav>
      )}
    </div>
  );
}

/* ── Active heading tracking ───────────────────────────────────────────── */
function useActiveHeading(toc: TocItem[]): string {
  const [activeId, setActiveId] = useState('');
  const observerRef = useRef<IntersectionObserver | null>(null);

  useEffect(() => {
    if (!toc.length) return;

    observerRef.current?.disconnect();
    const visibleIds = new Set<string>();

    observerRef.current = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            visibleIds.add(entry.target.id);
          } else {
            visibleIds.delete(entry.target.id);
          }
        }
        if (visibleIds.size > 0) {
          const firstVisible = toc.find((item) => visibleIds.has(item.id));
          if (firstVisible) setActiveId(firstVisible.id);
        }
      },
      { rootMargin: '-80px 0px -70% 0px', threshold: 0 },
    );

    for (const item of toc) {
      const el = document.getElementById(item.id);
      if (el) observerRef.current.observe(el);
    }

    return () => observerRef.current?.disconnect();
  }, [toc]);

  return activeId;
}

/* ── Main page ─────────────────────────────────────────────────────────── */
export function DocumentViewerPage(): JSX.Element {
  const docId = useMemo(() => readParam('docId'), []);
  const fallbackTitle = useMemo(() => readParam('title'), []);
  const [document, setDocument] = useState<KnowledgeDocument | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!docId) {
      setError('缺少文档 ID');
      setLoading(false);
      return;
    }

    const controller = new AbortController();
    fetch(`${PUBLIC_KNOWLEDGE_BASE_URL}/documents/${encodeURIComponent(docId)}`, {
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw new Error(`文档读取失败：${response.status}`);
        return (await response.json()) as ApiEnvelope<KnowledgeDocument>;
      })
      .then((payload) => {
        if (!payload.data) throw new Error('文档不存在或接口返回为空');
        setDocument(payload.data);
      })
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setError(err instanceof Error ? err.message : '文档读取失败');
      })
      .finally(() => setLoading(false));

    return () => controller.abort();
  }, [docId]);

  const title = document?.title || fallbackTitle || '参考文档';
  const content = useMemo(
    () => normalizeDocumentMarkdown(document?.content ?? '', title),
    [document?.content, title],
  );
  const toc = useMemo(() => extractToc(content), [content]);
  const tags = document?.tags?.length ? document.tags : ['howto'];
  const activeId = useActiveHeading(toc);

  const scrollToHeading = useCallback((id: string) => {
    const el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, []);

  return (
    <div className="min-h-screen bg-white">
      {/* ── Top navigation bar ─────────────────────────────────────────── */}
      <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/95 backdrop-blur-sm">
        <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
          <div className="flex items-center gap-3">
            <a href="/chat" className="flex items-center gap-2 text-ink-700 transition-colors hover:text-brand-600">
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
              </svg>
              <span className="text-sm font-medium">返回聊天</span>
            </a>
            <span className="text-slate-300">/</span>
            <span className="text-sm text-ink-500 truncate max-w-[200px] sm:max-w-none">{title}</span>
          </div>
          <div className="flex items-center gap-3 text-xs text-ink-500">
            {document ? <span>{estimateReadMinutes(content)} 分钟阅读</span> : null}
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="flex gap-10 py-8">

          {/* ── Sidebar TOC — desktop ──────────────────────────────────── */}
          <aside className="hidden lg:block w-60 shrink-0">
            <div className="sticky top-24 max-h-[calc(100vh-7rem)] overflow-y-auto">
              <h2 className="mb-4 text-base font-bold text-ink-700">目录</h2>
              {toc.length ? (
                <DesktopTocNav toc={toc} activeId={activeId} />
              ) : (
                <p className="text-sm text-ink-400">暂无目录</p>
              )}
            </div>
          </aside>

          {/* ── Main content ───────────────────────────────────────────── */}
          <main className="min-w-0 flex-1">
            <MobileToc toc={toc} activeId={activeId} />

            {loading && (
              <div className="space-y-4">
                <div className="h-8 w-3/4 animate-pulse rounded bg-slate-100" />
                <div className="h-4 w-full animate-pulse rounded bg-slate-100" />
                <div className="h-4 w-5/6 animate-pulse rounded bg-slate-100" />
                <div className="h-4 w-2/3 animate-pulse rounded bg-slate-100" />
              </div>
            )}

            {error && (
              <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-danger-600">
                {error}
              </div>
            )}

            {document && (
              <article>
                {/* Tags */}
                <div className="mb-6 flex flex-wrap items-center gap-2">
                  {tags.map((tag) => (
                    <span key={tag} className="badge badge-neutral">{tag}</span>
                  ))}
                  {document.updatedAt && (
                    <span className="text-xs text-ink-500">
                      更新于 {new Date(document.updatedAt).toLocaleDateString('zh-CN')}
                    </span>
                  )}
                </div>

                {/* Markdown content */}
                <div className="prose prose-slate max-w-none
                  prose-headings:scroll-mt-20
                  prose-h1:mb-6 prose-h1:pb-3 prose-h1:border-b prose-h1:border-slate-200 prose-h1:text-2xl prose-h1:font-bold prose-h1:text-ink-900
                  prose-h2:mb-4 prose-h2:mt-10 prose-h2:pb-2 prose-h2:border-b prose-h2:border-slate-200 prose-h2:text-xl prose-h2:font-semibold prose-h2:text-ink-900
                  prose-h3:mb-3 prose-h3:mt-8 prose-h3:text-base prose-h3:font-semibold prose-h3:text-ink-800
                  prose-p:text-ink-700 prose-p:leading-7 prose-p:text-[15px]
                  prose-a:text-brand-600 prose-a:no-underline hover:prose-a:underline
                  prose-strong:text-ink-800
                  prose-code:rounded prose-code:bg-slate-100 prose-code:px-1.5 prose-code:py-0.5 prose-code:text-sm prose-code:font-normal prose-code:text-ink-700 prose-code:before:content-none prose-code:after:content-none
                  prose-pre:rounded-lg prose-pre:border prose-pre:border-slate-200 prose-pre:bg-ink-900 prose-pre:p-4
                  prose-pre:code:bg-transparent prose-pre:code:text-slate-200
                  prose-blockquote:border-l-brand-400 prose-blockquote:bg-brand-50/50 prose-blockquote:py-0.5 prose-blockquote:text-ink-500 prose-blockquote:not-italic
                  prose-ul:text-ink-700 prose-ol:text-ink-700
                  prose-li:leading-7 prose-li:text-[15px]
                  prose-img:rounded-lg prose-img:border prose-img:border-slate-200
                ">
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={{
                      h1: ({ children }) => {
                        const text = String(children);
                        const item = toc.find((entry) => entry.text === text && entry.level === 1);
                        return <h1 id={item?.id}>{children}</h1>;
                      },
                      h2: ({ children }) => {
                        const text = String(children);
                        const item = toc.find((entry) => entry.text === text && entry.level === 2);
                        return <h2 id={item?.id}>{children}</h2>;
                      },
                      h3: ({ children }) => {
                        const text = String(children);
                        const item = toc.find((entry) => entry.text === text && entry.level === 3);
                        return <h3 id={item?.id}>{children}</h3>;
                      },
                      a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noreferrer" />,
                      table: ({ node: _node, ...props }) => (
                        <div className="my-6 overflow-x-auto rounded-lg border border-slate-200">
                          <table {...props} className="min-w-full text-sm" />
                        </div>
                      ),
                      th: ({ node: _node, ...props }) => (
                        <th {...props} className="border-b border-slate-200 bg-slate-50 px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-ink-500" />
                      ),
                      td: ({ node: _node, ...props }) => (
                        <td {...props} className="border-b border-slate-100 px-4 py-2.5 text-ink-700" />
                      ),
                    }}
                  >
                    {content}
                  </ReactMarkdown>
                </div>
              </article>
            )}
          </main>
        </div>
      </div>
    </div>
  );
}
