import asyncio

from advanced_agent.models import Authority
from advanced_agent.runtime.app import RuntimeApp


def test_background_user_request_returns_provisional_before_main(tmp_path) -> None:
    async def run() -> None:
        app = RuntimeApp.create(tmp_path / "state.sqlite")
        sid = app.create_session("background")
        request_id, quick = await app.start_user_request_background(sid, "hello", str(tmp_path))
        assert quick.authority == Authority.PROVISIONAL
        stream = app.sessions.stream_for_request(request_id)
        assert len(stream) == 1
        assert stream[0].authority == Authority.PROVISIONAL
        rendered = await app.wait_user_request(request_id, timeout_seconds=2)
        assert rendered.authority == Authority.AUTHORITATIVE
        stream = app.sessions.stream_for_request(request_id)
        assert [delta.authority for delta in stream] == [Authority.PROVISIONAL, Authority.AUTHORITATIVE]
        events = app.events.store.recent(20)
        types = [event.type for event in events]
        assert "interaction.background.started" in types
        assert "interaction.background.completed" in types

    asyncio.run(run())
