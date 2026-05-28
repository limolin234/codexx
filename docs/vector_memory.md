# Vector Memory

Long-term memory retrieval is vector-first.

## Principle

```text
query -> query vectors -> vector DB top-k -> SQLite hydrate metadata/content
```

SQLite must not become an O(n) semantic search engine.

## Vector labels

A memory alignment agent should generate multiple retrieval labels per memory item:

- semantic
- project
- time
- methodology
- project_feature
- implementation
- decision
- preference
- procedure
- risk
- handoff
- chat
- agent_relevance

Each label may become a separate vector row in a vector database. SQLite stores `memory_id`, scope, type, source, status, lifecycle, and vector id mapping.
