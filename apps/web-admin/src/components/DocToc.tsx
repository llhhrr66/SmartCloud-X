import type { DocHeading } from "../lib/markdown-parser";

interface DocTocProps {
  headings: DocHeading[];
  activeId: string;
}

/**
 * DocToc — left-rail table of contents for document viewer.
 * Highlights the current heading via IntersectionObserver scroll-spy.
 */
export function DocToc({ headings, activeId }: DocTocProps) {
  if (headings.length === 0) return null;

  function scrollTo(id: string) {
    const el = document.getElementById(id);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  return (
    <nav className="doc-toc-rail" aria-label="文档目录">
      <div className="doc-toc-title">目录</div>
      {headings.map((h) => (
        <a
          key={h.id}
          className={`doc-toc-item ${h.level === 3 ? "doc-toc-item-h3" : ""} ${
            h.id === activeId ? "doc-toc-item-active" : ""
          }`}
          href={`#${h.id}`}
          onClick={(e) => {
            e.preventDefault();
            scrollTo(h.id);
          }}
        >
          {h.text}
        </a>
      ))}
    </nav>
  );
}
