from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.qa.check_release_readiness import build_report as build_focused_readiness_report
from scripts.qa.verify_openapi_contracts import build_summary


REPO_ROOT = Path(__file__).resolve().parents[2]


REQUIRED_ARTIFACTS = (
    "tests/contract/test_openapi_contracts.py",
    "tests/integration/test_auth_marketing_research_flow.py",
    "tests/integration/test_contract_presence.py",
    "tests/integration/test_error_path_smoke.py",
    "tests/integration/test_orchestrator_smoke.py",
    "tests/integration/test_service_smoke.py",
    "tests/e2e/package.json",
    "tests/e2e/playwright.root.config.ts",
    "tests/e2e/test_browser_entry.spec.ts",
    "tests/e2e/test_ui_smoke.py",
    "scripts/qa/qa_env.sh",
    "scripts/qa/openapi_contracts.py",
    "scripts/qa/baseline_expectations.py",
    "scripts/qa/check_release_readiness.py",
    "scripts/qa/infra_persistence_matrix.py",
    "scripts/qa/project_smoke.py",
    "scripts/qa/run_full_stack_validation.sh",
    "scripts/qa/verify_openapi_contracts.py",
    "scripts/qa/run_local_validation.sh",
    "scripts/qa/run_smoke.sh",
    "docs/runbooks/local-validation.md",
    "docs/runbooks/release-readiness.md",
    "docs/reviews/integration-qa-baseline.md",
    "docs/reviews/known-issues.md",
    "docs/reviews/2026-04-16-integration-qa-baseline-review.md",
    "docs/status/supervisor-integration-qa-status.md",
    "logs/supervisor-integration-qa/progress.log",
    "logs/supervisor-integration-qa/blockers.log",
    "logs/supervisor-integration-qa/decisions.log",
    "logs/supervisor-integration-qa/state.json",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check QA release-readiness artifacts.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail when open critical/high issues remain in docs/reviews/known-issues.md.",
    )
    return parser.parse_args()


def parse_known_issues(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []

    rows: list[dict[str, str]] = []
    pattern = re.compile(r"^\|([^|]+)\|([^|]+)\|([^|]+)\|([^|]+)\|([^|]+)\|$")
    for line in path.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line.strip())
        if not match:
            continue
        cells = [cell.strip() for cell in match.groups()]
        if cells[0].lower() == "id" or cells[0].startswith("---"):
            continue
        rows.append(
            {
                "id": cells[0],
                "severity": cells[1].lower(),
                "status": cells[2].lower(),
                "area": cells[3],
                "summary": cells[4],
            }
        )
    return rows


def build_readiness_report() -> dict[str, object]:
    artifact_report = []
    missing = []
    for rel_path in REQUIRED_ARTIFACTS:
        exists = (REPO_ROOT / rel_path).exists()
        artifact_report.append({"path": rel_path, "exists": exists})
        if not exists:
            missing.append(rel_path)

    known_issues = parse_known_issues(REPO_ROOT / "docs" / "reviews" / "known-issues.md")
    focused_readiness = build_focused_readiness_report()
    return {
        "ok": not missing,
        "missingArtifacts": missing,
        "artifacts": artifact_report,
        "focusedReadiness": focused_readiness,
        "infraPersistence": focused_readiness.get("focusAreas", {}).get("infraPersistence"),
        "openapi": build_summary(),
        "knownIssues": known_issues,
    }


def main() -> int:
    args = parse_args()
    report = build_readiness_report()
    blocking_known_issues = [
        issue
        for issue in report["knownIssues"]
        if issue["status"] in {"open", "accepted-risk"}
        and issue["severity"] in {"critical", "high"}
    ]
    report["blockingKnownIssues"] = blocking_known_issues
    report["ok"] = (
        bool(report["ok"])
        and bool(report["focusedReadiness"]["ok"])
        and (not args.strict or not blocking_known_issues)
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
