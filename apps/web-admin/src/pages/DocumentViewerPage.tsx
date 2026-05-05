import { useCallback, useEffect, useRef, useState } from "react";
import { useToast } from "../components/Toast";
import { adminApi } from "../lib/api";
import { parseMarkdown } from "../lib/markdown-parser";
import { DocToc } from "../components/DocToc";
import type { KnowledgeDocumentContent } from "../types";
import type { DocHeading } from "../lib/markdown-parser";

/**
 * DocumentViewerPage — professional document viewer with TOC sidebar.
 * Navigated to via hash: #/document-viewer?docId=xxx&title=yyy
 * Uses parseMarkdown for structured HTML + heading extraction,
 * IntersectionObserver for scroll-spy, and event delegation for copy buttons.
 */
export function DocumentViewerPage() {
  const [doc, setDoc] = useState<KnowledgeDocumentContent | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeId, setActiveId] = useState("");
  const [metaOpen, setMetaOpen] = useState(false);
  const [tocDrawerOpen, setTocDrawerOpen] = useState(false);
  const [headings, setHeadings] = useState<DocHeading[]>([]);
  const [htmlContent, setHtmlContent] = useState("");

  const contentRef = useRef<HTMLDivElement>(null);
  const observerRef = useRef<IntersectionObserver | null>(null);
  const toast = useToast();

  useEffect(() => {
    void loadDocument();
  }, []);

  async function loadDocument() {
    const params = new URLSearchParams(
      window.location.hash.replace(/^#\/document-viewer\??/, ""),
    );
    const docId = params.get("docId");
    if (!docId) {
      setError("缺少 docId 参数");
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const result = await adminApi.fetchDocumentContent(docId);
      setDoc(result);
      const parsed = parseMarkdown(result.content || "");
      setHeadings(parsed.headings);
      setHtmlContent(parsed.html);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "加载文档内容失败";
      setError(msg);
      toast.push(msg, "error");
    } finally {
      setLoading(false);
    }
  }

  // ── IntersectionObserver scroll-spy ──
  useEffect(() => {
    if (!contentRef.current || headings.length === 0) return;

    // Tear down any previous observer
    if (observerRef.current) observerRef.current.disconnect();

    const headingEls = contentRef.current.querySelectorAll(
      ".doc-h1, .doc-h2, .doc-h3",
    );

    const visibleIds = new Map<string, number>();

    observerRef.current = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const id = entry.target.id;
          if (!id) continue;
          if (entry.isIntersecting) {
            visibleIds.set(id, entry.intersectionRatio);
          } else {
            visibleIds.delete(id);
          }
        }
        // Pick the first visible heading (topmost in viewport)
        if (visibleIds.size > 0) {
          // Find the heading with the smallest top position
          let bestId = "";
          let bestTop = Infinity;
          for (const id of visibleIds.keys()) {
            const el = document.getElementById(id);
            if (el) {
              const rect = el.getBoundingClientRect();
              if (rect.top < bestTop) {
                bestTop = rect.top;
                bestId = id;
              }
            }
          }
          if (bestId) setActiveId(bestId);
        }
      },
      {
        root: null,
        rootMargin: "-80px 0px -60% 0px",
        threshold: [0, 0.25, 0.5, 0.75, 1],
      },
    );

    for (const el of headingEls) {
      observerRef.current.observe(el);
    }

    return () => {
      observerRef.current?.disconnect();
    };
  }, [headings, htmlContent]);

  // ── Copy button event delegation ──
  const handleContentClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      const target = e.target as HTMLElement;
      if (target.classList.contains("doc-copy-btn")) {
        const codeEl = target.parentElement?.querySelector("code");
        if (codeEl) {
          navigator.clipboard.writeText(codeEl.textContent || "").then(
            () => {
              target.textContent = "已复制";
              toast.push("代码已复制到剪贴板", "success");
              setTimeout(() => {
                target.textContent = "复制";
              }, 2000);
            },
            () => {
              toast.push("复制失败", "error");
            },
          );
        }
      }
    },
    [toast],
  );

  function goBack() {
    window.history.back();
  }

  // ── Loading skeleton ──
  if (loading) {
    return (
      <section className="doc-page-shell animate-fade-in">
        <div className="doc-topbar">
          <button className="btn-ghost" onClick={goBack} type="button">
            ← 返回
          </button>
        </div>
        <div className="doc-body-area">
          <div className="doc-content-column">
            <div className="skeleton" style={{ height: 32, width: "60%", marginBottom: 24 }} />
            <div className="skeleton" style={{ height: 16, width: "100%", marginBottom: 12 }} />
            <div className="skeleton" style={{ height: 16, width: "95%", marginBottom: 12 }} />
            <div className="skeleton" style={{ height: 16, width: "88%", marginBottom: 12 }} />
            <div className="skeleton" style={{ height: 16, width: "92%", marginBottom: 12 }} />
            <div className="skeleton" style={{ height: 120, width: "100%", marginBottom: 16 }} />
            <div className="skeleton" style={{ height: 16, width: "78%" }} />
          </div>
        </div>
      </section>
    );
  }

  // ── Error state ──
  if (error || !doc) {
    return (
      <section className="doc-page-shell animate-fade-in">
        <div className="doc-topbar">
          <button className="btn-ghost" onClick={goBack} type="button">
            ← 返回
          </button>
        </div>
        <div className="empty-state">
          <p className="text-lg font-semibold mb-2" style={{ color: "var(--accent-danger)" }}>
            文档加载失败
          </p>
          <p className="text-sm muted">{error ?? "未找到文档"}</p>
          <button className="btn-secondary mt-4" onClick={loadDocument} type="button">
            重试
          </button>
        </div>
      </section>
    );
  }

  // ── Metadata rows ──
  const metaRows: Array<[string, string]> = [];
  if (doc.id || doc.doc_id) metaRows.push(["文档 ID", doc.id || doc.doc_id || ""]);
  if (doc.sourceId || doc.kb_id) metaRows.push(["知识库", doc.sourceId || doc.kb_id || "-"]);
  if (doc.source_type) metaRows.push(["来源类型", doc.source_type]);
  if (doc.source_uri) metaRows.push(["来源 URI", doc.source_uri]);
  if (doc.tags && doc.tags.length > 0) metaRows.push(["标签", doc.tags.join(", ")]);
  if (doc.createdAt || doc.created_at) metaRows.push(["创建时间", new Date(doc.createdAt || doc.created_at!).toLocaleString()]);
  if (doc.updatedAt || doc.updated_at) metaRows.push(["更新时间", new Date(doc.updatedAt || doc.updated_at!).toLocaleString()]);

  const isMobile = typeof window !== "undefined" && window.innerWidth < 980;

  return (
    <section className="doc-page-shell animate-fade-in">
      {/* ── Top bar ── */}
      <div className="doc-topbar">
        <div className="min-w-0">
          <p className="eyebrow">知识文档</p>
          <h1 className="truncate">{doc.title}</h1>
        </div>
        <button className="btn-ghost shrink-0" onClick={goBack} type="button">
          ← 返回
        </button>
      </div>

      {/* ── Collapsible metadata panel ── */}
      {metaRows.length > 0 && (
        <div className="doc-meta-panel">
          <button
            className="doc-meta-toggle"
            type="button"
            onClick={() => setMetaOpen((v) => !v)}
          >
            <span>文档信息</span>
            <span className={`toggle-arrow ${metaOpen ? "open" : ""}`}>▸</span>
          </button>
          {metaOpen && (
            <div className="doc-meta-body">
              <div className="kv-list" style={{ gridTemplateColumns: "minmax(80px, 0.3fr) 1fr" }}>
                {metaRows.map(([label, value]) => (
                  <>
                    <span>{label}</span>
                    <strong className="text-sm" style={label === "文档 ID" ? { fontFamily: "var(--font-mono, 'JetBrains Mono', monospace)" } : label === "来源 URI" ? { wordBreak: "break-all" } : undefined}>
                      {value}
                    </strong>
                  </>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Body: TOC + Content ── */}
      <div className="doc-body-area">
        {/* Desktop TOC rail */}
        <DocToc headings={headings} activeId={activeId} />

        {/* Content column */}
        <div
          ref={contentRef}
          className="doc-content-column doc-content"
          dangerouslySetInnerHTML={{ __html: htmlContent }}
          onClick={handleContentClick}
        />
      </div>

      {/* Mobile TOC float button */}
      {isMobile && headings.length > 0 && (
        <button
          className="doc-toc-float-btn"
          type="button"
          onClick={() => setTocDrawerOpen(true)}
          aria-label="打开目录"
        >
          ☰
        </button>
      )}

      {/* Mobile TOC drawer */}
      {tocDrawerOpen && (
        <div className="doc-toc-drawer" onClick={() => setTocDrawerOpen(false)}>
          <div className="doc-toc-drawer-inner" onClick={(e) => e.stopPropagation()}>
            <DocToc headings={headings} activeId={activeId} />
          </div>
        </div>
      )}
    </section>
  );
}
