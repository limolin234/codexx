# SQLite Schema

SQLite is the structured state and metadata store. It is not the long-term semantic search engine.

Major groups:

- sessions/messages/interaction_streams
- agents/agent_processes
- tasks/task_state/task_events/task_output_chunks/task_summaries
- control_commands/interrupt_state
- audit_reviews
- memory_items/memory_vectors metadata

Vector search is vector-first; SQLite hydrates vector hits by ids and stores lifecycle/source metadata.
