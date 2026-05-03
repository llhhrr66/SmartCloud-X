from pathlib import Path

from app.services.agent_answer_generator import OpenAICompatibleAgentAnswerGenerator


class _FakeSettings:
    llm_api_key = None
    llm_model = None
    llm_base_url = None
    llm_timeout_seconds = 20


def test_agent_answer_generator_loads_system_prompt_from_file(tmp_path: Path) -> None:
    prompt_root = tmp_path / "prompts"
    prompt_dir = prompt_root / "agents" / "finance_order"
    prompt_dir.mkdir(parents=True)
    prompt_file = prompt_dir / "system.v1.0.md"
    prompt_file.write_text("# role\n你是文件版 Finance_Order_Agent。", encoding="utf-8")

    generator = OpenAICompatibleAgentAnswerGenerator(settings=_FakeSettings(), prompt_root=prompt_root)

    assert generator._system_prompt_for("finance_order_agent") == "# role\n你是文件版 Finance_Order_Agent。"


def test_agent_answer_generator_falls_back_when_prompt_file_missing(tmp_path: Path) -> None:
    generator = OpenAICompatibleAgentAnswerGenerator(settings=_FakeSettings(), prompt_root=tmp_path / "prompts")

    prompt = generator._system_prompt_for("finance_order_agent")

    assert "你是 SmartCloud-X 的 finance_order_agent" in prompt


def test_agent_answer_generator_extracts_final_answer_from_json_text(tmp_path: Path) -> None:
    generator = OpenAICompatibleAgentAnswerGenerator(settings=_FakeSettings(), prompt_root=tmp_path / "prompts")

    text = '{"final_answer":"你好，这是正文。","citations":["baseline://support-playbook"]}'

    assert generator._normalize_generated_content(text) == "你好，这是正文。"
