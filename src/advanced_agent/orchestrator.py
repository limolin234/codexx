from __future__ import annotations

from pathlib import Path

from advanced_agent.runtime.app import RuntimeApp


def demo(user_text: str, db_path: str | Path = ":memory:", workdir: str = "."):
    app = RuntimeApp.create(db_path)
    session_id = app.create_session("demo")
    request_id = app.handle_user_text(session_id, user_text, workdir=workdir)
    return app.sessions.stream_for_request(request_id)


if __name__ == "__main__":
    for delta in demo("开始实现 advanced_agent 第一版", db_path="runtime/advanced_agent.sqlite", workdir="."):
        print(f"{delta.seq} {delta.writer.value}/{delta.authority.value}: {delta.text}")
