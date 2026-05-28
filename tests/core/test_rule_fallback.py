from advanced_agent.llm import LLMError
from advanced_agent.runtime.app import RuntimeApp


class FailingModel:
    def chat_complete(self, *args, **kwargs):
        raise LLMError("LLM HTTP 403: secret raw error")
    def chat(self, *args, **kwargs):
        raise LLMError("LLM HTTP 403: secret raw error")


def test_main_rule_fallback_hides_raw_llm_error_and_lists_tools(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    app.main.model = FailingModel()
    sid = app.create_session("fallback")
    req, _ = app.start_user_request(sid, "你到底有什么工具")
    rendered = app.finish_user_request(sid, req, str(tmp_path))
    assert "LLM HTTP" not in rendered.text
    assert "task_state" in rendered.text or "任务" in rendered.text


def test_main_rule_fallback_can_answer_recent_context(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    app.main.model = FailingModel()
    sid = app.create_session("fallback")
    req, _ = app.start_user_request(sid, "我刚刚说了什么")
    rendered = app.finish_user_request(sid, req, str(tmp_path))
    assert "我刚刚说了什么" in rendered.text
    assert "LLM HTTP" not in rendered.text
