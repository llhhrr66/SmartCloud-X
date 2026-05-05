/**
 * Markdown parser for the DocumentViewerPage.
 * Returns structured result with heading list (for TOC) and rendered HTML.
 *
 * Supports: h1/h2/h3, bold, italic, inline code, fenced code blocks (with
 * language tag + copy button), ordered/unordered lists, blockquotes, callouts
 * (> [!TIP/INFO/WARNING/DANGER]), pipe tables, horizontal rules, images, links.
 */

export interface DocHeading {
  id: string;
  text: string;
  level: number; // 1 | 2 | 3
}

export interface ParsedDocument {
  html: string;
  headings: DocHeading[];
}

/** Main entry — parse markdown into HTML + heading list. */
export function parseMarkdown(md: string): ParsedDocument {
  if (!md) return { html: "", headings: [] };

  const headings: DocHeading[] = [];
  const seenIds = new Map<string, number>();

  const lines = md.split("\n");
  const htmlLines: string[] = [];
  let inCodeBlock = false;
  let codeLang = "";
  let codeBlockContent: string[] = [];
  let inUl = false;
  let inOl = false;
  let inBlockquote = false;
  let blockquoteLines: string[] = [];
  let inCallout = false;
  let calloutType = "";
  let calloutLines: string[] = [];
  let inTable = false;
  let tableRows: string[][] = [];
  let tableIsFirstRow = true;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // ── Code block toggle ──
    if (line.startsWith("```")) {
      if (inCodeBlock) {
        closeList();
        closeBlockquote();
        closeCallout();
        closeTable();
        const rawCode = escapeHtml(codeBlockContent.join("\n"));
        const langBadge = codeLang
          ? `<span class="doc-code-lang">${escapeHtml(codeLang)}</span>`
          : "";
        htmlLines.push(
          `<div class="doc-code-wrap">${langBadge}<pre class="doc-code-block"><code>${rawCode}</code><button class="doc-copy-btn" type="button">复制</button></pre></div>`,
        );
        codeBlockContent = [];
        codeLang = "";
        inCodeBlock = false;
      } else {
        closeList();
        closeBlockquote();
        closeCallout();
        closeTable();
        inCodeBlock = true;
        codeLang = line.slice(3).trim();
      }
      continue;
    }

    if (inCodeBlock) {
      codeBlockContent.push(line);
      continue;
    }

    // ── Blockquote / Callout ──
    const bqMatch = line.match(/^>\s?(.*)$/);
    if (bqMatch) {
      closeList();
      closeTable();
      const content = bqMatch[1];
      // Check for callout syntax: > [!TIP], > [!INFO], > [!WARNING], > [!DANGER]
      const calloutMatch = content.match(/^\[!(TIP|INFO|WARNING|DANGER)\]\s*(.*)$/i);
      if (calloutMatch) {
        // If already in a different block, close it
        closeBlockquote();
        closeCallout();
        calloutType = calloutMatch[1].toUpperCase();
        inCallout = true;
        calloutLines = [calloutMatch[2]];
      } else if (inCallout) {
        calloutLines.push(content);
      } else {
        if (!inBlockquote) {
          inBlockquote = true;
          blockquoteLines = [];
        }
        blockquoteLines.push(content);
      }
      continue;
    }

    // Non-blockquote line — close any open blockquote/callout
    if (inBlockquote) closeBlockquote();
    if (inCallout) closeCallout();

    // ── Blank line ──
    if (line.trim() === "") {
      closeList();
      closeTable();
      continue;
    }

    // ── Horizontal rule ──
    if (/^[-*_]{3,}\s*$/.test(line.trim())) {
      closeList();
      closeTable();
      htmlLines.push(`<hr class="doc-hr" />`);
      continue;
    }

    // ── Headers ──
    const h3Match = line.match(/^### (.+)$/);
    if (h3Match) {
      closeList();
      closeTable();
      const { id, text } = emitHeading(h3Match[1], 3, headings, seenIds);
      htmlLines.push(`<h3 class="doc-h3" id="${id}">${inlineFormat(text)}</h3>`);
      continue;
    }
    const h2Match = line.match(/^## (.+)$/);
    if (h2Match) {
      closeList();
      closeTable();
      const { id, text } = emitHeading(h2Match[1], 2, headings, seenIds);
      htmlLines.push(`<h2 class="doc-h2" id="${id}">${inlineFormat(text)}</h2>`);
      continue;
    }
    const h1Match = line.match(/^# (.+)$/);
    if (h1Match) {
      closeList();
      closeTable();
      const { id, text } = emitHeading(h1Match[1], 1, headings, seenIds);
      htmlLines.push(`<h1 class="doc-h1" id="${id}">${inlineFormat(text)}</h1>`);
      continue;
    }

    // ── Unordered list ──
    const ulMatch = line.match(/^[-*] (.+)$/);
    if (ulMatch) {
      closeOl();
      closeTable();
      if (!inUl) {
        htmlLines.push(`<ul class="doc-list">`);
        inUl = true;
      }
      htmlLines.push(`<li>${inlineFormat(ulMatch[1])}</li>`);
      continue;
    }

    // ── Ordered list ──
    const olMatch = line.match(/^\d+\.\s+(.+)$/);
    if (olMatch) {
      closeUl();
      closeTable();
      if (!inOl) {
        htmlLines.push(`<ol class="doc-list-ordered">`);
        inOl = true;
      }
      htmlLines.push(`<li>${inlineFormat(olMatch[1])}</li>`);
      continue;
    }

    // ── Table rows (pipe-separated) ──
    if (line.includes("|") && line.trim().startsWith("|")) {
      closeList();
      const cells = line
        .split("|")
        .filter((_, idx, arr) => idx > 0 && idx < arr.length - 1)
        .map((c) => c.trim());
      // Skip separator row (--- or :---:)
      if (cells.every((c) => /^[-:]+$/.test(c))) {
        tableIsFirstRow = false;
        continue;
      }
      if (!inTable) {
        inTable = true;
        tableRows = [];
        tableIsFirstRow = true;
      }
      tableRows.push(cells);
      tableIsFirstRow = false;
      continue;
    }

    // ── Paragraph ──
    closeList();
    closeTable();
    htmlLines.push(`<p class="doc-paragraph">${inlineFormat(line)}</p>`);
  }

  // Close any remaining open blocks
  if (inCodeBlock) {
    const rawCode = escapeHtml(codeBlockContent.join("\n"));
    const langBadge = codeLang
      ? `<span class="doc-code-lang">${escapeHtml(codeLang)}</span>`
      : "";
    htmlLines.push(
      `<div class="doc-code-wrap">${langBadge}<pre class="doc-code-block"><code>${rawCode}</code><button class="doc-copy-btn" type="button">复制</button></pre></div>`,
    );
  }
  closeList();
  closeBlockquote();
  closeCallout();
  closeTable();

  return { html: htmlLines.join("\n"), headings };

  // ── Helper closures ──

  function closeList() {
    closeUl();
    closeOl();
  }
  function closeUl() {
    if (inUl) {
      htmlLines.push("</ul>");
      inUl = false;
    }
  }
  function closeOl() {
    if (inOl) {
      htmlLines.push("</ol>");
      inOl = false;
    }
  }
  function closeBlockquote() {
    if (inBlockquote) {
      const content = blockquoteLines.map((l) => inlineFormat(l)).join("<br />");
      htmlLines.push(`<blockquote class="doc-blockquote">${content}</blockquote>`);
      inBlockquote = false;
      blockquoteLines = [];
    }
  }
  function closeCallout() {
    if (inCallout) {
      const typeClass = `doc-callout-${calloutType.toLowerCase()}`;
      const titleMap: Record<string, string> = {
        TIP: "💡 提示",
        INFO: "ℹ️ 信息",
        WARNING: "⚠️ 注意",
        DANGER: "🚫 危险",
      };
      const title = titleMap[calloutType] ?? calloutType;
      const body = calloutLines
        .filter((l) => l.trim())
        .map((l) => inlineFormat(l))
        .join("<br />");
      htmlLines.push(
        `<div class="doc-callout ${typeClass}"><div class="doc-callout-title">${title}</div><div class="doc-callout-body">${body}</div></div>`,
      );
      inCallout = false;
      calloutType = "";
      calloutLines = [];
    }
  }
  function closeTable() {
    if (!inTable) return;
    if (tableRows.length === 0) {
      inTable = false;
      return;
    }
    const headerRow = tableRows[0];
    const bodyRows = tableRows.slice(1);
    const thCells = headerRow.map((c) => `<th>${inlineFormat(c)}</th>`).join("");
    const tbody = bodyRows
      .map((row) => `<tr>${row.map((c) => `<td>${inlineFormat(c)}</td>`).join("")}</tr>`)
      .join("\n");
    htmlLines.push(
      `<table class="doc-table"><thead><tr>${thCells}</tr></thead><tbody>${tbody}</tbody></table>`,
    );
    inTable = false;
    tableRows = [];
  }
}

/** Generate a heading ID, track duplicates. */
function emitHeading(
  raw: string,
  level: number,
  headings: DocHeading[],
  seenIds: Map<string, number>,
): { id: string; text: string } {
  // Strip inline formatting for ID generation
  const text = raw.replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .trim();

  // Generate slug — preserve CJK characters, replace whitespace/punctuation with hyphens
  let id = text
    .replace(/[\s+/\\^$=!@#%&*(){}[\]|;:'",.<>?]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    .toLowerCase();

  if (!id) id = `heading-${headings.length + 1}`;

  // Deduplicate
  const count = seenIds.get(id) ?? 0;
  seenIds.set(id, count + 1);
  if (count > 0) id = `${id}-${count + 1}`;

  headings.push({ id, text, level });
  return { id, text };
}

/** Inline formatting: bold, italic, inline code, images, links. */
function inlineFormat(text: string): string {
  // Images (before links, since ![...](...) contains [...](...))
  text = text.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, '<img class="doc-img" src="$2" alt="$1" />');
  // Bold
  text = text.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  // Italic
  text = text.replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g, "<em>$1</em>");
  // Inline code
  text = text.replace(/`([^`]+)`/g, '<code class="doc-inline-code">$1</code>');
  // Links
  text = text.replace(
    /\[([^\]]+)\]\(([^)]+)\)/g,
    '<a href="$2" class="doc-link" target="_blank" rel="noopener noreferrer">$1</a>',
  );
  return text;
}

/** Escape HTML entities for code blocks. */
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
