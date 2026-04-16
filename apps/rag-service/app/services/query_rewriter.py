import re

from app.models.rag import QueryRewriteResult

SYNONYM_MAP = {
    "gpu": ["算力", "显卡", "cuda"],
    "账单": ["扣费", "费用", "billing"],
    "发票": ["invoice", "开票"],
    "工单": ["ticket", "支持单"],
    "部署": ["上线", "配置", "install"],
    "faq": ["常见问题", "说明"],
    "icp": ["备案", "实名"],
}


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for item in re.findall(r"[A-Za-z0-9_+-]+|[\u4e00-\u9fff]+", text.lower()):
        if re.fullmatch(r"[\u4e00-\u9fff]+", item):
            if len(item) <= 4:
                tokens.append(item)
            else:
                tokens.extend(item[index : index + 2] for index in range(len(item) - 1))
        else:
            tokens.append(item)
    return list(dict.fromkeys(tokens))


class QueryRewriter:
    def rewrite(self, query: str) -> QueryRewriteResult:
        normalized = re.sub(r"\s+", " ", query.strip())
        tokens = tokenize(normalized)
        expanded: list[str] = []
        seen: set[str] = set()
        for token in tokens:
            for synonym in SYNONYM_MAP.get(token, []):
                if synonym not in seen:
                    expanded.append(synonym)
                    seen.add(synonym)
        rewritten_terms = tokens + expanded
        rewritten_query = " ".join(term for term in rewritten_terms if term).strip() or normalized
        return QueryRewriteResult(
            originalQuery=query,
            rewrittenQuery=rewritten_query,
            expandedTerms=expanded,
        )
