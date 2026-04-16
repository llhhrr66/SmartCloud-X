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


def test_campaign_listing_and_copy_generation(client, token_codec) -> None:
    campaigns = client.get(
        "/api/v1/marketing/campaigns?page=1&page_size=20",
        headers=_user_headers(token_codec, "user:marketing.read"),
    )
    assert campaigns.status_code == 200
    data = campaigns.json()["data"]
    assert data["total"] >= 2
    assert all(item["status"] == "published" for item in data["items"])
    first_campaign = data["items"][0]

    copy = client.post(
        "/api/v1/marketing/copy/generate",
        headers=_user_headers(token_codec, "user:marketing.write"),
        json={
            "campaign_id": first_campaign["campaign_id"],
            "topic": "AI 算力起量",
            "audience": "AI 创业团队",
            "tone": "launch",
            "keywords": ["AI 算力", "弹性扩容"],
        },
    )
    assert copy.status_code == 200
    copy_data = copy.json()["data"]
    assert copy_data["headline"].startswith("新品首发")
    assert copy_data["landing_page_url"].startswith("https://")


def test_generated_copy_history_and_detail_are_readable(client, token_codec) -> None:
    created = client.post(
        "/api/v1/marketing/copy/generate",
        headers=_user_headers(token_codec, "user:marketing.write"),
        json={
            "campaign_id": "cmp_gpu_launch_001",
            "topic": "AI 算力起量",
            "audience": "AI 创业团队",
            "tone": "launch",
            "keywords": ["AI 算力", "弹性扩容"],
        },
    )
    assert created.status_code == 200
    copy_id = created.json()["data"]["copy_id"]

    listing = client.get(
        "/api/v1/marketing/copies?page=1&page_size=20&tone=launch",
        headers=_user_headers(token_codec, "user:marketing.read"),
    )
    assert listing.status_code == 200
    list_data = listing.json()["data"]
    assert list_data["total"] == 1
    assert list_data["items"][0]["copy_id"] == copy_id

    detail = client.get(
        f"/api/v1/marketing/copies/{copy_id}",
        headers=_user_headers(token_codec, "user:marketing.read"),
    )
    assert detail.status_code == 200
    assert detail.json()["data"]["copy_id"] == copy_id
    assert detail.json()["data"]["tone"] == "launch"


def test_copy_generation_falls_back_to_campaign_highlights(client, token_codec) -> None:
    created = client.post(
        "/api/v1/marketing/copy/generate",
        headers=_user_headers(token_codec, "user:marketing.write"),
        json={
            "campaign_id": "cmp_gpu_launch_001",
            "topic": "默认关键词",
            "audience": "AI 创业团队",
            "tone": "launch",
            "keywords": [],
        },
    )
    assert created.status_code == 200
    assert created.json()["data"]["keywords"] == ["新品首发", "AI 算力", "弹性扩容"]


def test_user_marketing_routes_do_not_expose_or_generate_draft_campaigns(client, token_codec) -> None:
    draft_listing = client.get(
        "/api/v1/marketing/campaigns?page=1&page_size=20&status=draft",
        headers=_user_headers(token_codec, "user:marketing.read"),
    )
    assert draft_listing.status_code == 200
    assert draft_listing.json()["data"]["items"] == []
    assert draft_listing.json()["data"]["total"] == 0

    copy = client.post(
        "/api/v1/marketing/copy/generate",
        headers=_user_headers(token_codec, "user:marketing.write"),
        json={
            "campaign_id": "cmp_storage_draft_001",
            "topic": "草稿活动",
            "audience": "工程团队",
            "tone": "professional",
            "keywords": [],
        },
    )
    assert copy.status_code == 404

    promotion_link = client.post(
        "/api/v1/marketing/promotion-links/generate",
        headers=_user_headers(token_codec, "user:marketing.write"),
        json={
            "campaign_id": "cmp_storage_draft_001",
            "channel": "wechat",
        },
    )
    assert promotion_link.status_code == 404

    poster = client.post(
        "/api/v1/marketing/posters",
        headers=_user_headers(token_codec, "user:marketing.write", extra={"Idempotency-Key": "poster-draft-001"}),
        json={
            "campaign_id": "cmp_storage_draft_001",
            "theme": "草稿活动",
            "slogan": "不应为草稿活动生成海报",
            "size": "1080x1080",
        },
    )
    assert poster.status_code == 404


def test_user_marketing_routes_only_expose_currently_active_campaigns(
    client,
    token_codec,
    service_modules,
) -> None:
    store = service_modules["store"].get_marketing_store()
    future_start = service_modules["models"].utc_now() + timedelta(days=2)
    future_end = future_start + timedelta(days=7)
    store._snapshot.campaigns[0].start_at = future_start.isoformat()
    store._snapshot.campaigns[0].end_at = future_end.isoformat()
    store._persist()

    listing = client.get(
        "/api/v1/marketing/campaigns?page=1&page_size=20",
        headers=_user_headers(token_codec, "user:marketing.read"),
    )
    assert listing.status_code == 200
    listed_ids = [item["campaign_id"] for item in listing.json()["data"]["items"]]
    assert "cmp_gpu_launch_001" not in listed_ids

    copy = client.post(
        "/api/v1/marketing/copy/generate",
        headers=_user_headers(token_codec, "user:marketing.write"),
        json={
            "campaign_id": "cmp_gpu_launch_001",
            "topic": "未开始活动",
            "audience": "工程团队",
            "tone": "professional",
            "keywords": [],
        },
    )
    assert copy.status_code == 404

    promotion_link = client.post(
        "/api/v1/marketing/promotion-links/generate",
        headers=_user_headers(token_codec, "user:marketing.write"),
        json={
            "campaign_id": "cmp_gpu_launch_001",
            "channel": "wechat",
        },
    )
    assert promotion_link.status_code == 404

    poster = client.post(
        "/api/v1/marketing/posters",
        headers=_user_headers(token_codec, "user:marketing.write", extra={"Idempotency-Key": "poster-future-001"}),
        json={
            "campaign_id": "cmp_gpu_launch_001",
            "theme": "未开始活动",
            "slogan": "未开始活动不应开放用户侧生成",
            "size": "1080x1080",
        },
    )
    assert poster.status_code == 404


def test_poster_task_creation_requires_idempotency_key(client, token_codec) -> None:
    response = client.post(
        "/api/v1/marketing/posters",
        headers=_user_headers(token_codec, "user:marketing.write"),
        json={
            "campaign_id": "cmp_gpu_launch_001",
            "theme": "缺少幂等键",
            "slogan": "验证请求头校验",
            "size": "1080x1080",
        },
    )
    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == 4001001
    assert payload["error"]["field"] == "Idempotency-Key"


def test_create_poster_task_and_poll_completed_result(client, token_codec) -> None:
    created = client.post(
        "/api/v1/marketing/posters",
        headers=_user_headers(token_codec, "user:marketing.write", extra={"Idempotency-Key": "poster-req-001"}),
        json={
            "campaign_id": "cmp_gpu_launch_001",
            "theme": "新品首发",
            "slogan": "AI 算力一键起飞",
            "size": "1024x1536",
        },
    )
    assert created.status_code == 202
    data = created.json()["data"]
    assert data["status"] == "queued"

    detail = client.get(
        f"/api/v1/marketing/posters/{data['task_id']}",
        headers=_user_headers(token_codec, "user:marketing.read"),
    )
    assert detail.status_code == 200
    detail_data = detail.json()["data"]
    assert detail_data["status"] == "completed"
    assert detail_data["image_url"].startswith("https://cdn.smartcloud.local/posters/")


def test_poster_result_alias_route_returns_placeholder_asset_payload(client, token_codec) -> None:
    created = client.post(
        "/api/v1/marketing/posters",
        headers=_user_headers(token_codec, "user:marketing.write", extra={"Idempotency-Key": "poster-req-003"}),
        json={
            "campaign_id": "cmp_gpu_launch_001",
            "theme": "海报结果",
            "slogan": "结果占位图已生成",
            "size": "1080x1920",
        },
    )
    assert created.status_code == 202
    task_id = created.json()["data"]["task_id"]

    result = client.get(
        f"/api/v1/marketing/posters/{task_id}/result",
        headers=_user_headers(token_codec, "user:marketing.read"),
    )
    assert result.status_code == 200
    result_data = result.json()["data"]
    assert result_data["result_ready"] is True
    assert result_data["preview_url"].startswith("https://cdn.smartcloud.local/posters/")
    assert result_data["download_url"].endswith("?download=1")


def test_poster_task_can_surface_running_state_before_auto_completion(
    client,
    token_codec,
    service_modules,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MARKETING_SERVICE_AUTO_COMPLETE_SECONDS", "10")
    service_modules["config"].get_settings.cache_clear()

    created = client.post(
        "/api/v1/marketing/posters",
        headers=_user_headers(token_codec, "user:marketing.write", extra={"Idempotency-Key": "poster-running"}),
        json={
            "campaign_id": "cmp_gpu_launch_001",
            "theme": "运行中海报",
            "slogan": "验证运行中状态",
            "size": "1080x1080",
        },
    )
    assert created.status_code == 202
    task_id = created.json()["data"]["task_id"]

    store = service_modules["store"].get_marketing_store()
    task = store._snapshot.poster_tasks[0]
    task.created_at = (service_modules["models"].utc_now() - timedelta(seconds=5)).isoformat()
    task.updated_at = task.created_at
    store._persist()

    running = client.get(
        f"/api/v1/marketing/posters/{task_id}",
        headers=_user_headers(token_codec, "user:marketing.read"),
    )
    assert running.status_code == 200
    running_data = running.json()["data"]
    assert running_data["status"] == "running"
    assert running_data["image_url"] is None

    running_result = client.get(
        f"/api/v1/marketing/posters/{task_id}/result",
        headers=_user_headers(token_codec, "user:marketing.read"),
    )
    assert running_result.status_code == 200
    assert running_result.json()["data"]["result_ready"] is False

    task.created_at = (service_modules["models"].utc_now() - timedelta(seconds=11)).isoformat()
    task.updated_at = task.created_at
    store._persist()

    completed = client.get(
        f"/api/v1/marketing/posters/{task_id}",
        headers=_user_headers(token_codec, "user:marketing.read"),
    )
    assert completed.status_code == 200
    assert completed.json()["data"]["status"] == "completed"
    assert completed.json()["data"]["image_url"].startswith("https://cdn.smartcloud.local/posters/")


def test_poster_task_idempotency_replays_and_conflicts(client, token_codec) -> None:
    headers = _user_headers(token_codec, "user:marketing.write", extra={"Idempotency-Key": "poster-req-002"})
    body = {
        "campaign_id": "cmp_ecs_growth_001",
        "theme": "增长提效",
        "slogan": "稳定上云，增长加速",
        "size": "1080x1080",
    }
    first = client.post("/api/v1/marketing/posters", headers=headers, json=body)
    second = client.post("/api/v1/marketing/posters", headers=headers, json=body)
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["data"] == second.json()["data"]

    conflict = client.post(
        "/api/v1/marketing/posters",
        headers=headers,
        json={
            "campaign_id": "cmp_ecs_growth_001",
            "theme": "不同主题",
            "slogan": "不同标语",
            "size": "1080x1080",
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == 4090001


def test_poster_task_idempotency_is_scoped_per_user(client, token_codec) -> None:
    body = {
        "campaign_id": "cmp_gpu_launch_001",
        "theme": "共享幂等键",
        "slogan": "验证按用户隔离",
        "size": "1080x1080",
    }
    first = client.post(
        "/api/v1/marketing/posters",
        headers=_user_headers(
            token_codec,
            "user:marketing.write",
            user_id="u_10001",
            extra={"Idempotency-Key": "poster-shared-key"},
        ),
        json=body,
    )
    second = client.post(
        "/api/v1/marketing/posters",
        headers=_user_headers(
            token_codec,
            "user:marketing.write",
            user_id="u_20002",
            extra={"Idempotency-Key": "poster-shared-key"},
        ),
        json=body,
    )

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["data"]["task_id"] != second.json()["data"]["task_id"]


def test_poster_tasks_and_idempotency_are_tenant_scoped(client, token_codec) -> None:
    body = {
        "campaign_id": "cmp_gpu_launch_001",
        "theme": "多租户海报",
        "slogan": "验证租户隔离",
        "size": "1080x1080",
    }
    first = client.post(
        "/api/v1/marketing/posters",
        headers=_user_headers(
            token_codec,
            "user:marketing.write",
            user_id="u_10001",
            tenant_id="tenant-a",
            extra={"Idempotency-Key": "poster-tenant-key"},
        ),
        json=body,
    )
    second = client.post(
        "/api/v1/marketing/posters",
        headers=_user_headers(
            token_codec,
            "user:marketing.write",
            user_id="u_10001",
            tenant_id="tenant-b",
            extra={"Idempotency-Key": "poster-tenant-key"},
        ),
        json=body,
    )

    assert first.status_code == 202
    assert second.status_code == 202
    first_task_id = first.json()["data"]["task_id"]
    second_task_id = second.json()["data"]["task_id"]
    assert first_task_id != second_task_id

    tenant_a_listing = client.get(
        "/api/v1/marketing/posters?page=1&page_size=20",
        headers=_user_headers(token_codec, "user:marketing.read", tenant_id="tenant-a"),
    )
    tenant_b_listing = client.get(
        "/api/v1/marketing/posters?page=1&page_size=20",
        headers=_user_headers(token_codec, "user:marketing.read", tenant_id="tenant-b"),
    )
    assert tenant_a_listing.status_code == 200
    assert tenant_b_listing.status_code == 200
    assert [item["task_id"] for item in tenant_a_listing.json()["data"]["items"]] == [first_task_id]
    assert [item["task_id"] for item in tenant_b_listing.json()["data"]["items"]] == [second_task_id]

    cross_tenant_detail = client.get(
        f"/api/v1/marketing/posters/{first_task_id}",
        headers=_user_headers(token_codec, "user:marketing.read", tenant_id="tenant-b"),
    )
    assert cross_tenant_detail.status_code == 404


def test_promotion_link_placeholder_generation(client, token_codec) -> None:
    response = client.post(
        "/api/v1/marketing/promotion-links/generate",
        headers=_user_headers(token_codec, "user:marketing.write"),
        json={
            "campaign_id": "cmp_gpu_launch_001",
            "channel": "wechat",
            "source": "social",
            "content_tag": "hero-banner",
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["short_url"].startswith("https://go.smartcloud.local/")
    assert "utm_campaign=cmp_gpu_launch_001" in data["tracking_code"]


def test_promotion_link_history_is_tenant_scoped(client, token_codec) -> None:
    tenant_a = client.post(
        "/api/v1/marketing/promotion-links/generate",
        headers=_user_headers(token_codec, "user:marketing.write", tenant_id="tenant-a"),
        json={
            "campaign_id": "cmp_gpu_launch_001",
            "channel": "wechat",
            "source": "social",
            "content_tag": "tenant-a",
        },
    )
    tenant_b = client.post(
        "/api/v1/marketing/promotion-links/generate",
        headers=_user_headers(token_codec, "user:marketing.write", tenant_id="tenant-b"),
        json={
            "campaign_id": "cmp_gpu_launch_001",
            "channel": "wechat",
            "source": "social",
            "content_tag": "tenant-b",
        },
    )
    assert tenant_a.status_code == 200
    assert tenant_b.status_code == 200
    tenant_a_link_id = tenant_a.json()["data"]["link_id"]
    tenant_b_link_id = tenant_b.json()["data"]["link_id"]

    tenant_a_listing = client.get(
        "/api/v1/marketing/promotion-links?page=1&page_size=20&channel=wechat",
        headers=_user_headers(token_codec, "user:marketing.read", tenant_id="tenant-a"),
    )
    tenant_b_listing = client.get(
        "/api/v1/marketing/promotion-links?page=1&page_size=20&channel=wechat",
        headers=_user_headers(token_codec, "user:marketing.read", tenant_id="tenant-b"),
    )
    assert tenant_a_listing.status_code == 200
    assert tenant_b_listing.status_code == 200
    assert [item["link_id"] for item in tenant_a_listing.json()["data"]["items"]] == [tenant_a_link_id]
    assert [item["link_id"] for item in tenant_b_listing.json()["data"]["items"]] == [tenant_b_link_id]

    cross_tenant_detail = client.get(
        f"/api/v1/marketing/promotion-links/{tenant_a_link_id}",
        headers=_user_headers(token_codec, "user:marketing.read", tenant_id="tenant-b"),
    )
    assert cross_tenant_detail.status_code == 404


def test_poster_listing_completes_all_visible_tasks(client, token_codec) -> None:
    for campaign_id, theme in (
        ("cmp_gpu_launch_001", "新品首发"),
        ("cmp_ecs_growth_001", "增长提效"),
    ):
        created = client.post(
            "/api/v1/marketing/posters",
            headers=_user_headers(
                token_codec,
                "user:marketing.write",
                extra={"Idempotency-Key": f"poster-listing-{campaign_id}"},
            ),
            json={
                "campaign_id": campaign_id,
                "theme": theme,
                "slogan": f"{theme} 标语",
                "size": "1080x1080",
            },
        )
        assert created.status_code == 202

    listing = client.get(
        "/api/v1/marketing/posters?page=1&page_size=20",
        headers=_user_headers(token_codec, "user:marketing.read"),
    )
    assert listing.status_code == 200
    items = listing.json()["data"]["items"]
    assert len(items) == 2
    assert all(item["status"] == "completed" for item in items)
    assert all(item["image_url"].startswith("https://cdn.smartcloud.local/posters/") for item in items)


def test_marketing_routes_require_valid_user_permissions(client, token_codec) -> None:
    unauthorized = client.get("/api/v1/marketing/campaigns")
    assert unauthorized.status_code == 401

    forbidden = client.post(
        "/api/v1/marketing/copy/generate",
        headers=_user_headers(token_codec, "user:research.read"),
        json={
            "campaign_id": "cmp_gpu_launch_001",
            "topic": "AI 算力",
            "audience": "工程团队",
            "tone": "professional",
            "keywords": [],
        },
    )
    assert forbidden.status_code == 403


def test_marketing_routes_reject_refresh_like_tokens(client, token_codec) -> None:
    access = token_codec.issue_access_token(
        subject_type="user",
        subject_id="u_10001",
        tenant_id="default",
        roles=["user"],
        permissions=["user:marketing.read"],
    )
    refresh_like_claims = dict(access.claims)
    refresh_like_claims["token_type"] = "refresh"
    refresh_like_token = token_codec._encode(refresh_like_claims)  # type: ignore[attr-defined]

    response = client.get(
        "/api/v1/marketing/campaigns",
        headers={"Authorization": f"Bearer {refresh_like_token}"},
    )
    assert response.status_code == 401


def test_marketing_routes_reject_internal_audience_user_tokens(
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
        permissions=["user:marketing.read"],
    )
    internal_audience_claims = dict(public_access.claims)
    internal_audience_claims["aud"] = settings.internal_auth_audience
    internal_audience_token = token_codec._encode(internal_audience_claims)  # type: ignore[attr-defined]

    response = client.get(
        "/api/v1/marketing/campaigns",
        headers={"Authorization": f"Bearer {internal_audience_token}"},
    )
    assert response.status_code == 401


def test_openapi_publishes_poster_result_route(client) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/marketing/copies" in paths
    assert "/api/v1/marketing/copies/{copy_id}" in paths
    assert "/api/v1/marketing/promotion-links" in paths
    assert "/api/v1/marketing/promotion-links/{link_id}" in paths
    assert "/api/v1/marketing/posters/{task_id}/result" in paths


def test_marketing_can_opt_into_strict_auth_current_state_validation(
    client,
    token_codec,
    service_modules,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MARKETING_SERVICE_AUTH_VALIDATION_MODE", "strict")
    monkeypatch.setenv(
        "MARKETING_SERVICE_AUTH_VALIDATE_TOKEN_URL",
        "http://auth-user-service.local/internal/v1/auth/validate-token",
    )
    service_modules["config"].get_settings.cache_clear()

    def allow(_request, _token, *, settings):
        assert settings.internal_service_name == "marketing-service"
        return {
            "subject_type": "user",
            "subject_id": "u_10001",
            "tenant_id": "default",
            "roles": ["user"],
            "permissions": ["user:marketing.read"],
            "expired_at": "2099-01-01T00:00:00+00:00",
        }

    monkeypatch.setattr(service_modules["dependencies"], "_validate_token_with_auth_service", allow)

    response = client.get(
        "/api/v1/marketing/campaigns",
        headers=_user_headers(token_codec, "user:marketing.read"),
    )
    assert response.status_code == 200


def test_marketing_strict_auth_validation_rejects_stale_token(
    client,
    token_codec,
    service_modules,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MARKETING_SERVICE_AUTH_VALIDATION_MODE", "strict")
    monkeypatch.setenv(
        "MARKETING_SERVICE_AUTH_VALIDATE_TOKEN_URL",
        "http://auth-user-service.local/internal/v1/auth/validate-token",
    )
    service_modules["config"].get_settings.cache_clear()

    def reject(_request, _token, *, settings):
        raise service_modules["models"].ServiceError(401, 4010002, "token is no longer valid")

    monkeypatch.setattr(service_modules["dependencies"], "_validate_token_with_auth_service", reject)

    response = client.get(
        "/api/v1/marketing/campaigns",
        headers=_user_headers(token_codec, "user:marketing.read"),
    )
    assert response.status_code == 401
    assert response.json()["message"] == "token is no longer valid"


def test_marketing_strict_auth_uses_validated_permissions_even_when_empty(
    client,
    token_codec,
    service_modules,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MARKETING_SERVICE_AUTH_VALIDATION_MODE", "strict")
    monkeypatch.setenv(
        "MARKETING_SERVICE_AUTH_VALIDATE_TOKEN_URL",
        "http://auth-user-service.local/internal/v1/auth/validate-token",
    )
    service_modules["config"].get_settings.cache_clear()

    def allow_without_permissions(_request, _token, *, settings):
        assert settings.internal_service_name == "marketing-service"
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
        "/api/v1/marketing/campaigns",
        headers=_user_headers(token_codec, "user:marketing.read"),
    )
    assert response.status_code == 403
    assert response.json()["message"] == "missing required permissions"
    assert response.json()["error"]["details"]["missing_permissions"] == ["user:marketing.read"]
