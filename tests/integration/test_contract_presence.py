from __future__ import annotations

from pathlib import Path

from scripts.qa.baseline_expectations import (
    FOUNDATION_CONTRACT_EXPECTATIONS,
    KEY_SERVICE_EXPECTATIONS,
    STATUS_DOC_EXPECTATIONS,
    collect_observations,
)
from scripts.qa.check_release_readiness import build_report


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read_text(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


def test_key_service_artifacts_exist_for_current_smartcloud_x_baseline() -> None:
    important_categories = {"auth", "orchestrator", "knowledge", "rag", "web-user", "frontend-sdk"}
    missing = [
        expectation.rel_path
        for expectation in KEY_SERVICE_EXPECTATIONS
        if expectation.category in important_categories and not (REPO_ROOT / expectation.rel_path).exists()
    ]
    assert not missing, f"missing key SmartCloud-X service assets: {missing}"


def test_frozen_contracts_and_status_docs_are_nonempty_markdown_artifacts() -> None:
    for expectation in (*FOUNDATION_CONTRACT_EXPECTATIONS, *STATUS_DOC_EXPECTATIONS):
        content = _read_text(expectation.rel_path)
        assert content.strip(), f"empty markdown artifact: {expectation.rel_path}"
        assert content.lstrip().startswith("#"), f"expected markdown heading in {expectation.rel_path}"


def test_focused_release_readiness_report_passes_with_repo_current_state() -> None:
    report = build_report()

    assert report["ok"], report["failures"]
    summary = report["summary"]
    assert summary["failed"] == 0
    assert summary["total"] >= 60
    assert summary["categories"]["qa"]["passed"] == summary["categories"]["qa"]["total"]
    assert summary["categories"]["status"]["passed"] == summary["categories"]["status"]["total"]
    assert summary["categories"]["contracts"]["passed"] == summary["categories"]["contracts"]["total"]


def test_release_readiness_observations_match_repo_counts_and_root_browser_entry() -> None:
    observations = {item["name"]: item["detail"] for item in collect_observations()}

    assert "test_browser_entry.spec.ts" in observations["tests-e2e-contents"]
    assert int(observations["openapi-document-count"]) >= 9
    assert int(observations["status-document-count"]) >= 7
    assert '"distPresent": true' in observations["web-user-generated-artifacts"]
