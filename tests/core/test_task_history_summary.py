from advanced_agent.models import TaskSpec
from advanced_agent.runtime.app import RuntimeApp
from advanced_agent.summarizer import TailSummarizer


def test_task_output_backpressure_and_history(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    task_id = app.tasks.create_task(TaskSpec(goal="history", workdir=str(tmp_path)), app.time.wall_ms())
    app.tasks.append_output(task_id, "stdout", "x" * 9000, app.time.wall_ms(), max_chunk_chars=100)
    tail = app.tasks.get_tail(task_id)
    assert "[truncated]" in tail
    summary = TailSummarizer().summarize("ok\nwarning: check this\n")
    app.tasks.append_summary(task_id, "progress", summary.summary, summary.important_events, summary.risks, app.time.wall_ms())
    history = app.tasks.history(task_id)
    assert history["state"]["latest_summary"]
    assert history["summaries"]
