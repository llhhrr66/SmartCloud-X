from functools import lru_cache

from app.core.metrics import ANSWER_REQUESTS_TOTAL
from app.core.tracing import start_span
from app.models.rag import AnswerResponse, RetrieveResponse


class AnswerComposer:
    def compose(self, query: str, retrieval: RetrieveResponse, style: str = "brief") -> AnswerResponse:
        with start_span(
            "rag.answer.compose",
            smartcloud_answer_style=style,
            smartcloud_answer_query=query,
            smartcloud_answer_degraded=retrieval.degraded,
            smartcloud_answer_citation_count=len(retrieval.citations),
        ):
            ANSWER_REQUESTS_TOTAL.inc()
            if not retrieval.citations:
                answer = "当前没有检索到可引用知识，建议先在管理后台补充文档后再重试。"
                return AnswerResponse(
                    query=query,
                    rewrittenQuery=retrieval.rewritten_query,
                    backendUsed=retrieval.backend_used,
                    answer=answer,
                    citations=[],
                    coverageNotes=retrieval.coverage_notes,
                    degraded=retrieval.degraded,
                    context=retrieval.context,
                )

            top_citations = retrieval.citations[:3]
            if style == "brief":
                answer = self._brief_answer(query, top_citations, retrieval.context.context_text if retrieval.context else "")
            else:
                answer = self._detailed_answer(query, top_citations, retrieval.context.context_text if retrieval.context else "")
            return AnswerResponse(
                query=query,
                rewrittenQuery=retrieval.rewritten_query,
                backendUsed=retrieval.backend_used,
                answer=answer,
                citations=retrieval.citations,
                coverageNotes=retrieval.coverage_notes,
                degraded=retrieval.degraded,
                context=retrieval.context,
            )

    @staticmethod
    def _brief_answer(query: str, citations, context_text: str) -> str:
        supporting = "；".join(f"{item.document_title} 提到 {item.snippet.rstrip('。.!?；;')}" for item in citations[:2])
        if context_text:
            return f"针对“{query}”，当前知识库优先命中：{supporting}。上下文已按预算整理，可直接供下游 LLM 使用。"
        return f"针对“{query}”，当前知识库优先命中：{supporting}。"

    @staticmethod
    def _detailed_answer(query: str, citations, context_text: str) -> str:
        lines = [f"问题：{query}", "依据："]
        lines.extend(f"{index}. {item.document_title}: {item.snippet.rstrip('。.!?；;')}" for index, item in enumerate(citations, start=1))
        if context_text:
            lines.append("已生成可复用上下文片段。")
        return "\n".join(lines)


@lru_cache(maxsize=1)
def get_answer_composer() -> AnswerComposer:
    return AnswerComposer()
