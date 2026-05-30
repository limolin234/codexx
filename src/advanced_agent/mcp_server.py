from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from advanced_agent import defaults
from advanced_agent.runtime.app import RuntimeApp
from advanced_agent.runtime_tools import RuntimeToolBridge


def create_mcp(db_path: str | Path | None = None, config_path: str | Path | None = None) -> FastMCP:
    """Create the project-local Advanced Agent MCP server.

    The server is a thin protocol adapter. Runtime semantics stay in
    `RuntimeToolBridge`, so tests, Codex MCP, and future HTTP adapters share the
    same memory/context/task implementation.
    """

    db_path = db_path or defaults.default_db()
    config_path = config_path if config_path is not None else defaults.default_config()
    app = RuntimeApp.create(
        db_path,
        config_path=config_path,
        initial_cwd=os.environ.get("ADVANCED_AGENT_LAUNCH_CWD"),
        sync_process_cwd=True,
    )
    bridge = RuntimeToolBridge(app)
    mcp = FastMCP(
        "advanced-agent-runtime",
        instructions="Advanced Agent project-local runtime. Use exposed tools for memory/context lookup and durable runtime memory.",
    )

    safe_read_annotations = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
    safe_db_write_annotations = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
    @mcp.tool(
        name="context_get",
        description="Get supplemental prior session lines plus durable memory hits. Use for context lookup, semantic memory search, and recent-memory recaps.",
        annotations=safe_read_annotations,
    )
    def context_get(
        query: str = "",
        scope: str = defaults.DEFAULT_SCOPE,
        session_id: str | None = None,
        recent_limit: int = 30,
        memory_top_k: int = 8,
        include_compacted: bool = False,
        mode: Literal["supplement", "full"] = "supplement",
        live_recent_limit: int = 12,
        include_memory_content: bool | None = None,
        memory_content_max_chars: int | None = None,
        include_log_memories: bool = False,
        query_profile: str = "auto",
        facet_weights_json: str = "{}",
        view: Literal["compact", "debug"] = "compact",
        dedupe: Literal["on", "off"] = "on",
        caller_session_id: str = "",
        include_profile: bool | None = None,
        profile_limit: int = 3,
    ) -> dict[str, Any]:
        try:
            facet_weights = json.loads(facet_weights_json or "{}")
        except json.JSONDecodeError as exc:
            return {"ok": False, "error": f"facet_weights_json must be JSON object: {exc}"}
        if not isinstance(facet_weights, dict):
            return {"ok": False, "error": "facet_weights_json must decode to an object"}
        args: dict[str, Any] = {
            "query": query,
            "scope": scope,
            "recent_limit": recent_limit,
            "memory_top_k": memory_top_k,
            "include_compacted": include_compacted,
            "mode": mode,
            "live_recent_limit": live_recent_limit,
            "include_log_memories": include_log_memories,
            "query_profile": query_profile,
            "facet_weights": facet_weights,
            "view": view,
            "dedupe": dedupe,
            "caller_session_id": caller_session_id,
            "profile_limit": profile_limit,
        }
        if include_profile is not None:
            args["include_profile"] = include_profile
        if include_memory_content is not None:
            args["include_memory_content"] = include_memory_content
        if memory_content_max_chars is not None:
            args["memory_content_max_chars"] = memory_content_max_chars
        if session_id:
            args["session_id"] = session_id
        return bridge.call("context.get", args)

    @mcp.tool(
        name="memory_write",
        description="Write a durable memory record through the aligned memory indexer. Non-destructive and duplicate-safe; clients may auto-approve routine memory notes.",
        annotations=safe_db_write_annotations,
    )
    def memory_write(
        summary: str,
        content: str | None = None,
        scope: str = defaults.DEFAULT_SCOPE,
        type: str = "note",
        importance: float = 0.5,
        confidence: float = 0.8,
    ) -> dict[str, Any]:
        return bridge.call(
            "memory.write",
            {
                "summary": summary,
                "content": content if content is not None else summary,
                "scope": scope,
                "type": type,
                "source_type": "mcp",
                "source_id": summary[:80],
                "importance": importance,
                "confidence": confidence,
            },
        )

    # Keep low-level memory.search / memory.recent inside RuntimeToolBridge for
    # internal agents and tests.  Do not expose them as MCP tools: context_get is
    # the single model-facing read path so Codex has fewer memory-tool choices.

    @mcp.tool(name="session_raw_tail", description="Read a bounded raw dialogue tail; use when the model needs to inspect overflow recent rows without loading all history.", annotations=safe_read_annotations)
    def session_raw_tail(session_id: str | None = None, limit: int = 80, max_chars: int = 800, include_compacted: bool = True) -> dict[str, Any]:
        args: dict[str, Any] = {"limit": limit, "max_chars": max_chars, "include_compacted": include_compacted}
        if session_id:
            args["session_id"] = session_id
        return bridge.call("session.raw_tail", args)

    @mcp.tool(name="project_info", description="Read runtime cwd and inferred project root.", annotations=safe_read_annotations)
    def project_info() -> dict[str, Any]:
        return bridge.call("project.info", {})

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="Advanced Agent project-local MCP server")
    parser.add_argument("--db", default=defaults.default_db())
    parser.add_argument("--config", default=defaults.default_config())
    parser.add_argument("--transport", choices=("stdio", "sse", "streamable-http"), default="stdio")
    args = parser.parse_args()
    create_mcp(args.db, args.config).run(transport=args.transport)


if __name__ == "__main__":
    main()
