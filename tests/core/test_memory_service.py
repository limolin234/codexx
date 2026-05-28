from advanced_agent.runtime.app import RuntimeApp


def test_memory_service_write_search_hydrates_content_and_dedups_labels(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    result = app.memory.write(
        summary="Codex MCP should read previous records",
        content="Previous record content: use MCP context.get before context-dependent answers.",
        scope="project:mcp",
        type="decision",
    )
    assert result.created

    hits = app.memory.search("previous records context", scope="project:mcp", top_k=5)
    assert len([hit for hit in hits if hit.memory_id == result.memory_id]) == 1
    assert hits[0].content and "context.get" in hits[0].content
    assert hits[0].labels and "semantic" in hits[0].labels


def test_memory_service_recent_lists_without_query(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    app.memory.write(summary="first durable note", scope="project:recent", source_id="1")
    app.memory.write(summary="second durable note", scope="project:recent", source_id="2")

    recent = app.memory.recent(scope="project:recent", limit=2)
    assert len(recent) == 2
    assert {item.summary for item in recent} == {"first durable note", "second durable note"}
