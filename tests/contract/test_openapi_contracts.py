from __future__ import annotations

from scripts.qa.openapi_contracts import OpenApiContract
from scripts.qa.service_matrix import OPENAPI_SPECS, REPRESENTATIVE_RESPONSE_CONTRACTS


def test_openapi_specs_cover_required_operations() -> None:
    for spec in OPENAPI_SPECS.values():
        contract = OpenApiContract(spec.path)
        assert contract.title
        assert contract.version
        contract.assert_required_operations(spec.required_operations)


def test_representative_response_contracts_resolve_json_schemas() -> None:
    contracts = {name: OpenApiContract(spec.path) for name, spec in OPENAPI_SPECS.items()}
    for check in REPRESENTATIVE_RESPONSE_CONTRACTS:
        schema = contracts[check.spec_name].response_schema(
            check.path,
            check.method,
            check.status_code,
        )
        assert schema is not None, f"missing json schema for {check}"
