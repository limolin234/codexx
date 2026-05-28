from advanced_agent.agents.interactive import InteractiveAgent
from advanced_agent.models import AgentRole, Authority, StreamDelta
from advanced_agent.runtime.app import RuntimeApp
from advanced_agent.cli import _format_delta


class SilentModel:
    def chat(self, messages):
        return "<silent>"


def test_interactive_model_can_choose_silence(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    app.interactive.model = SilentModel()
    sid = app.create_session("silent")
    request_id, delta = app.start_user_request(sid, "继续")
    assert request_id
    assert delta.text == ""
    stream = app.sessions.stream_for_request(request_id)
    assert stream[0].text == ""


def test_interactive_render_can_choose_silence(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.create_session("silent")
    delta = app.interactive.render_main_reply(sid, "r", "<silent>")
    assert delta.text == ""


def test_interactive_sanitizes_internal_ids(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.create_session("sanitize")
    rendered = app.interactive.render_main_reply(sid, "r", "任务 task_abcdef1234567890 已经完成，request req_abcdef1234567890 结束。")
    assert "task_" not in rendered.text
    assert "req_" not in rendered.text
    assert "后台任务" in rendered.text
