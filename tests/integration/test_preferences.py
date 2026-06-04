from advanced_agent.preferences import PreferenceLimits, PreferenceWorker
from advanced_agent.runtime.app import RuntimeApp
from advanced_agent.stores.profile_store import ProfileStore, PromptOverlayStore


def test_preference_worker_bounded_profile(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.create_session("prefs")
    app.record_user_message(sid, "我希望先讨论架构和模块解耦，可维护性优先，不要急着 demo")
    app.record_user_message(sid, "interactive 只做快速反馈，main agent 做核心判断")
    profile_id = app.preferences.update_from_session(sid, scope="project:test")
    assert profile_id.startswith("profile_")
    summary = app.profiles.get_profile("project:test")
    assert summary is not None
    assert len(summary) <= 1200
    main_overlays = app.overlays.overlays_for("project:test", "main")
    assert main_overlays
    assert "Lightweight startup user-profile hints" in main_overlays[0]
    assert "暂无稳定偏好" in main_overlays[0]


def test_prompt_overlay_total_limit(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    now = app.time.wall_ms()
    app.overlays.replace_overlay("s", "main", "a", "a" * 10, now, priority=1, max_chars=100)
    app.overlays.replace_overlay("s", "main", "b", "b" * 10, now, priority=0, max_chars=100)
    overlays = app.overlays.overlays_for("s", "main", max_total_chars=15)
    assert sum(len(x) for x in overlays) <= 15
