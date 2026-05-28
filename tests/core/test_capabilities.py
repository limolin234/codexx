from advanced_agent.capabilities import BackendRegistry, CapabilityRouter, LatencyClass
from advanced_agent.runtime.app import RuntimeApp


def test_capability_router_keeps_fast_queries_in_core() -> None:
    router = CapabilityRouter(BackendRegistry())
    decision = router.route("看看任务进度和 tail")
    assert decision.capability.backend == "core"
    assert decision.capability.latency == LatencyClass.LOW


def test_capability_router_delegates_code_to_codex() -> None:
    router = CapabilityRouter(BackendRegistry())
    decision = router.route("修改代码并运行测试")
    assert decision.capability.backend == "codex-cli"
    assert decision.capability.requires_task


def test_prompt_includes_abstract_capabilities(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.create_session("cap")
    bundle = app.main.prompt_builder.main_decision(sid, "r", "修改代码")
    text = "\n".join(m.content for m in bundle.messages)
    assert "Available abstract capabilities" in text
    assert "code_editing" in text
    assert "codex-cli" in text
