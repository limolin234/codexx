# Preference Worker

Preference maintenance is a separate process/module. Main agent should not permanently edit its own prompt.

## Responsibilities

- read interaction history;
- extract stable user/project preferences;
- classify preferences by category;
- maintain bounded user profile summaries;
- maintain prompt overlays per target agent;
- keep total prompt injection length controlled.

## Bounded format

The first version uses categories:

- architecture;
- interaction;
- safety;
- memory;
- general fallback.

Each category has a character limit. The whole profile has a total character limit. Prompt overlays also have per-overlay and total read limits.

## Flow

```text
messages / streams
  -> PreferenceWorker
  -> user_profiles
  -> prompt_overlays
  -> ContextBuilder later
  -> model prompt
```

This keeps user preference stable without relying on vector recall every turn.
