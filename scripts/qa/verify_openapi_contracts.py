from __future__ import annotations

import json
import sys
from pathlib import Path


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.qa.openapi_contracts import OpenApiContract
from scripts.qa.service_matrix import OPENAPI_SPECS, REPRESENTATIVE_RESPONSE_CONTRACTS


def build_summary() -> dict[str, object]:
    contracts = {name: OpenApiContract(spec.path) for name, spec in OPENAPI_SPECS.items()}
    specs_summary: list[dict[str, object]] = []
    for name, spec in OPENAPI_SPECS.items():
        contract = contracts[name]
        contract.assert_required_operations(spec.required_operations)
        specs_summary.append(
            {
                "name": name,
                "path": str(spec.path),
                "title": contract.title,
                "version": contract.version,
                "requiredOperationCount": sum(len(methods) for methods in spec.required_operations.values()),
            }
        )

    representative_checks = []
    for check in REPRESENTATIVE_RESPONSE_CONTRACTS:
        schema = contracts[check.spec_name].response_schema(
            check.path,
            check.method,
            check.status_code,
        )
        representative_checks.append(
            {
                "spec": check.spec_name,
                "path": check.path,
                "method": check.method.upper(),
                "status": check.status_code,
                "hasJsonSchema": schema is not None,
            }
        )

    return {
        "ok": True,
        "specCount": len(specs_summary),
        "specs": specs_summary,
        "representativeResponseContracts": representative_checks,
    }


def main() -> int:
    print(json.dumps(build_summary(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
