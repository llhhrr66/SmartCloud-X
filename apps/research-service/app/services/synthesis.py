from __future__ import annotations

import re
from dataclasses import dataclass

from app.models import ResearchCitation, ResearchResult, ResearchSection


@dataclass
class SourceDocument:
    title: str
    url: str
    text: str
    snippet: str = ""


def synthesize_report(
    topic: str,
    scope: str,
    sources: list[SourceDocument],
    *,
    depth: str = "standard",
    output_format: str = "markdown",
) -> ResearchResult:
    keywords = _extract_keywords(topic, scope)
    selected = _select_sentences(sources, keywords, max_sentences=_sentence_limit(depth))
    summary = _build_summary(topic, scope, selected, sources)
    sections = _build_sections(topic, scope, selected, sources, keywords)
    citations = [
        ResearchCitation(title=s.title, url=s.url, snippet=s.snippet or s.text[:200])
        for s in sources
    ]
    return ResearchResult(
        summary=summary,
        sections=sections,
        citations=citations,
        metadata={
            "provider": "pipeline",
            "synthesis": "deterministic-extractive",
            "depth": depth,
            "output_format": output_format,
            "source_count": len(sources),
            "sentence_count": len(selected),
            "keywords": keywords,
        },
    )


def _extract_keywords(topic: str, scope: str) -> list[str]:
    raw = re.split(r"[\s,，。；;：:、/()（）\[\]【】{}]+", f"{topic} {scope}")
    keywords: list[str] = []
    for token in raw:
        t = token.strip("-_—·…")
        if len(t) >= 2 and t not in keywords:
            keywords.append(t)
    return keywords[:10] or [topic[:24]]


def _sentence_limit(depth: str) -> int:
    return {"lite": 5, "standard": 10, "deep": 20}.get(depth, 10)


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？.!?\n])\s*", text)
    return [s.strip() for s in parts if len(s.strip()) >= 8]


def _score_sentence(sentence: str, keywords: list[str]) -> float:
    lower = sentence.lower()
    hits = sum(1 for kw in keywords if kw.lower() in lower)
    return hits / max(len(keywords), 1)


def _select_sentences(
    sources: list[SourceDocument],
    keywords: list[str],
    max_sentences: int,
) -> list[tuple[str, str, str]]:
    candidates: list[tuple[float, str, str, str]] = []
    for src in sources:
        for sent in _split_sentences(src.text):
            score = _score_sentence(sent, keywords)
            candidates.append((score, sent, src.title, src.url))
    candidates.sort(key=lambda x: x[0], reverse=True)
    selected: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for _score, sent, title, url in candidates:
        key = sent[:60]
        if key in seen:
            continue
        seen.add(key)
        selected.append((sent, title, url))
        if len(selected) >= max_sentences:
            break
    return selected


def _build_summary(
    topic: str,
    scope: str,
    selected: list[tuple[str, str, str]],
    sources: list[SourceDocument],
) -> str:
    source_count = len(sources)
    sentence_count = len(selected)
    domains = list({s.url.split("/")[2] for s in sources if "/" in s.url})[:3]
    domain_text = f"，参考来源涵盖 {', '.join(domains)}" if domains else ""
    topic_label = "\u201c" + topic + "\u201d"
    return (
        f"围绕{topic_label}完成了深度研究，共阅读 {source_count} 份资料、"
        f"提取 {sentence_count} 条关键信息{domain_text}。"
    )


def _build_sections(
    topic: str,
    scope: str,
    selected: list[tuple[str, str, str]],
    sources: list[SourceDocument],
    keywords: list[str],
) -> list[ResearchSection]:
    sections: list[ResearchSection] = []
    sections.append(ResearchSection(title="研究范围", content=scope))

    if selected:
        content_lines = [f"- {sent}" for sent, _title, _url in selected[:15]]
        sections.append(ResearchSection(title="关键发现", content="\n".join(content_lines)))
    else:
        topic_label = "\u201c" + topic + "\u201d"
        sections.append(
            ResearchSection(
                title="关键发现",
                content=f"当前未从外部资料中提取到与{topic_label}直接相关的关键句子。",
            )
        )

    if sources:
        ref_lines = [f"- [{s.title}]({s.url})" for s in sources]
        sections.append(ResearchSection(title="参考来源", content="\n".join(ref_lines)))

    sections.append(
        ResearchSection(
            title="建议动作",
            content=f"建议基于以上 {len(keywords)} 个维度进一步验证数据并评估成本。",
        )
    )
    return sections
