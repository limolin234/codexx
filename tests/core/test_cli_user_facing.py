from advanced_agent.cli import _format_delta, _is_redundant_reply
from advanced_agent.models import AgentRole, Authority, StreamDelta


def test_cli_hides_stream_metadata_by_default() -> None:
    delta = StreamDelta(session_id="s", request_id="r", seq=1, writer=AgentRole.INTERACTIVE, authority=Authority.PROVISIONAL, text="你好", timestamp_ms=1)
    assert _format_delta(delta) == "你好"
    assert "interactive/provisional" in _format_delta(delta, debug=True)


def test_cli_suppresses_redundant_greeting() -> None:
    assert _is_redundant_reply("你好呀！有什么可以帮你的？", "你好！有什么我可以帮你处理的吗？")
    assert not _is_redundant_reply("我看一下。", "已发起后台任务 task_1。")
