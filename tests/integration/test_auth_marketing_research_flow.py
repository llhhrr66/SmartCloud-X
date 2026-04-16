from __future__ import annotations

from pathlib import Path

from scripts.qa.contract_policy import validate_live_response_contract
from scripts.qa.openapi_contracts import OpenApiContract
from tests.qa_helpers.service_loader import assert_standard_headers, service_test_client


def test_auth_marketing_and_research_share_user_token_contracts(tmp_path: Path) -> None:
    auth_contract = OpenApiContract("openapi/auth-user-service.openapi.yaml")
    marketing_contract = OpenApiContract("openapi/marketing-service.openapi.yaml")
    research_contract = OpenApiContract("openapi/research-service.openapi.yaml")

    with service_test_client(
        "auth-user-service",
        env_overrides={
            "AUTH_USER_SERVICE_DATA_PATH": str(tmp_path / "auth-store.json"),
            "SMARTCLOUD_JWT_SECRET": "qa-test-secret",
            "SMARTCLOUD_AUTH_ISSUER": "qa-test-issuer",
            "SMARTCLOUD_AUTH_AUDIENCE": "qa-test-audience",
        },
    ) as auth_client:
        login = auth_client.post(
            "/api/v1/auth/login",
            json={
                "login_type": "password",
                "account": "demo@smartcloud.local",
                "password": "Password123!",
            },
        )
        assert login.status_code == 200
        assert_standard_headers(login.headers)
        validate_live_response_contract(
            {"auth-user-service": auth_contract},
            "auth-user-service",
            "/api/v1/auth/login",
            "post",
            200,
            login.json(),
        )
        access_token = login.json()["data"]["access_token"]

    bearer_headers = {"Authorization": f"Bearer {access_token}"}

    with service_test_client(
        "marketing-service",
        env_overrides={
            "MARKETING_SERVICE_DATA_PATH": str(tmp_path / "marketing-store.json"),
            "SMARTCLOUD_JWT_SECRET": "qa-test-secret",
            "SMARTCLOUD_AUTH_ISSUER": "qa-test-issuer",
            "SMARTCLOUD_AUTH_AUDIENCE": "qa-test-audience",
        },
    ) as marketing_client:
        campaigns = marketing_client.get("/api/v1/marketing/campaigns?page=1&page_size=20", headers=bearer_headers)
        assert campaigns.status_code == 200
        assert_standard_headers(campaigns.headers)
        validate_live_response_contract(
            {"marketing-service": marketing_contract},
            "marketing-service",
            "/api/v1/marketing/campaigns",
            "get",
            200,
            campaigns.json(),
        )
        campaign_id = campaigns.json()["data"]["items"][0]["campaign_id"]

        copy = marketing_client.post(
            "/api/v1/marketing/copy/generate",
            headers=bearer_headers,
            json={
                "campaign_id": campaign_id,
                "topic": "AI算力起量",
                "audience": "AI创业团队",
                "tone": "launch",
                "keywords": ["AI算力", "弹性扩容"],
            },
        )
        assert copy.status_code == 200
        assert_standard_headers(copy.headers)
        validate_live_response_contract(
            {"marketing-service": marketing_contract},
            "marketing-service",
            "/api/v1/marketing/copy/generate",
            "post",
            200,
            copy.json(),
        )
        assert copy.json()["data"]["headline"]

    with service_test_client(
        "research-service",
        env_overrides={
            "RESEARCH_SERVICE_DATA_PATH": str(tmp_path / "research-store.json"),
            "SMARTCLOUD_JWT_SECRET": "qa-test-secret",
            "SMARTCLOUD_AUTH_ISSUER": "qa-test-issuer",
            "SMARTCLOUD_AUTH_AUDIENCE": "qa-test-audience",
        },
    ) as research_client:
        create = research_client.post(
            "/api/v1/research/tasks",
            headers={**bearer_headers, "Idempotency-Key": "qa-integration-research-001"},
            json={
                "topic": "LangGraph vs CrewAI",
                "scope": "客服编排能力对比",
                "depth": "standard",
                "output_format": "markdown",
                "reference_urls": ["https://docs.langchain.com/oss/python/langgraph/overview"],
            },
        )
        assert create.status_code == 202
        assert_standard_headers(create.headers)
        validate_live_response_contract(
            {"research-service": research_contract},
            "research-service",
            "/api/v1/research/tasks",
            "post",
            202,
            create.json(),
        )
        task_id = create.json()["data"]["task_id"]

        detail = research_client.get(f"/api/v1/research/tasks/{task_id}", headers=bearer_headers)
        assert detail.status_code == 200
        assert_standard_headers(detail.headers)
        validate_live_response_contract(
            {"research-service": research_contract},
            "research-service",
            "/api/v1/research/tasks/{task_id}",
            "get",
            200,
            detail.json(),
        )
        assert detail.json()["data"]["status"] == "completed"
