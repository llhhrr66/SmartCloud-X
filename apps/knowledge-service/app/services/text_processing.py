from __future__ import annotations

import math
import re
from collections import Counter

DOMAIN_HINT_PATTERNS = {
    "billing": ["billing", "invoice", "账单", "发票", "扣费", "续费", "退款"],
    "icp": ["备案", "icp", "域名实名", "接入商", "管局"],
    "marketing": ["marketing", "campaign", "推广", "营销", "投放", "海报", "活动"],
    "product": ["product", "gpu", "云主机", "实例", "镜像", "部署", "规格", "产品"],
}

CJK_PUNCT_TRANSLATION = str.maketrans(
    {
        "，": ",",
        "。": ".",
        "；": ";",
        "：": ":",
        "（": "(",
        "）": ")",
        "【": "[",
        "】": "]",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "、": ",",
        "！": "!",
        "？": "?",
    }
)

STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "have",
    "from",
    "your",
    "you",
    "问题",
    "一个",
    "进行",
    "以及",
    "相关",
    "通过",
    "需要",
    "可以",
}


def estimate_tokens(text: str) -> int:
    cjk_chars = len(re.findall(r"[\u3400-\u9fff]", text))
    latin_words = len(re.findall(r"[A-Za-z0-9_+-]+", text))
    punctuation = len(re.findall(r"[^\w\s\u3400-\u9fff]", text))
    estimate = (cjk_chars * 1.5) + latin_words + (punctuation * 0.3)
    return max(1, math.ceil(estimate))


def _tokenize_keywords(text: str) -> list[str]:
    normalized = text.lower()
    tokens: list[str] = []
    tokens.extend(re.findall(r"[A-Za-z0-9_+-]{2,}", normalized))
    for group in re.findall(r"[\u4e00-\u9fff]{2,}", normalized):
        if len(group) <= 4:
            tokens.append(group)
        else:
            tokens.extend(group[index : index + 2] for index in range(len(group) - 1))
            tokens.extend(group[index : index + 3] for index in range(len(group) - 2))
    return tokens


class TextProcessor:
    def clean(self, text: str) -> str:
        cleaned = text.replace("\ufeff", "").replace("\u200b", "").replace("\u200c", "").replace("\u200d", "")
        cleaned = cleaned.translate(CJK_PUNCT_TRANSLATION)
        cleaned = re.sub(r"^\s{0,3}#{1,6}\s*", "", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"\[(?P<label>[^\]]+)\]\((?P<link>[^)]+)\)", r"\g<label>", cleaned)
        cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
        cleaned = re.sub(r"[ \t]+", " ", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        cleaned = re.sub(r" *\n *", "\n", cleaned)
        return cleaned.strip()

    def extract_metadata(self, text: str) -> dict[str, object]:
        normalized = text.lower()
        cjk_chars = len(re.findall(r"[\u3400-\u9fff]", text))
        latin_chars = len(re.findall(r"[A-Za-z]", text))
        if cjk_chars > latin_chars:
            language = "zh-CN"
        elif latin_chars > 0:
            language = "en"
        else:
            language = "unknown"

        domain_hints = [
            name
            for name, patterns in DOMAIN_HINT_PATTERNS.items()
            if any(pattern in normalized for pattern in patterns)
        ]
        entities = sorted(
            set(
                re.findall(r"[A-Z]{2,}(?:[-_][A-Z0-9]+)*", text)
                + re.findall(r"[\u4e00-\u9fff]{2,6}(?:服务|平台|系统|文档|账单|发票|备案)", text)
            )
        )[:12]
        reading_time_minutes = max(1, math.ceil(estimate_tokens(text) / 220))
        return {
            "language": language,
            "domainHints": domain_hints,
            "entityMentions": entities,
            "estimatedReadingMinutes": reading_time_minutes,
        }

    def extract_keywords(
        self,
        text: str,
        max_keywords: int,
        *,
        corpus_texts: list[str] | None = None,
    ) -> list[str]:
        corpus = corpus_texts or []
        document_tokens = [token for token in _tokenize_keywords(text) if token not in STOPWORDS]
        if not document_tokens:
            return []
        document_counts = Counter(document_tokens)
        corpus_token_sets = [set(_tokenize_keywords(item)) for item in corpus if item.strip()]
        doc_freq = Counter()
        for token_set in corpus_token_sets:
            doc_freq.update(token_set)
        corpus_size = max(1, len(corpus_token_sets))
        scored: list[tuple[str, float]] = []
        for token, tf in document_counts.items():
            idf = math.log((corpus_size + 1) / (1 + doc_freq.get(token, 0))) + 1
            bonus = 0.2 if re.fullmatch(r"[\u4e00-\u9fff]{2,4}", token) else 0.0
            scored.append((token, tf * idf + bonus))
        scored.sort(key=lambda item: (-item[1], item[0]))
        return [token for token, _score in scored[:max_keywords]]


class ChunkingService:
    def __init__(self, max_chunk_chars: int, chunk_overlap_chars: int, strategy: str = "fixed") -> None:
        self.max_chunk_chars = max_chunk_chars
        self.chunk_overlap_chars = chunk_overlap_chars
        self.strategy = strategy

    def split(self, content: str) -> list[str]:
        content = content.strip()
        if self.strategy == "paragraph":
            paragraph_chunks = self._split_paragraphs(content)
            if paragraph_chunks:
                return paragraph_chunks
        if len(content) <= self.max_chunk_chars:
            return [content]
        return self._split_fixed(content)

    def _split_fixed(self, content: str) -> list[str]:
        chunks: list[str] = []
        start = 0
        while start < len(content):
            end = min(len(content), start + self.max_chunk_chars)
            chunk = content[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(content):
                break
            start = max(0, end - self.chunk_overlap_chars)
        return chunks

    def _split_paragraphs(self, content: str) -> list[str]:
        normalized = re.sub(r"\r\n?", "\n", content).strip()
        normalized = re.sub(r"\n-{3,}\n", "\n\n", normalized)
        if normalized.startswith("## "):
            header_sections = [item.strip() for item in re.split(r"(?=^##\s+)", normalized, flags=re.MULTILINE) if item.strip()]
        else:
            header_sections = [normalized]

        sections: list[str] = []
        for section in header_sections:
            parts = [item.strip() for item in re.split(r"\n\n+", section) if item.strip()]
            if section.startswith("## ") and parts:
                head, *tail = parts
                sections.append(head)
                sections.extend(tail)
            else:
                sections.extend(parts)

        merged: list[str] = []
        buffer = ""
        for section in sections:
            if section.startswith("## ") and buffer:
                merged.append(buffer)
                buffer = section
                continue
            candidate = f"{buffer}\n\n{section}".strip() if buffer else section
            if len(candidate) <= self.max_chunk_chars:
                buffer = candidate
                continue
            if buffer:
                merged.append(buffer)
                overlap = buffer[-self.chunk_overlap_chars :] if self.chunk_overlap_chars > 0 else ""
                buffer = f"{overlap}\n{section}".strip() if overlap else section
            else:
                buffer = section
            if len(buffer) > self.max_chunk_chars:
                merged.extend(self._split_fixed(buffer))
                buffer = ""
        if buffer:
            merged.append(buffer)
        return [item for item in merged if item]
