import asyncio

from advanced_agent.runtime.app import RuntimeApp


def test_main_direct_background_requests_keep_request_specific_text(tmp_path) -> None:
    async def run() -> None:
        app = RuntimeApp.create(tmp_path / "state.sqlite")
        sid = app.create_session("fork")
        r1 = await app.start_main_request_background(sid, "第一个请求：查工具", str(tmp_path))
        r2 = await app.start_main_request_background(sid, "第二个请求：查路径", str(tmp_path))
        await app.wait_user_request(r1, timeout_seconds=2)
        await app.wait_user_request(r2, timeout_seconds=2)
        d1 = app.decisions.latest_for_request(sid, r1)
        d2 = app.decisions.latest_for_request(sid, r2)
        assert d1 is not None and d2 is not None
        assert "第一个请求" in d1.intent
        assert "第二个请求" in d2.intent

    asyncio.run(run())
