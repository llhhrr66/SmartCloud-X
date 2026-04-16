#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.qa.baseline_expectations import collect_all_checks, collect_observations



def build_report() -> dict[str, object]:
    checks = collect_all_checks()
    failures = [check for check in checks if not check["passed"]]
    category_totals = Counter(check["category"] for check in checks)
    category_passed = Counter(check["category"] for check in checks if check["passed"])
    categories = {
        category: {
            "passed": category_passed.get(category, 0),
            "total": total,
        }
        for category, total in sorted(category_totals.items())
    }
    return {
        "ok": not failures,
        "summary": {
            "passed": len(checks) - len(failures),
            "failed": len(failures),
            "total": len(checks),
            "categories": categories,
        },
        "checks": checks,
        "failures": failures,
        "observations": collect_observations(),
    }



def main() -> int:
    report = build_report()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
