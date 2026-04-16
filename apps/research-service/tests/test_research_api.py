from datetime import timedelta


def _user_headers(
    token_codec,
    *permissions: str,
    user_id: str = "u_10001",
    tenant_id: str = "default",
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    token = token_codec.issue_access_token(
        subject_type="user",
        subject_id=user_id,
        tenant_id=tenant_id,
        roles=["user"],
        permissions=list(permissions),
    ).token
    headers = {"Authorization": f"Bearer {token}"}
    if extra:
        headers.update(extra)
    return headers


def test_create_research_task_and_poll_completed_detail(client, token_codec) -> None:
    response = client.post(
        "/api/v1/research/tasks",
        headers=_user_headers(token_codec, "user:research.write", extra={"Idempotency-Key": "research-req-000"}),
        json={
            "topic": "LangGraph vs CrewAI",
            "scope": "客服编排能力对比",
            "depth": "standard",
            "output_format": "markdown",
            "reference_urls": ["https://docs.langchain.com/oss/python/langgraph/overview"],
        },
    )
    assert response.status_code == 202
    payload = response.json()["data"]
    assert payload["status"] == "queued"

    detail = client.get(
        f"/api/v1/research/tasks/{payload['task_id']}",
        headers=_user_headers(token_codec, "user:research.read"),
    )
    assert detail.status_code == 200
    detail_data = detail.json()["data"]
    assert detail_data["status"] == "completed"
    assert detail_data["progress"] == 100
    assert detail_data["report_file_id"].startswith("file_report_")


def test_research_status_and_result_alias_routes_return_placeholder_outputs(client, token_codec) -> None:
    response = client.post(
        "/api/v1/research/tasks",
        headers=_user_headers(
            token_codec,
            "user:research.write",
            "user:research.read",
            extra={"Idempotency-Key": "research-req-010"},
        ),
        json={
            "topic": "云客服行业调研",
            "scope": "竞品和落地建议",
            "depth": "deep",
            "output_format": "markdown",
            "reference_urls": [],
        },
    )
    assert response.status_code == 202
    task_id = response.json()["data"]["task_id"]

    status = client.get(
        f"/api/v1/research/tasks/{task_id}/status",
        headers=_user_headers(token_codec, "user:research.read"),
    )
    assert status.status_code == 200
    status_data = status.json()["data"]
    assert status_data["status"] == "completed"
    assert status_data["result_ready"] is True

    result = client.get(
        f"/api/v1/research/tasks/{task_id}/result",
        headers=_user_headers(token_codec, "user:research.read"),
    )
    assert result.status_code == 200
    result_data = result.json()["data"]
    assert result_data["report_file_id"].startswith("file_report_")
    assert result_data["download_url"].startswith("https://downloads.smartcloud.local/research/")
    assert result_data["preview_text"].startswith("# 云客服行业调研")

    report = client.get(
        f"/api/v1/research/tasks/{task_id}/report",
        headers=_user_headers(token_codec, "user:research.read"),
    )
    assert report.status_code == 200
    assert report.json()["data"] == result_data


def test_research_task_can_surface_running_state_before_auto_completion(
    client,
    token_codec,
    service_modules,
    monkeypatch,
) -> None:
    monkeypatch.setenv("RESEARCH_SERVICE_AUTO_COMPLETE_SECONDS", "10")
    service_modules["config"].get_settings.cache_clear()

    response = client.post(
        "/api/v1/research/tasks",
        headers=_user_headers(
            token_codec,
            "user:research.write",
            "user:research.read",
            extra={"Idempotency-Key": "research-req-running"},
        ),
        json={
            "topic": "异步研究进度",
            "scope": "验证运行中状态",
            "depth": "standard",
            "output_format": "markdown",
            "reference_urls": [],
        },
    )
    assert response.status_code == 202
    task_id = response.json()["data"]["task_id"]

    store = service_modules["store"].get_research_store()
    task = store._snapshot.tasks[0]
    task.created_at = (service_modules["models"].utc_now() - timedelta(seconds=5)).isoformat()
    task.updated_at = task.created_at
    store._persist()

    running = client.get(
        f"/api/v1/research/tasks/{task_id}",
        headers=_user_headers(token_codec, "user:research.read"),
    )
    assert running.status_code == 200
    running_data = running.json()["data"]
    assert running_data["status"] == "running"
    assert 15 <= running_data["progress"] < 100
    assert running_data["started_at"] is not None
    assert running_data["report_file_id"] is None

    running_result = client.get(
        f"/api/v1/research/tasks/{task_id}/result",
        headers=_user_headers(token_codec, "user:research.read"),
    )
    assert running_result.status_code == 200
    assert running_result.json()["data"]["result_ready"] is False

    task = store._snapshot.tasks[0]
    task.created_at = (service_modules["models"].utc_now() - timedelta(seconds=11)).isoformat()
    task.updated_at = task.created_at
    store._persist()

    completed = client.get(
        f"/api/v1/research/tasks/{task_id}",
        headers=_user_headers(token_codec, "user:research.read"),
    )
    assert completed.status_code == 200
    assert completed.json()["data"]["status"] == "completed"
    assert completed.json()["data"]["report_file_id"].startswith("file_report_")


def test_research_task_creation_requires_idempotency_key(client, token_codec) -> None:
    response = client.post(
        "/api/v1/research/tasks",
        headers=_user_headers(token_codec, "user:research.write"),
        json={
            "topic": "缺少幂等键",
            "scope": "验证请求头校验",
            "depth": "lite",
            "output_format": "markdown",
            "reference_urls": [],
        },
    )
    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == 4001001
    assert payload["error"]["field"] == "Idempotency-Key"


def test_research_task_idempotency_replays_first_acceptance(client, token_codec) -> None:
    headers = {
        **_user_headers(token_codec, "user:research.write", "user:research.read"),
        "Idempotency-Key": "research-req-001",
    }
    body = {
        "topic": "GPU 云主机选型",
        "scope": "生产环境建议",
        "depth": "deep",
        "output_format": "markdown",
        "reference_urls": [],
    }
    first = client.post("/api/v1/research/tasks", headers=headers, json=body)
    second = client.post("/api/v1/research/tasks", headers=headers, json=body)

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["data"] == second.json()["data"]

    listing = client.get(
        "/api/v1/research/tasks?page=1&page_size=20",
        headers=_user_headers(token_codec, "user:research.read"),
    )
    assert listing.status_code == 200
    assert listing.json()["data"]["total"] == 1


def test_research_task_idempotency_conflict_returns_409(client, token_codec) -> None:
    headers = {
        **_user_headers(token_codec, "user:research.write"),
        "Idempotency-Key": "research-req-002",
    }
    first = client.post(
        "/api/v1/research/tasks",
        headers=headers,
        json={
            "topic": "A",
            "scope": "范围A",
            "depth": "lite",
            "output_format": "markdown",
            "reference_urls": [],
        },
    )
    assert first.status_code == 202

    conflict = client.post(
        "/api/v1/research/tasks",
        headers=headers,
        json={
            "topic": "B",
            "scope": "范围B",
            "depth": "deep",
            "output_format": "pdf",
            "reference_urls": [],
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == 4090001


def test_research_task_idempotency_is_scoped_per_user(client, token_codec) -> None:
    first = client.post(
        "/api/v1/research/tasks",
        headers=_user_headers(
            token_codec,
            "user:research.write",
            user_id="u_10001",
            extra={"Idempotency-Key": "research-shared-key"},
        ),
        json={
            "topic": "共享幂等键",
            "scope": "验证按用户隔离",
            "depth": "lite",
            "output_format": "markdown",
            "reference_urls": [],
        },
    )
    second = client.post(
        "/api/v1/research/tasks",
        headers=_user_headers(
            token_codec,
            "user:research.write",
            user_id="u_20002",
            extra={"Idempotency-Key": "research-shared-key"},
        ),
        json={
            "topic": "共享幂等键",
            "scope": "验证按用户隔离",
            "depth": "lite",
            "output_format": "markdown",
            "reference_urls": [],
        },
    )

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["data"]["task_id"] != second.json()["data"]["task_id"]


def test_research_tasks_and_idempotency_are_tenant_scoped(client, token_codec) -> None:
    body = {
        "topic": "多租户调研",
        "scope": "验证任务隔离",
        "depth": "lite",
        "output_format": "markdown",
        "reference_urls": [],
    }
    first = client.post(
        "/api/v1/research/tasks",
        headers=_user_headers(
            token_codec,
            "user:research.write",
            user_id="u_10001",
            tenant_id="tenant-a",
            extra={"Idempotency-Key": "research-tenant-key"},
        ),
        json=body,
    )
    second = client.post(
        "/api/v1/research/tasks",
        headers=_user_headers(
            token_codec,
            "user:research.write",
            user_id="u_10001",
            tenant_id="tenant-b",
            extra={"Idempotency-Key": "research-tenant-key"},
        ),
        json=body,
    )

    assert first.status_code == 202
    assert second.status_code == 202
    first_task_id = first.json()["data"]["task_id"]
    second_task_id = second.json()["data"]["task_id"]
    assert first_task_id != second_task_id

    tenant_a_listing = client.get(
        "/api/v1/research/tasks?page=1&page_size=20",
        headers=_user_headers(token_codec, "user:research.read", tenant_id="tenant-a"),
    )
    tenant_b_listing = client.get(
        "/api/v1/research/tasks?page=1&page_size=20",
        headers=_user_headers(token_codec, "user:research.read", tenant_id="tenant-b"),
    )
    assert tenant_a_listing.status_code == 200
    assert tenant_b_listing.status_code == 200
    assert [item["task_id"] for item in tenant_a_listing.json()["data"]["items"]] == [first_task_id]
    assert [item["task_id"] for item in tenant_b_listing.json()["data"]["items"]] == [second_task_id]

    cross_tenant_detail = client.get(
        f"/api/v1/research/tasks/{first_task_id}",
        headers=_user_headers(token_codec, "user:research.read", tenant_id="tenant-b"),
    )
    assert cross_tenant_detail.status_code == 404


def test_research_task_listing_completes_all_visible_tasks(client, token_codec) -> None:
    for topic in ("LangGraph", "Phoenix"):
        created = client.post(
            "/api/v1/research/tasks",
            headers=_user_headers(
                token_codec,
                "user:research.write",
                extra={"Idempotency-Key": f"research-listing-{topic}"},
            ),
            json={
                "topic": topic,
                "scope": "平台能力评估",
                "depth": "standard",
                "output_format": "markdown",
                "reference_urls": [],
            },
        )
        assert created.status_code == 202

    listing = client.get(
        "/api/v1/research/tasks?page=1&page_size=20",
        headers=_user_headers(token_codec, "user:research.read"),
    )
    assert listing.status_code == 200
    items = listing.json()["data"]["items"]
    assert len(items) == 2
    assert all(item["status"] == "completed" for item in items)
    assert all(item["progress"] == 100 for item in items)
    assert all(item["report_file_id"].startswith("file_report_") for item in items)


def test_research_routes_require_valid_user_permissions(client, token_codec) -> None:
    unauthorized = client.get("/api/v1/research/tasks")
    assert unauthorized.status_code == 401

    forbidden = client.get(
        "/api/v1/research/tasks",
        headers=_user_headers(token_codec, "user:marketing.read"),
    )
    assert forbidden.status_code == 403


def test_research_routes_reject_refresh_like_tokens(client, token_codec) -> None:
    access = token_codec.issue_access_token(
        subject_type="user",
        subject_id="u_10001",
        tenant_id="default",
        roles=["user"],
        permissions=["user:research.read"],
    )
    refresh_like_claims = dict(access.claims)
    refresh_like_claims["token_type"] = "refresh"
    refresh_like_token = token_codec._encode(refresh_like_claims)  # type: ignore[attr-defined]

    response = client.get(
        "/api/v1/research/tasks",
        headers={"Authorization": f"Bearer {refresh_like_token}"},
    )
    assert response.status_code == 401


def test_research_routes_reject_internal_audience_user_tokens(
    client,
    token_codec,
    service_modules,
) -> None:
    settings = service_modules["config"].get_settings()
    public_access = token_codec.issue_access_token(
        subject_type="user",
        subject_id="u_10001",
        tenant_id="default",
        roles=["user"],
        permissions=["user:research.read"],
    )
    internal_audience_claims = dict(public_access.claims)
    internal_audience_claims["aud"] = settings.internal_auth_audience
    internal_audience_token = token_codec._encode(internal_audience_claims)  # type: ignore[attr-defined]

    response = client.get(
        "/api/v1/research/tasks",
        headers={"Authorization": f"Bearer {internal_audience_token}"},
    )
    assert response.status_code == 401


def test_research_can_opt_into_strict_auth_current_state_validation(
    client,
    token_codec,
    service_modules,
    monkeypatch,
) -> None:
    monkeypatch.setenv("RESEARCH_SERVICE_AUTH_VALIDATION_MODE", "strict")
    monkeypatch.setenv(
        "RESEARCH_SERVICE_AUTH_VALIDATE_TOKEN_URL",
        "http://auth-user-service.local/internal/v1/auth/validate-token",
    )
    service_modules["config"].get_settings.cache_clear()

    def allow(_request, _token, *, settings):
        assert settings.internal_service_name == "research-service"
        return {
            "subject_type": "user",
            "subject_id": "u_10001",
            "tenant_id": "default",
            "roles": ["user"],
            "permissions": ["user:research.read"],
            "expired_at": "2099-01-01T00:00:00+00:00",
        }

    monkeypatch.setattr(service_modules["dependencies"], "_validate_token_with_auth_service", allow)

    response = client.get(
        "/api/v1/research/tasks",
        headers=_user_headers(token_codec, "user:research.read"),
    )
    assert response.status_code == 200


def test_research_strict_auth_validation_rejects_stale_token(
    client,
    token_codec,
    service_modules,
    monkeypatch,
) -> None:
    monkeypatch.setenv("RESEARCH_SERVICE_AUTH_VALIDATION_MODE", "strict")
    monkeypatch.setenv(
        "RESEARCH_SERVICE_AUTH_VALIDATE_TOKEN_URL",
        "http://auth-user-service.local/internal/v1/auth/validate-token",
    )
    service_modules["config"].get_settings.cache_clear()

    def reject(_request, _token, *, settings):
        raise service_modules["models"].ServiceError(401, 4010002, "token is no longer valid")

    monkeypatch.setattr(service_modules["dependencies"], "_validate_token_with_auth_service", reject)

    response = client.get(
        "/api/v1/research/tasks",
        headers=_user_headers(token_codec, "user:research.read"),
    )
    assert response.status_code == 401
    assert response.json()["message"] == "token is no longer valid"


def test_research_strict_auth_uses_validated_permissions_even_when_empty(
    client,
    token_codec,
    service_modules,
    monkeypatch,
) -> None:
    monkeypatch.setenv("RESEARCH_SERVICE_AUTH_VALIDATION_MODE", "strict")
    monkeypatch.setenv(
        "RESEARCH_SERVICE_AUTH_VALIDATE_TOKEN_URL",
        "http://auth-user-service.local/internal/v1/auth/validate-token",
    )
    service_modules["config"].get_settings.cache_clear()

    def allow_without_permissions(_request, _token, *, settings):
        assert settings.internal_service_name == "research-service"
        return {
            "subject_type": "user",
            "subject_id": "u_10001",
            "tenant_id": "default",
            "roles": [],
            "permissions": [],
            "expired_at": "2099-01-01T00:00:00+00:00",
        }

    monkeypatch.setattr(
        service_modules["dependencies"],
        "_validate_token_with_auth_service",
        allow_without_permissions,
    )

    response = client.get(
        "/api/v1/research/tasks",
        headers=_user_headers(token_codec, "user:research.read"),
    )
    assert response.status_code == 403
    assert response.json()["message"] == "missing required permissions"
    assert response.json()["error"]["details"]["missing_permissions"] == ["user:research.read"]


def test_openapi_publishes_status_and_result_routes(client) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/research/tasks/{task_id}/status" in paths
    assert "/api/v1/research/tasks/{task_id}/result" in paths


def test_research_database_persists_tasks_across_store_reload(client, token_codec, service_modules) -> None:
    created = client.post(
        "/api/v1/research/tasks",
        headers=_user_headers(
            token_codec,
            "user:research.write",
            extra={"Idempotency-Key": "research-db-persist"},
        ),
        json={
            "topic": "数据库持久化调研",
            "scope": "验证跨 store reload 持久化",
            "depth": "lite",
            "output_format": "markdown",
            "reference_urls": [],
        },
    )
    assert created.status_code == 202
    task_id = created.json()["data"]["task_id"]

    service_modules["store"].get_research_store.cache_clear()
    reloaded_store = service_modules["store"].get_research_store()
    assert any(item.task_id == task_id for item in reloaded_store._snapshot.tasks)
