from __future__ import annotations

from dataclasses import dataclass

from advanced_agent.stores.task_store import TaskStore
from advanced_agent.summarizer import TailSummarizer
from advanced_agent.time_service import TimeService


@dataclass(slots=True)
class TaskSummaryRun:
    scanned: int
    summarized: int
    task_ids: list[str]


class TaskSummaryWorker:
    """Cheap deterministic task progress summarizer.

    This worker lets main/interactive inspect bounded progress summaries instead
    of repeatedly feeding long task tails into model context. A small-model
    summarizer can replace TailSummarizer later behind this class.
    """

    def __init__(self, tasks: TaskStore, time: TimeService, summarizer: TailSummarizer | None = None) -> None:
        self.tasks = tasks
        self.time = time
        self.summarizer = summarizer or TailSummarizer()

    def summarize_task(self, task_id: str, output_limit: int = 80) -> str:
        tail = self.tasks.get_tail(task_id, limit=output_limit)
        result = self.summarizer.summarize(tail)
        return self.tasks.append_summary(task_id, "progress", result.summary, result.important_events, result.risks, self.time.wall_ms())

    def summarize_active(self, statuses: list[str] | None = None, limit: int = 20) -> TaskSummaryRun:
        statuses = statuses or ["queued", "running", "stop", "cancel", "failed", "completed"]
        rows = self.tasks.list_tasks(statuses=statuses, limit=limit)
        summarized: list[str] = []
        for row in rows:
            task_id = row["id"]
            self.summarize_task(task_id)
            summarized.append(task_id)
        return TaskSummaryRun(scanned=len(rows), summarized=len(summarized), task_ids=summarized)
