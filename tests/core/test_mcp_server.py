import pytest

from advanced_agent.mcp_server import create_mcp


@pytest.mark.anyio
async def test_mcp_exposes_memory_toolcall_roundtrip(tmp_path) -> None:
    mcp = create_mcp(tmp_path / "state.sqlite", None)
    tool_names = {tool.name for tool in await mcp.list_tools()}
    assert {"memory.write", "context.get", "session.raw_tail", "project.info"}.issubset(tool_names)
    assert {"memory_write", "context_get", "session_raw_tail", "project_info"}.issubset(tool_names)
    tools = {tool.name: tool for tool in await mcp.list_tools()}
    auto_approved = {
        "context.get",
        "context_get",
        "memory.write",
        "memory_write",
        "session.raw_tail",
        "session_raw_tail",
        "project.info",
        "project_info",
    }
    for name in auto_approved:
        assert tools[name].annotations.destructiveHint is False
        assert tools[name].annotations.openWorldHint is False
    assert tools["memory.write"].annotations.destructiveHint is False
    assert tools["memory.write"].annotations.readOnlyHint is False
    assert tools["memory.write"].annotations.idempotentHint is True
    assert tools["context_get"].inputSchema["properties"]["mode"]["enum"] == ["supplement", "full"]
    hidden_tools = {
        "memory_archive_inactive_indexes",
        "memory_purge_deleted",
        "session_recent",
        "memory_search",
        "memory.search",
        "memory_recent",
        "memory.recent",
        "workdir_chdir",
        "task_list",
        "task_state",
        "task_tail",
        "timer_schedule",
        "event_wait",
    }
    assert hidden_tools.isdisjoint(tool_names)
    _, write_data = await mcp.call_tool(
        "memory.write",
        {
            "summary": "MCP toolcall can store previous conversation records",
            "content": "This record proves Codex can use a toolcall to write memory, then search it later.",
            "scope": "project:mcp-test",
            "type": "decision",
        },
    )
    assert write_data["ok"] and write_data["created"]

    _, ctx_data = await mcp.call_tool("context_get", {"query": "toolcall previous conversation", "scope": "project:mcp-test", "include_memory_content": True})
    assert ctx_data["ok"]
    assert ctx_data["memories"]
    assert "write memory" in ctx_data["memories"][0]["content"]

    _, recent_ctx = await mcp.call_tool("context_get", {"query": "", "scope": "project:mcp-test", "memory_top_k": 1})
    assert recent_ctx["ok"]
    assert recent_ctx["memories"][0]["summary"] == "MCP toolcall can store previous conversation records"

    assert set(tools["memory_write"].inputSchema["properties"]) == {
        "summary",
        "content",
        "scope",
        "type",
        "importance",
        "confidence",
    }


@pytest.mark.anyio
async def test_mcp_context_get_reads_recent_session_and_memory(tmp_path) -> None:
    mcp = create_mcp(tmp_path / "state.sqlite", None)
    await mcp.call_tool("memory.write", {"summary": "记忆模块已经接入 MCP", "scope": "project:ctx-test"})

    _, ctx = await mcp.call_tool("context.get", {"query": "MCP 记忆模块", "scope": "project:ctx-test"})
    assert ctx["ok"]
    assert any("记忆模块" in item["summary"] for item in ctx["memories"])


@pytest.mark.anyio
async def test_mcp_multiple_server_instances_share_db_safely(tmp_path) -> None:
    db = tmp_path / "state.sqlite"
    mcp_a = create_mcp(db, None)
    mcp_b = create_mcp(db, None)
    for i in range(12):
        server = mcp_a if i % 2 == 0 else mcp_b
        _, data = await server.call_tool(
            "memory.write",
            {"summary": f"concurrent terminal memory {i}", "scope": "project:multi-mcp", "type": "note"},
        )
        assert data["ok"]

    _, search_data = await mcp_b.call_tool("context_get", {"query": "concurrent terminal", "scope": "project:multi-mcp", "memory_top_k": 12})
    assert search_data["ok"]
    assert len(search_data["memories"]) >= 6
