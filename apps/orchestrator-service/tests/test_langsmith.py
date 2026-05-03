import os

from app.core.config import Settings
from app.core.langsmith import configure_langsmith_env, langsmith_enabled


def test_configure_langsmith_env_sets_expected_variables(monkeypatch) -> None:
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGSMITH_ENDPOINT", raising=False)
    monkeypatch.delenv("LANGSMITH_PROJECT", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)

    settings = Settings.model_validate(
        {
            "LANGSMITH_TRACING": True,
            "LANGSMITH_ENDPOINT": "https://api.smith.langchain.com",
            "LANGSMITH_PROJECT": "smartcloud-x",
            "LANGSMITH_API_KEY": "ls-test-key",
        }
    )
    configure_langsmith_env(settings)

    assert os.environ["LANGSMITH_TRACING"] == "true"
    assert os.environ["LANGSMITH_ENDPOINT"] == "https://api.smith.langchain.com"
    assert os.environ["LANGSMITH_PROJECT"] == "smartcloud-x"
    assert os.environ["LANGSMITH_API_KEY"] == "ls-test-key"
    assert langsmith_enabled(settings) is True
