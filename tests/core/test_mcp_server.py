import pytest

from advanced_agent.mcp_server import create_mcp


@pytest.mark.anyio
async def test_mcp_exposes_memory_toolcall_roundtrip(tmp_path) -> None:
    mcp = create_mcp(tmp_path / "state.sqlite", None)
    tool_names = {tool.name for tool in await mcp.list_tools()}
    assert {"memory.write", "memory.search", "context.get", "session.recent"}.issubset(tool_names)
    assert {"memory_write", "memory_search", "context_get", "session_recent"}.issubset(tool_names)
    tools = {tool.name: tool for tool in await mcp.list_tools()}
    auto_approved = {
        "context.get",
        "context_get",
        "memory.search",
        "memory_search",
        "memory.write",
        "memory_write",
        "memory.recent",
        "memory_recent",
        "session.recent",
        "session_recent",
        "session.raw_tail",
        "session_raw_tail",
        "project.info",
        "project_info",
        "workdir.chdir",
        "workdir_chdir",
        "task.list",
        "task_list",
        "task.state",
        "task_state",
        "task.tail",
        "task_tail",
        "timer.schedule",
        "timer_schedule",
        "event.wait",
        "event_wait",
    }
    for name in auto_approved:
        assert tools[name].annotations.destructiveHint is False
        assert tools[name].annotations.openWorldHint is False
    assert tools["memory.write"].annotations.destructiveHint is False
    assert tools["memory.write"].annotations.readOnlyHint is False
    assert tools["memory.write"].annotations.idempotentHint is True
    assert tools["memory.search"].annotations.readOnlyHint is True
    assert tools["workdir.chdir"].annotations.readOnlyHint is False

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

    _, search_data = await mcp.call_tool("memory.search", {"query": "toolcall previous conversation", "scope": "project:mcp-test"})
    assert search_data["ok"]
    assert search_data["hits"]
    assert "write memory" in search_data["hits"][0]["content"]

    _, alias_data = await mcp.call_tool("memory_search", {"query": "toolcall previous conversation", "scope": "project:mcp-test"})
    assert alias_data["ok"] and alias_data["hits"]


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

    _, search_data = await mcp_b.call_tool("memory.search", {"query": "concurrent terminal", "scope": "project:multi-mcp", "top_k": 12})
    assert search_data["ok"]
    assert len(search_data["hits"]) >= 6
