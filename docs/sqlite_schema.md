# SQLite Schema

`codexx` uses separate SQLite files for different lifecycles. `runtime/advanced_agent.sqlite` is runtime state, while `memory/longterm.sqlite` is the durable long-term memory asset and `memory/rawtail.sqlite` is the bounded raw-tail evidence cache.

Major groups:

- sessions/messages/interaction_streams
- agents/agent_processes
- tasks/task_state/task_events/task_output_chunks/task_summaries
- control_commands/interrupt_state
- audit_reviews
- runtime_hooks/runtime_events
- semantic_events/semantic_summaries/semantic_tasks/semantic_memory_candidates

`memory/longterm.sqlite` owns:

- memory_items/memory_vectors/memory_facets/memory_fts
- user_profiles

`memory/rawtail.sqlite` owns:

- rawtail_chunks

Vector search is vector-first; long-term SQLite hydrates vector hits by ids and stores lifecycle/source metadata. Runtime state can be partially lost on hard kill or device migration; the `memory/` directory is the stable user asset.
