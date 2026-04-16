#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

[[ -d "$ROOT/packages/common" ]]
[[ -d "$ROOT/packages/common-schemas" ]]
[[ -d "$ROOT/packages/common-auth" ]]
[[ -f "$ROOT/.env.example" ]]
[[ -f "$ROOT/docs/contracts/supervisor-ownership.md" ]]
[[ -f "$ROOT/openapi/components.openapi.yaml" ]]
[[ -f "$ROOT/openapi/admin-api.openapi.yaml" ]]
[[ -f "$ROOT/openapi/auth-user-service.openapi.yaml" ]]
[[ -f "$ROOT/openapi/business-tools-service.openapi.yaml" ]]
[[ -f "$ROOT/openapi/marketing-service.openapi.yaml" ]]
[[ -f "$ROOT/openapi/research-service.openapi.yaml" ]]
[[ -f "$ROOT/packages/common-schemas/errors/error_codes.yaml" ]]
[[ -f "$ROOT/docs/contracts/change-requests/CHANGE_REQUEST_TEMPLATE.md" ]]

python3 "$ROOT/scripts/validate_foundation.py" --quiet
echo "foundation-ready-check: baseline validated"
