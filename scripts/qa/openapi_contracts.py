from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

import jsonschema

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - optional dependency for QA helper
    yaml = None
else:
    class _LenientYamlLoader(yaml.SafeLoader):
        """YAML loader that ignores unknown custom tags used by some specs."""


    def _construct_unknown_tag(loader: _LenientYamlLoader, tag_suffix: str, node: Any) -> Any:
        if isinstance(node, yaml.ScalarNode):
            return loader.construct_scalar(node)
        if isinstance(node, yaml.SequenceNode):
            return loader.construct_sequence(node)
        if isinstance(node, yaml.MappingNode):
            return loader.construct_mapping(node)
        raise TypeError(f"unsupported YAML node type: {node.__class__.__name__}")


    _LenientYamlLoader.add_multi_constructor("!", _construct_unknown_tag)


class ContractValidationError(ValueError):
    """Raised when an OpenAPI contract check fails."""


class OpenApiContract:
    def __init__(self, spec_path: str | Path) -> None:
        self.spec_path = Path(spec_path).resolve()
        self._documents: dict[Path, dict[str, Any]] = {}
        self.document = self._load_document(self.spec_path)

    @property
    def title(self) -> str:
        return str(self.document.get("info", {}).get("title", ""))

    @property
    def version(self) -> str:
        return str(self.document.get("info", {}).get("version", ""))

    def _load_document(self, path: Path) -> dict[str, Any]:
        resolved = path.resolve()
        if resolved not in self._documents:
            self._documents[resolved] = self._parse_document(resolved)
        return self._documents[resolved]

    def _parse_document(self, path: Path) -> dict[str, Any]:
        text = path.read_text(encoding="utf-8")
        if yaml is not None:
            payload = yaml.load(text, Loader=_LenientYamlLoader)
        else:
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ContractValidationError(
                    "PyYAML is not installed and the OpenAPI document is not valid JSON: "
                    f"{path}"
                ) from exc
        if not isinstance(payload, dict):
            raise ContractValidationError(f"OpenAPI document must decode to an object: {path}")
        return payload

    def assert_required_operations(self, required_operations: dict[str, tuple[str, ...]]) -> None:
        for path, methods in required_operations.items():
            for method in methods:
                self.require_operation(path, method)

    def require_operation(self, path: str, method: str) -> dict[str, Any]:
        operations = self.document.get("paths", {})
        if path not in operations:
            raise ContractValidationError(f"missing path {path} in {self.spec_path}")
        operation = operations[path].get(method.lower())
        if operation is None:
            raise ContractValidationError(
                f"missing method {method.upper()} for {path} in {self.spec_path}"
            )
        return operation

    def response_schema(self, path: str, method: str, status_code: int) -> dict[str, Any] | None:
        operation = self.require_operation(path, method)
        responses = operation.get("responses", {})
        status_key = str(status_code)
        if status_key not in responses and "default" in responses:
            status_key = "default"
        if status_key not in responses:
            raise ContractValidationError(
                f"missing response {status_code} for {method.upper()} {path} in {self.spec_path}"
            )

        content = responses[status_key].get("content", {})
        json_content = content.get("application/json")
        if json_content is None:
            return None

        schema = json_content.get("schema")
        if schema is None:
            return None
        return self._normalize_nullable(
            self._expand_refs(schema, current_path=self.spec_path, ref_stack=())
        )

    def validate_response(self, path: str, method: str, status_code: int, payload: Any) -> None:
        schema = self.response_schema(path, method, status_code)
        if schema is None:
            return
        validator_cls = jsonschema.validators.validator_for(schema)
        validator_cls.check_schema(schema)
        validator = validator_cls(schema)
        errors = sorted(validator.iter_errors(payload), key=lambda item: list(item.absolute_path))
        if not errors:
            return
        first_error = errors[0]
        absolute_path = ".".join(str(part) for part in first_error.absolute_path)
        location = absolute_path or "<root>"
        raise ContractValidationError(
            f"{method.upper()} {path} {status_code} failed contract validation at {location}: "
            f"{first_error.message}"
        )

    def _expand_refs(
        self,
        node: Any,
        *,
        current_path: Path,
        ref_stack: tuple[str, ...],
    ) -> Any:
        if isinstance(node, list):
            return [self._expand_refs(item, current_path=current_path, ref_stack=ref_stack) for item in node]

        if not isinstance(node, dict):
            return node

        if "$ref" in node:
            ref = str(node["$ref"])
            if ref in ref_stack:
                return deepcopy(node)
            target, target_path = self._resolve_ref(ref, current_path=current_path)
            expanded = self._expand_refs(target, current_path=target_path, ref_stack=(*ref_stack, ref))
            extras = {
                key: self._expand_refs(value, current_path=current_path, ref_stack=ref_stack)
                for key, value in node.items()
                if key != "$ref"
            }
            if not extras:
                return expanded
            if isinstance(expanded, dict):
                return self._merge_schema_dicts(expanded, extras)
            return expanded

        return {
            key: self._expand_refs(value, current_path=current_path, ref_stack=ref_stack)
            for key, value in node.items()
        }

    def _resolve_ref(self, ref: str, *, current_path: Path) -> tuple[Any, Path]:
        if "#" in ref:
            file_part, pointer = ref.split("#", 1)
        else:
            file_part, pointer = ref, ""

        target_path = (current_path.parent / file_part).resolve() if file_part else current_path.resolve()
        document = self._load_document(target_path)
        if not pointer:
            return deepcopy(document), target_path
        return deepcopy(self._resolve_pointer(document, pointer)), target_path

    def _resolve_pointer(self, document: dict[str, Any], pointer: str) -> Any:
        current: Any = document
        for part in pointer.lstrip("/").split("/"):
            token = part.replace("~1", "/").replace("~0", "~")
            current = current[token]
        return current

    def _merge_schema_dicts(self, base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(base)
        for key, value in overlay.items():
            if key == "required" and isinstance(value, list):
                merged[key] = sorted({*merged.get(key, []), *value})
                continue
            if key == "properties" and isinstance(value, dict):
                properties = deepcopy(merged.get("properties", {}))
                properties.update(value)
                merged["properties"] = properties
                continue
            merged[key] = value
        return merged

    def _normalize_nullable(self, node: Any) -> Any:
        if isinstance(node, list):
            return [self._normalize_nullable(item) for item in node]
        if not isinstance(node, dict):
            return node

        normalized = {
            key: self._normalize_nullable(value)
            for key, value in node.items()
            if key != "nullable"
        }

        if node.get("nullable") is True:
            if isinstance(normalized.get("type"), str):
                normalized["type"] = [normalized["type"], "null"]
            elif isinstance(normalized.get("type"), list) and "null" not in normalized["type"]:
                normalized["type"] = [*normalized["type"], "null"]
            elif "anyOf" in normalized:
                normalized["anyOf"] = [*normalized["anyOf"], {"type": "null"}]
            elif "oneOf" in normalized:
                normalized["oneOf"] = [*normalized["oneOf"], {"type": "null"}]
        return normalized
