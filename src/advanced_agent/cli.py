from __future__ import annotations

import argparse
import asyncio
import sys
from contextlib import nullcontext
from pathlib import Path

from advanced_agent.runtime.app import RuntimeApp

try:  # prompt_toolkit is used only for real TTY interaction.
    from prompt_toolkit import PromptSession, print_formatted_text
    from prompt_toolkit.patch_stdout import patch_stdout
except ModuleNotFoundError:  # pragma: no cover - fallback for minimal envs
    PromptSession = None
    print_formatted_text = print
    patch_stdout = None


HELP = """Commands:
  /help                 show this help
  /exit                 quit
  /mem TEXT             add TEXT into vector memory
  /search QUERY         search vector memory
  /pwd                  show runtime working directory
  /cd PATH              change runtime working directory
  /stream REQUEST_ID    show stored stream for request
  /tasks                list recent tasks
  /task TASK_ID         show task state, summary, and tail
  /context              show active/compacted context stats
  /clear-before MS      hide messages at/before wall-clock ms from prompt context
  /rollback-to MS       hide messages after wall-clock ms from prompt context
Any other text goes through interactive -> main mock flow.
"""


async def async_main() -> None:
    parser = argparse.ArgumentParser(description="Advanced Agent local interactive prototype")
    parser.add_argument("--db", default="runtime/advanced_agent.sqlite")
    parser.add_argument("--workdir", default=".")
    parser.add_argument("--config", default=".env.json", help="JSON model config path; ignored if missing")
    parser.add_argument("--session-title", default="default", help="persistent default session title")
    parser.add_argument("--new-session", action="store_true", help="create a fresh session instead of resuming the default one")
    parser.add_argument("--debug-stream", action="store_true", help="show writer/authority metadata for each stream delta")
    args = parser.parse_args()

    app = RuntimeApp.create(args.db, config_path=args.config)
    app.chdir(args.workdir)
    session_id = app.create_session(args.session_title) if args.new_session else app.default_session(args.session_title)
    use_prompt_toolkit = bool(sys.stdin.isatty() and PromptSession is not None)
    prompt_session = PromptSession() if use_prompt_toolkit and PromptSession is not None else None
    output_context = patch_stdout() if use_prompt_toolkit and patch_stdout is not None else nullcontext()
    _safe_print("Advanced Agent prototype. Type /help for commands, /exit to quit.")
    _safe_print(f"session={session_id} db={args.db} cwd={app.workspace.cwd}")
    pending: set[asyncio.Task] = set()

    with output_context:
        while True:
            try:
                text = (await _read_prompt(prompt_session)).strip()
            except (EOFError, KeyboardInterrupt):
                _safe_print("")
                break
            if not text:
                continue
            if text == "/exit":
                if pending:
                    _safe_print(f"waiting for {len(pending)} background request(s)...")
                    await asyncio.gather(*pending, return_exceptions=True)
                break
            if text == "/help":
                _safe_print(HELP)
                continue
            if text.startswith("/mem "):
                memory_id = app.remember(text[5:].strip(), scope="cli", type_="note")
                _safe_print(f"remembered {memory_id}")
                continue
            if text.startswith("/search "):
                hits = app.search_memory(text[8:].strip(), scope="cli", top_k=5)
                if not hits:
                    _safe_print("no hits")
                for hit in hits:
                    _safe_print(f"{hit.distance:.4f} {hit.memory_id} [{hit.label_kind}] {hit.summary}")
                continue
            if text == "/pwd":
                info = app.workspace.info()
                _safe_print({"cwd": info.cwd, "project_root": info.project_root, "markers": info.markers})
                continue
            if text.startswith("/cd "):
                try:
                    info = app.chdir(text[4:].strip())
                except Exception as exc:
                    _safe_print(f"cd failed: {type(exc).__name__}: {exc}")
                else:
                    _safe_print(f"cwd={info.cwd}")
                continue
            if text.startswith("/stream "):
                for delta in app.sessions.stream_for_request(text[8:].strip()):
                    _safe_print(f"{delta.seq} {delta.writer.value}/{delta.authority.value}: {delta.text}")
                continue
            if text == "/tasks":
                for row in app.tasks.list_tasks(limit=20):
                    _safe_print(f"{row['id']} {row['status']} {row['stage'] or '-'} {row['goal'][:80]}")
                continue
            if text.startswith("/task "):
                task_id = text.split(maxsplit=1)[1]
                state = app.supervisor.get_task_state(task_id)
                _safe_print("state:", None if state is None else {
                    "status": state.status,
                    "stage": state.stage,
                    "summary": state.latest_summary,
                    "need_attention": state.need_attention,
                    "can_stop": state.can_stop,
                })
                tail = app.supervisor.get_task_tail(task_id, limit=40)
                if tail:
                    _safe_print("tail:")
                    _safe_print(tail)
                continue
            if text == "/context":
                stats = app.sessions.context_stats(session_id)
                _safe_print(stats)
                continue
            if text.startswith("/clear-before "):
                cutoff = int(text.split(maxsplit=1)[1])
                count = app.clear_context_before_ms(session_id, cutoff)
                _safe_print(f"cleared_from_context {count} messages")
                continue
            if text.startswith("/rollback-to "):
                cutoff = int(text.split(maxsplit=1)[1])
                count = app.rollback_context_to_ms(session_id, cutoff)
                _safe_print(f"rolled_back_context {count} messages")
                continue
            request_id = await app.start_main_request_background(session_id, text)
            task = app.background_requests[request_id]
            pending.add(task)
            if args.debug_stream:
                _safe_print(f"started request={request_id}")

            def _done(done_task, rid=request_id):
                pending.discard(done_task)
                try:
                    rendered_delta = done_task.result()
                except Exception as exc:
                    _safe_print(f"处理失败：{type(exc).__name__}: {exc}")
                    return
                if rendered_delta.text.strip():
                    _safe_print(_format_delta(rendered_delta, debug=args.debug_stream))
                if args.debug_stream:
                    _safe_print(f"completed request={rid}")

            task.add_done_callback(_done)


def main() -> None:
    asyncio.run(async_main())


async def _read_prompt(prompt_session) -> str:
    if prompt_session is not None:
        return await prompt_session.prompt_async("> ")
    return input("> ")


def _safe_print(*args) -> None:
    print_formatted_text(*args)


def _format_delta(delta, debug: bool = False) -> str:
    if debug:
        return f"{delta.seq} {delta.writer.value}/{delta.authority.value}: {delta.text}"
    return delta.text


def _is_redundant_reply(first: str, second: str) -> bool:
    a = _normalize_reply(first)
    b = _normalize_reply(second)
    if not a or not b:
        return False
    if a == b:
        return True
    greeting_tokens = ("你好", "您好", "hello", "hi", "有什么可以帮")
    if any(tok in a for tok in greeting_tokens) and any(tok in b for tok in greeting_tokens):
        return True
    return False


def _normalize_reply(text: str) -> str:
    return "".join(ch for ch in text.lower().strip() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


if __name__ == "__main__":
    main()
