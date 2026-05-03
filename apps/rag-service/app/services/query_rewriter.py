from __future__ import annotations

import json
import re
from pathlib import Path

from app.core.config import get_settings
from app.models.rag import ConversationMessage, QueryRewriteResult

DEFAULT_SYNONYM_MAP = {
    "gpu": ["算力", "显卡", "cuda"],
    "账单": ["扣费", "费用", "billing"],
    "发票": ["invoice", "开票"],
    "工单": ["ticket", "支持单"],
    "部署": ["上线", "配置", "install"],
    "faq": ["常见问题", "说明"],
    "icp": ["备案", "实名"],
    "服务器": ["ecs", "云主机", "实例"],
    "域名": ["dns", "解析"],
    "ssl": ["证书", "https"],
    "cdn": ["加速", "分发"],
    "安全组": ["防火墙", "规则"],
}


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for item in re.findall(r"[A-Za-z0-9_+-]+|[一-鿿]+", text.lower()):
        if re.fullmatch(r"[一-鿿]+", item):
            if len(item) <= 4:
                tokens.append(item)
            else:
                tokens.extend(item[index : index + 2] for index in range(len(item) - 1))
        else:
            tokens.append(item)
    return list(dict.fromkeys(token for token in tokens if token.strip()))


class QueryRewriter:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.synonym_map = self._load_synonyms()

    def rewrite(
        self,
        query: str,
        conversation_context: list[ConversationMessage] | None = None,
    ) -> QueryRewriteResult:
        normalized = re.sub(r"\s+", " ", query.strip())
        tokens = tokenize(normalized)
        context_terms = self._extract_context_terms(conversation_context or [], tokens)
        expanded: list[str] = []
        seen: set[str] = set()
        for token in tokens + context_terms:
            for synonym in self.synonym_map.get(token, []):
                if synonym not in seen:
                    expanded.append(synonym)
                    seen.add(synonym)
        rewritten_terms = tokens + context_terms + expanded
        rewritten_query = " ".join(term for term in rewritten_terms if term).strip() or normalized
        return QueryRewriteResult(
            originalQuery=query,
            rewrittenQuery=rewritten_query,
            expandedTerms=expanded,
            contextTerms=context_terms,
        )

    def _extract_context_terms(
        self,
        conversation_context: list[ConversationMessage],
        existing_tokens: list[str],
        limit: int = 8,
    ) -> list[str]:
        seen = set(existing_tokens)
        terms: list[str] = []
        for message in reversed(conversation_context[-6:]):
            for token in tokenize(message.content):
                if token in seen:
                    continue
                if len(token) <= 1:
                    continue
                if re.fullmatch(r"[0-9_+-]+", token):
                    continue
                terms.append(token)
                seen.add(token)
                if len(terms) >= limit:
                    return terms
        return terms

    def _load_synonyms(self) -> dict[str, list[str]]:
        synonym_map = {key.lower(): value[:] for key, value in DEFAULT_SYNONYM_MAP.items()}
        path = self.settings.synonym_file
        if not path:
            return synonym_map
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            return synonym_map
        if not isinstance(data, dict):
            return synonym_map
        for key, value in data.items():
            if not isinstance(key, str) or not isinstance(value, list):
                continue
            cleaned = [str(item).strip() for item in value if str(item).strip()]
            if cleaned:
                synonym_map[key.lower()] = cleaned
        return synonym_map
