from advanced_agent.runtime.app import RuntimeApp


def test_sqlite_vec_memory_roundtrip(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    mid = app.remember("main agent owns semantic authority over interactive quick replies", scope="test", type_="decision")
    hits = app.search_memory("semantic authority main agent", scope="test", top_k=3)
    assert hits
    assert any(hit.memory_id == mid for hit in hits)
