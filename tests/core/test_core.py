from advanced_agent.models import AgentRole, Authority, Message, StreamDelta, TaskSpec
from advanced_agent.supervisor import WorkerSpec


def test_message_has_id() -> None:
    msg = Message(session_id="s", request_id="r", role="user", content="hi", created_at_ms=1)
    assert msg.id.startswith("msg_")


def test_task_spec_defaults() -> None:
    task = TaskSpec(goal="do work", workdir=".")
    assert task.id.startswith("task_")
    assert task.backend == "codex-cli"


def test_stream_delta_authority() -> None:
    delta = StreamDelta(
        session_id="s",
        request_id="r",
        seq=1,
        writer=AgentRole.INTERACTIVE,
        authority=Authority.PROVISIONAL,
        text="ok",
        timestamp_ms=1,
    )
    assert delta.id.startswith("delta_")


def test_worker_spec_has_id() -> None:
    spec = WorkerSpec(name="buffer", command=["python", "-V"], role="fast_buffer")
    assert spec.id.startswith("worker_")
