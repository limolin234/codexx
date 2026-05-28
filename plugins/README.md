# External Plugins

External plugins are outside the core runtime. A plugin can declare hooks in
`plugin.json`. The core schedules and fires those hooks, then emits
`plugin.hook.requested`. A plugin-specific agent/worker can handle the event and
read/write its own files or external integrations.

The core does not hard-code group summary, chat import, or other integrations.
