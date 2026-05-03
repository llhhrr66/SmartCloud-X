from __future__ import annotations

import json
import sys
from pathlib import Path


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.qa.openapi_contracts import OpenApiContract
from scripts.qa.service_matrix import OPENAPI_SPECS, REPRESENTATIVE_RESPONSE_CONTRACTS


def build_summary() -> dict[str, object]:
    specs_summary: list[dict[str, object]] = []
    representative_checks = []
    failures: list[dict[str, object]] = []

    contracts: dict[str, OpenApiContract] = {}
    for name, spec in OPENAPI_SPECS.items():
        try:
            contract = OpenApiContract(spec.path)
            contract.assert_required_operations(spec.required_operations)
            contracts[name] = contract
            specs_summary.append(
                {
                    "name": name,
                    "path": str(spec.path),
                    "title": contract.title,
                    "version": contract.version,
                    "requiredOperationCount": sum(len(methods) for methods in spec.required_operations.values()),
                }
            )
        except Exception as exc:
            failures.append(
                {
                    "type": "spec",
                    "spec": name,
                    "path": str(spec.path),
                    "detail": str(exc),
                }
            )

    for check in REPRESENTATIVE_RESPONSE_CONTRACTS:
        contract = contracts.get(check.spec_name)
        if contract is None:
            representative_checks.append(
                {
                    "spec": check.spec_name,
                    "path": check.path,
                    "method": check.method.upper(),
                    "status": check.status_code,
                    "hasJsonSchema": False,
                    "passed": False,
                    "detail": "spec validation failed before representative response contract could be checked",
                }
            )
            continue

        try:
            schema = contract.response_schema(
                check.path,
                check.method,
                check.status_code,
            )
            passed = schema is not None
            representative_checks.append(
                {
                    "spec": check.spec_name,
                    "path": check.path,
                    "method": check.method.upper(),
                    "status": check.status_code,
                    "hasJsonSchema": passed,
                    "passed": passed,
                    "detail": None if passed else "response schema missing",
                }
            )
            if not passed:
                failures.append(
                    {
                        "type": "representative-response",
                        "spec": check.spec_name,
                        "path": check.path,
                        "method": check.method.upper(),
                        "status": check.status_code,
                        "detail": "response schema missing",
                    }
                )
        except Exception as exc:
            representative_checks.append(
                {
                    "spec": check.spec_name,
                    "path": check.path,
                    "method": check.method.upper(),
                    "status": check.status_code,
                    "hasJsonSchema": False,
                    "passed": False,
                    "detail": str(exc),
                }
            )
            failures.append(
                {
                    "type": "representative-response",
                    "spec": check.spec_name,
                    "path": check.path,
                    "method": check.method.upper(),
                    "status": check.status_code,
                    "detail": str(exc),
                }
            )

    return {
        "ok": not failures,
        "specCount": len(specs_summary),
        "specs": specs_summary,
        "representativeResponseContracts": representative_checks,
        "failures": failures,
    }


def main() -> int:
    summary = build_summary()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
