from advanced_agent.hooks import HookKind
from advanced_agent.memory_indexer import MemoryCandidate
from advanced_agent.runtime.app import RuntimeApp


def test_memory_indexer_deduplicates_source(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    candidate = MemoryCandidate(
        scope="project:mem",
        type="decision",
        summary="架构优先",
        content="架构优先，可维护性优先",
        source_type="test",
        source_id="1",
    )
    first = app.memory_indexer.index(candidate)
    second = app.memory_indexer.index(candidate)
    assert first.created
    assert not second.created
    assert first.memory_id == second.memory_id


def test_memory_index_hook_indexes_text(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    app.hooks.schedule_in(
        HookKind.MEMORY_INDEX,
        target="memory:indexer",
        now_ms=app.time.wall_ms(),
        delay_ms=0,
        payload={"text": "main agent 是语义核心", "scope": "project:hook", "type": "decision"},
    )
    result = app.automation.tick()
    assert any(action.startswith("memory_index:indexed") for action in result.actions)
    hits = app.search_memory("语义核心", scope="project:hook")
    assert hits


def test_memory_indexer_writes_facets_and_fts(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    result = app.memory.write(
        summary="DB v2 uses hybrid keyword search",
        content="A rare-token-xyzzy memory should be discoverable through FTS even when vector labels are not enough.",
        scope="project:v2",
        type="decision",
    )
    assert result.created
    facet = app.db.query_one("SELECT facet_name FROM memory_facets WHERE memory_id=? AND facet_name='keywords'", (result.memory_id,))
    assert facet is not None
    fts = app.db.query_one('SELECT memory_id FROM memory_fts WHERE memory_fts MATCH ?', ('"rare-token-xyzzy"',))
    assert fts is not None
    found = app.memory.search("rare-token-xyzzy", scope="project:v2", top_k=3)
    assert found
    assert found[0].why_hit
    assert found[0].why_hit["keyword_score"] > 0
