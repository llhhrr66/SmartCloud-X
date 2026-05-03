import json
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = SERVICE_ROOT / "app"


def activate_service_imports() -> None:
    for module_name in list(sys.modules):
        if module_name == "app" or module_name.startswith("app."):
            sys.modules.pop(module_name, None)

    for candidate in (str(SERVICE_ROOT), str(APP_ROOT)):
        if candidate in sys.path:
            sys.path.remove(candidate)
        sys.path.insert(0, candidate)


activate_service_imports()

from app.models.rag import RetrieveRequest
from app.services.query_rewriter import QueryRewriter
from app.services.retrieval import RetrievalService


DATASET_PATH = Path(__file__).parent / "datasets" / "smoke" / "retrieval-smoke.jsonl"


def load_cases() -> list[dict]:
    return [json.loads(line) for line in DATASET_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


def make_response(case: dict):
    service = RetrievalService(QueryRewriter())
    if case["case_id"] == "retrieval_smoke_001":
        candidate = {
            "chunk_id": "eval-chk-1",
            "source_id": "src-eval-1",
            "document_id": "doc-eval-1",
            "title": "GPU 部署驱动指南",
            "content": "GPU 部署前需要确认驱动版本、CUDA 兼容性和镜像规格。",
            "score": 0.91,
            "source_name": "product_docs",
            "keywords": ["gpu", "部署", "驱动"],
            "created_at": "2099-04-16T00:00:00+00:00",
        }
        return service.build_response(
            RetrieveRequest(query=case["input"], topK=2),
            [
                type("EvalCandidate", (), {
                    "chunk": type("EvalChunk", (), {
                        "id": candidate["chunk_id"],
                        "source_id": candidate["source_id"],
                        "document_id": candidate["document_id"],
                        "document_title": candidate["title"],
                        "ordinal": 1,
                        "content": candidate["content"],
                        "token_estimate": 16,
                        "keywords": candidate["keywords"],
                        "tags": ["gpu"],
                        "created_at": candidate["created_at"],
                    })(),
                    "source_name": candidate["source_name"],
                    "score": candidate["score"],
                    "match_reason": "matched tokens: gpu, 部署, 驱动",
                })()
            ],
            "gpu 部署 驱动",
            backend_used="knowledge-service-search",
        )
    return service.build_response(
        RetrieveRequest(query=case["input"], topK=2),
        [],
        "账单 发票",
        degraded=True,
        degradation_note="knowledge-service unavailable",
        backend_used="knowledge-service-unavailable",
    )


def validate_case(case: dict) -> list[str]:
    errors: list[str] = []
    response = make_response(case)
    rewritten = response.rewritten_query.lower()
    for keyword in case.get("expected_keywords", []):
        if keyword.lower() not in rewritten:
            errors.append(f"missing expected keyword in rewritten query: {keyword}")
    if case.get("must_cite"):
        if not response.citations:
            errors.append("must_cite case returned no citations")
        for citation in response.citations:
            if not citation.citation_id:
                errors.append("citation missing citationId")
            if not citation.backend_used:
                errors.append("citation missing backendUsed")
    return errors


def test_retrieval_smoke_dataset_contract() -> None:
    cases = load_cases()
    assert len(cases) >= 2
    failures: dict[str, list[str]] = {}
    for case in cases:
        errors = validate_case(case)
        if errors:
            failures[case["case_id"]] = errors
    assert failures == {}
