from __future__ import annotations

import argparse
import json
import os
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

import httpx


READY_REQUIRED_UPSTREAMS = (
    "auth-user-service",
    "orchestrator-service",
    "tool-hub-service",
    "business-tools-service",
    "knowledge-service",
    "rag-service",
    "marketing-service",
    "research-service",
)


CheckFn = Callable[[], Any]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe SmartCloud-X gateway live acceptance paths.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=10.0)
    return parser.parse_args()


def _build_admin_login_payload() -> dict[str, str]:
    username = os.environ.get("SMARTCLOUD_QA_ADMIN_USERNAME", "admin")
    password = os.environ.get("SMARTCLOUD_QA_ADMIN_PASSWORD")
    captcha_token = os.environ.get("SMARTCLOUD_QA_ADMIN_CAPTCHA_TOKEN", "captcha-ok")
    if not password:
        raise RuntimeError("SMARTCLOUD_QA_ADMIN_PASSWORD is required for admin acceptance checks")
    return {
        "username": username,
        "password": password,
        "captcha_token": captcha_token,
    }


def _build_user_login_payload() -> dict[str, str]:
    account = os.environ.get("SMARTCLOUD_QA_USER_ACCOUNT", "demo@smartcloud.local")
    password = os.environ.get("SMARTCLOUD_QA_USER_PASSWORD")
    if not password:
        raise RuntimeError("SMARTCLOUD_QA_USER_PASSWORD is required for user acceptance checks")
    return {
        "login_type": "password",
        "account": account,
        "password": password,
    }


def _summarize_json(payload: Any) -> Any:
    if isinstance(payload, dict):
        return payload
    return payload


def _normalize_upstream_status(upstream_payload: dict[str, Any]) -> tuple[str | None, list[str]]:
    issues: list[str] = []
    status = upstream_payload.get("status")
    contract = upstream_payload.get("contract")
    http_status = upstream_payload.get("http_status")
    payload_status = upstream_payload.get("payload_status")
    if payload_status is None:
        nested_payload = upstream_payload.get("payload")
        if isinstance(nested_payload, dict):
            payload_status = nested_payload.get("status")

    if contract == "readyz":
        if http_status == 200 and payload_status == "ready":
            return "ready", issues
        issues.append(f"contract={contract!r}")
        issues.append(f"http_status={http_status!r}")
        issues.append(f"payload.status={payload_status!r}")
        return "not_ready", issues

    if status in {"ready", "not_ready"}:
        return status, issues
    if status in {"ok", "degraded"}:
        ready_status_code = upstream_payload.get("ready_status_code")
        if ready_status_code == 200:
            return "ready", issues
        issues.append(f"ready_status_code={ready_status_code!r}")
        return "not_ready", issues
    issues.append(f"status={status!r}")
    return None, issues


def _assert_gateway_readyz_contract(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("gateway /readyz missing data payload")
    if data.get("service") != "gateway-service":
        raise RuntimeError(f"gateway /readyz service mismatch: {data.get('service')!r}")
    if data.get("status") != "ready":
        raise RuntimeError(f"gateway /readyz status={data.get('status')!r} payload={json.dumps(data, ensure_ascii=False)[:800]}")
    not_ready_upstreams = data.get("not_ready_upstreams")
    if not isinstance(not_ready_upstreams, list):
        raise RuntimeError("gateway /readyz not_ready_upstreams must be a list")
    if not_ready_upstreams:
        raise RuntimeError(f"gateway /readyz reports non-ready upstreams: {not_ready_upstreams}")

    upstreams = data.get("upstreams")
    if not isinstance(upstreams, dict):
        raise RuntimeError("gateway /readyz missing upstreams map")

    missing = [name for name in READY_REQUIRED_UPSTREAMS if name not in upstreams]
    if missing:
        raise RuntimeError(f"gateway /readyz missing required upstreams: {missing}")

    failed_contracts: list[str] = []
    for name in READY_REQUIRED_UPSTREAMS:
        upstream_payload = upstreams.get(name)
        if not isinstance(upstream_payload, dict):
            failed_contracts.append(f"{name}: invalid payload")
            continue

        normalized_status, status_issues = _normalize_upstream_status(upstream_payload)
        if normalized_status != "ready":
            details = ", ".join(status_issues) if status_issues else f"status={normalized_status!r}"
            failed_contracts.append(f"{name}: {details}")

        if upstream_payload.get("contract") == "healthz-fallback":
            failed_contracts.append(f"{name}: healthz-fallback")

        if "contract" in upstream_payload or "http_status" in upstream_payload or "payload" in upstream_payload:
            contract = upstream_payload.get("contract")
            http_status = upstream_payload.get("http_status")
            payload_status = None
            nested_payload = upstream_payload.get("payload")
            if isinstance(nested_payload, dict):
                payload_status = nested_payload.get("status")
            if contract != "readyz":
                failed_contracts.append(f"{name}: contract={contract!r}")
            if http_status != 200 or payload_status != "ready":
                failed_contracts.append(
                    f"{name}: http_status={http_status!r}, payload.status={payload_status!r}"
                )
        else:
            ready_status_code = upstream_payload.get("ready_status_code")
            if ready_status_code != 200:
                failed_contracts.append(f"{name}: ready_status_code={ready_status_code!r}")

    if failed_contracts:
        raise RuntimeError("gateway /readyz contract assertions failed: " + "; ".join(failed_contracts))
    return {
        "service": data.get("service"),
        "status": data.get("status"),
        "upstream_count": len(upstreams),
        "required_upstreams": list(READY_REQUIRED_UPSTREAMS),
    }


def _assert_unauthorized_chat(response: httpx.Response) -> dict[str, Any]:
    if response.status_code != 401:
        raise RuntimeError(f"unauthorized chat returned {response.status_code}: {response.text[:800]}")
    payload = response.json()
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if not isinstance(detail, dict):
        raise RuntimeError(f"unauthorized chat missing detail payload: {payload!r}")
    if detail.get("code") != 4010002:
        raise RuntimeError(f"unauthorized chat code mismatch: {detail.get('code')!r}")
    return {"status_code": response.status_code, "detail": detail}


def _assert_sse_chat_response(response: httpx.Response) -> dict[str, Any]:
    if response.status_code != 200:
        raise RuntimeError(f"chat stream returned {response.status_code}: {response.text[:800]}")
    content_type = response.headers.get("content-type", "")
    if not content_type.startswith("text/event-stream"):
        raise RuntimeError(f"chat stream content-type mismatch: {content_type!r}")
    body = response.text
    if "baseline://" in body:
        raise RuntimeError("chat stream contains baseline:// citation placeholder")
    if "event:" not in body and "data:" not in body:
        raise RuntimeError(f"chat stream missing SSE frames: {body[:800]}")
    return {
        "status_code": response.status_code,
        "content_type": content_type,
        "preview": body[:200],
    }


def _extract_first_order_no(orders: dict[str, Any]) -> str:
    data = orders.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("orders_list missing data payload")

    items = data.get("items")
    if not isinstance(items, list):
        raise RuntimeError("orders_list data.items must be a list")

    if not items:
        total = data.get("total")
        raise RuntimeError(
            "orders_list returned empty items; cannot continue refund_create/refund_detail dependent checks"
            f" (total={total!r})"
        )

    first_item = items[0]
    if not isinstance(first_item, dict):
        raise RuntimeError("orders_list first item must be an object")

    order_no = first_item.get("order_no")
    if not isinstance(order_no, str) or not order_no.strip():
        raise RuntimeError("orders_list first item missing non-empty order_no")
    return order_no


def _append_blocked_check(
    grouped_checks: OrderedDict[str, list[dict[str, Any]]],
    group: str,
    name: str,
    reason: str,
) -> None:
    grouped_checks[group].append({"name": name, "passed": False, "blocked": True, "error": reason})


def main() -> int:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    grouped_checks: OrderedDict[str, list[dict[str, Any]]] = OrderedDict(
        (
            ("core_path", []),
            ("tooling_path", []),
            ("object_storage_path", []),
            ("admin_path", []),
        )
    )

    with httpx.Client(base_url=base_url, timeout=args.timeout, trust_env=False) as client:
        def run_check(group: str, name: str, fn: CheckFn) -> Any:
            try:
                result = fn()
                grouped_checks[group].append({"name": name, "passed": True, "result": result})
                return result
            except Exception as exc:  # pragma: no cover - CLI probe
                grouped_checks[group].append({"name": name, "passed": False, "error": str(exc)})
                return None

        def expect_json(method: str, path: str, *, expected_status: int, **kwargs) -> Any:
            response = client.request(method, path, **kwargs)
            if response.status_code != expected_status:
                raise RuntimeError(f"{method} {path} returned {response.status_code}: {response.text[:800]}")
            return response.json()

        def request(method: str, path: str, **kwargs) -> httpx.Response:
            return client.request(method, path, **kwargs)

        run_check("core_path", "healthz", lambda: expect_json("GET", "/healthz", expected_status=200))
        ready = run_check(
            "core_path",
            "readyz",
            lambda: _assert_gateway_readyz_contract(expect_json("GET", "/readyz", expected_status=200)),
        )

        run_check(
            "core_path",
            "chat_requires_auth",
            lambda: _assert_unauthorized_chat(
                request(
                    "POST",
                    "/api/v1/chat/completions",
                    headers={"Accept": "text/event-stream"},
                    json={
                        "user_input": "未登录聊天探针",
                        "stream": True,
                        "scene": "billing",
                        "attachments": [],
                        "context": {"user_id": "u-1", "tenant_id": "tenant-a"},
                    },
                )
            ),
        )

        login = run_check(
            "core_path",
            "user_login",
            lambda: expect_json(
                "POST",
                "/api/v1/auth/login",
                expected_status=200,
                json=_build_user_login_payload(),
            ),
        )
        if not login:
            checks = [item for items in grouped_checks.values() for item in items]
            passed = sum(1 for item in checks if item["passed"])
            total = len(checks)
            print(
                json.dumps(
                    {"score": passed, "total": total, "groups": grouped_checks, "checks": checks},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 1
        access_token = login["data"]["access_token"]
        user_headers = {"Authorization": f"Bearer {access_token}"}

        run_check("core_path", "auth_me", lambda: expect_json("GET", "/api/v1/auth/me", expected_status=200, headers=user_headers))
        session = run_check(
            "core_path",
            "chat_session_create",
            lambda: expect_json(
                "POST",
                "/api/v1/chat/sessions",
                expected_status=200,
                headers=user_headers,
                json={"scene": "billing", "title": "gateway probe", "initial_context": "qa"},
            ),
        )
        if not session:
            checks = [item for items in grouped_checks.values() for item in items]
            passed = sum(1 for item in checks if item["passed"])
            total = len(checks)
            print(
                json.dumps(
                    {"score": passed, "total": total, "groups": grouped_checks, "checks": checks},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 1
        conversation_id = session["data"]["conversation_id"]
        run_check(
            "core_path",
            "chat_stream",
            lambda: _assert_sse_chat_response(
                request(
                    "POST",
                    "/api/v1/chat/completions",
                    headers={**user_headers, "Accept": "text/event-stream"},
                    json={
                        "conversation_id": conversation_id,
                        "message_id": "probe-msg-1",
                        "user_input": "帮我查本月账单",
                        "stream": True,
                        "scene": "billing",
                        "attachments": [],
                        "context": {
                            "user_id": "u-1",
                            "tenant_id": "tenant-a",
                            "channel": "web",
                            "locale": "zh-CN",
                        },
                        "options": {"use_rag": True, "use_tools": True, "max_history_turns": 10},
                    },
                )
            ),
        )
        run_check(
            "core_path",
            "marketing_campaigns",
            lambda: _summarize_json(
                expect_json("GET", "/api/v1/marketing/campaigns", expected_status=200, headers=user_headers)
            ),
        )
        run_check(
            "core_path",
            "research_create",
            lambda: _summarize_json(
                expect_json(
                    "POST",
                    "/api/v1/research/tasks",
                    expected_status=202,
                    headers=user_headers,
                    json={
                        "topic": "SmartCloud-X gateway probe",
                        "scope": "本地联调",
                        "depth": "standard",
                        "output_format": "markdown",
                        "reference_urls": [],
                    },
                )
            ),
        )
        orders = run_check(
            "tooling_path",
            "orders_list",
            lambda: expect_json("GET", "/api/v1/orders", expected_status=200, headers=user_headers),
        )
        order_no = run_check("tooling_path", "orders_seed_required", lambda: _extract_first_order_no(orders or {}))
        if order_no:
            refund = run_check(
                "tooling_path",
                "refund_create",
                lambda: expect_json(
                    "POST",
                    f"/api/v1/orders/{order_no}/refunds",
                    expected_status=200,
                    headers=user_headers,
                    json={
                        "order_no": order_no,
                        "reason": "gateway probe",
                        "amount": "1288.32",
                        "attachments": [],
                    },
                ),
            )
            if refund:
                refund_no = refund["data"]["refund_no"]
                run_check(
                    "tooling_path",
                    "refund_detail",
                    lambda: expect_json("GET", f"/api/v1/refunds/{refund_no}", expected_status=200, headers=user_headers),
                )
        else:
            blocked_reason = (
                "blocked by orders_seed_required: orders_list returned no usable order_no; "
                "refund_create/refund_detail require pre-existing order data"
            )
            _append_blocked_check(grouped_checks, "tooling_path", "refund_create", blocked_reason)
            _append_blocked_check(grouped_checks, "tooling_path", "refund_detail", blocked_reason)
        ticket = run_check(
            "tooling_path",
            "ticket_create",
            lambda: expect_json(
                "POST",
                "/api/v1/tickets",
                expected_status=200,
                headers=user_headers,
                json={
                    "subject": "gateway probe",
                    "content": "请协助确认网关联调",
                    "priority": "medium",
                    "category": "customer_service",
                    "attachments": [],
                },
            ),
        )
        if ticket:
            ticket_no = ticket["data"]["ticket_no"]
            run_check(
                "tooling_path",
                "ticket_reply",
                lambda: expect_json(
                    "POST",
                    f"/api/v1/tickets/{ticket_no}/replies",
                    expected_status=200,
                    headers=user_headers,
                    json={"content": "补充说明", "attachments": []},
                ),
            )
        run_check(
            "tooling_path",
            "icp_material_check",
            lambda: expect_json(
                "POST",
                "/api/v1/icp/materials/check",
                expected_status=200,
                headers=user_headers,
                json={"subject_type": "enterprise", "materials": []},
            ),
        )
        application = run_check(
            "tooling_path",
            "icp_create",
            lambda: expect_json(
                "POST",
                "/api/v1/icp/applications",
                expected_status=200,
                headers=user_headers,
                json={
                    "subject_type": "enterprise",
                    "domain": "probe.smartcloud.local",
                    "website_name": "Gateway Probe",
                    "contacts": ["李雷 138****0001"],
                    "materials": [],
                },
            ),
        )
        if application:
            application_no = application["data"]["application_no"]
            run_check(
                "tooling_path",
                "icp_detail",
                lambda: expect_json(
                    "GET",
                    f"/api/v1/icp/applications/{application_no}",
                    expected_status=200,
                    headers=user_headers,
                ),
            )
        upload_policy = run_check(
            "object_storage_path",
            "file_upload_policy",
            lambda: expect_json(
                "POST",
                "/api/v1/files/upload-policy",
                expected_status=200,
                headers=user_headers,
                json={
                    "file_name": "probe.txt",
                    "size": 16,
                    "mime_type": "text/plain",
                    "biz_type": "chat_attachment",
                },
            ),
        )
        if upload_policy:
            file_id = upload_policy["data"]["file_id"]
            run_check(
                "object_storage_path",
                "file_complete",
                lambda: expect_json(
                    "POST",
                    "/api/v1/files/complete",
                    expected_status=200,
                    headers=user_headers,
                    json={
                        "file_id": file_id,
                        "object_key": upload_policy["data"]["object_key"],
                        "checksum": "probe-checksum",
                        "size": 16,
                    },
                ),
            )
            run_check(
                "object_storage_path",
                "file_detail",
                lambda: expect_json("GET", f"/api/v1/files/{file_id}", expected_status=200, headers=user_headers),
            )

        admin_login = run_check(
            "admin_path",
            "admin_login",
            lambda: expect_json(
                "POST",
                "/api/v1/admin/auth/login",
                expected_status=200,
                json=_build_admin_login_payload(),
            ),
        )
        if admin_login:
            admin_headers = {"Authorization": f"Bearer {admin_login['data']['access_token']}"}
            run_check(
                "admin_path",
                "admin_dashboard",
                lambda: expect_json(
                    "GET",
                    "/api/v1/admin/dashboard/summary",
                    expected_status=200,
                    headers=admin_headers,
                ),
            )

    checks = [item for items in grouped_checks.values() for item in items]
    passed = sum(1 for item in checks if item["passed"])
    total = len(checks)
    print(
        json.dumps(
            {"score": passed, "total": total, "groups": grouped_checks, "checks": checks},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
