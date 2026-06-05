# Memory Indexer

`MemoryIndexer` is the unified path for durable vector-indexed memory writes.

## Flow

```text
MemoryCandidate
  -> dedup by source_ref
  -> MemoryAlignment facets
  -> facet normalization / query-profile-ready labels
  -> memory_items
  -> sqlite-vec vectors, one row per facet
  -> memory_vectors mapping
```

## Candidate fields

- scope
- type
- summary
- content
- source_type
- source_id
- importance
- confidence
- facets
- metadata

## Automation

`HookKind.MEMORY_INDEX` can trigger indexing through `AutomationEngine`.

This replaces ad-hoc memory writes and keeps indexing automatic.
