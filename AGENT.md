# Advanced Agent 项目工作说明

## 项目目标

在本文件夹内构建一个“更好的本地 agent”：能高效与用户交流、管理计算机、保留长期记忆，并在架构上保持清晰、可替换、可迁移。它可以参考 OpenClaw 一类本地 agent 的目标，但不要复制复杂屎山；优先确定好边界和数据流。

## 用户提出的初始架构

1. 后续本地加入语音输入，语音输入基于专用模型和 NPU 完成。
2. 使用强大的主 agent，例如 GPT-5.5，作为思考核心：
   - 状态判断；
   - 核心思想反馈；
   - 任务拆分；
   - 是否打断/继续/升级的判断。
3. 主 agent 可以快速 fork 自身进入任务状态：
   - 保留必要上下文；
   - 完整处理具体复杂任务；
   - 不给主 agent 主循环增加过大上下文负担。
4. 主 agent 与用户对话之间插入快速小模型缓冲：
   - 低延迟响应；
   - 在慢模型思考时桥接用户；
   - 可被主 agent 打断；
   - 可被用户打断。
5. 加入向量数据库与记忆维护模型：
   - 用廉价但价值对齐的模型维护主 agent 记忆；
   - 对记忆分段；
   - 生成标签；
   - 写入向量数据库。

## 设计原则

- 先做固定而清楚的抽象，不急着把所有东西做成可配置。
- 主 agent 不直接承担所有长任务；长任务必须进入 task agent。
- 快速缓冲层不是另一个主脑，只处理延迟、状态同步和轻量沟通。
- 记忆层必须可审计，不能把所有原始聊天无脑塞进向量库。
- 工具执行必须有权限模型、日志和可回滚/可解释的操作记录。
- 面向边缘设备：模型后端、语音后端、向量库后端、工具执行后端都走接口。

## 当前进度

- 已创建项目初始 README、架构文档、记忆设计、路线图和 Python 接口骨架。
- 当前代码是最小原型，不调用真实模型；用于固定数据流和模块边界。

## 下一步建议

1. 先实现事件总线和可中断任务状态机。
2. 再实现 mock model backend，用测试验证主 agent / buffer / task agent 的交互。
3. 接入真实模型 API 前，先把日志、权限、记忆写入格式固定。
4. 语音/NPU 作为独立 input adapter，不要耦合进 agent 核心。

## 2026-05-28 第一版实现方向记录

本阶段目标：先实现可维护的第一版运行时骨架，而不是堆功能。优先级：模块化解耦、清晰上下文接口、可替换后端、能适配现成轮子（尤其 Codex CLI）。

### 核心决策

- 使用 Python 做第一版 runtime，因为 subprocess、asyncio、SQLite、模型/向量库生态最方便；进程边界固定后，后续模块可单独换 Rust/Go/C++。
- `advanced-agentd` / `Supervisor` 是确定性主控进程，唯一拥有底层进程管理能力。
- `main-agent` 是语义权威；`interactive-agent` 只做快速反馈、流式渲染和用户打断入口。
- `interactive-agent` 的输出默认是 `provisional`；`main-agent` 可用 `authoritative` 输出覆盖它。
- 不把 `kill` 暴露成常规 agent 能力。对外优先 `stop/pause/resume/cancel/snapshot`；`terminate/kill` 只做 supervisor 内部兜底。
- 新增 `audit-agent` 概念，审核优先级高于 main：`audit > main > user interrupt > interactive`。
- 加入 `interrupt-gate`：支持 interrupt enable、用户打断冷却、优先级仲裁。
- 每个模块通过自己的数据访问接口操作数据；不让 agent 直接裸用 SQL connection。
- 长期记忆采用 vector-first retrieval：向量库负责相关性召回，SQLite 只做 metadata/source/lifecycle/hydration。

### 第一版实现范围

- SQLite schema 与 store 接口。
- Time / Session / SharedState / Signal / Task / Audit 等 context 接口骨架。
- Supervisor 进程管理与有序 stop 语义。
- InterruptGate 冷却与优先级模型。
- AuditAgent mock 审核器。
- InteractiveAgent mock 快速 provisional 输出。
- MainAgent mock authoritative 输出并覆盖 interactive 输出。
- Runtime demo 验证：用户输入 -> interactive 快速反馈 -> main 权威纠正/确认 -> 数据入 SQLite。


## 2026-05-28 第一版实现完成记录

已完成第一版可维护骨架：

- `docs/runtime_model.md`：运行时进程、优先级、stop 语义。
- `docs/context_interface.md`：agent 上下文接口设计。
- `docs/sqlite_schema.md`：SQLite 静态结构说明。
- `docs/vector_memory.md`：长期记忆 vector-first 检索与相量标签设计。
- `src/advanced_agent/models.py`：共享数据模型，包括 authority、priority、stream delta、task/audit 模型。
- `src/advanced_agent/time_service.py`：wall/monotonic 时间服务。
- `src/advanced_agent/stores/`：SQLite wrapper 与 Session/Task/Audit/Control store。
- `src/advanced_agent/interrupts.py`：InterruptGate，支持用户打断冷却和优先级。
- `src/advanced_agent/audit.py`：第一版 rule-based audit agent，可阻止明显危险任务。
- `src/advanced_agent/supervisor.py`：supervisor 接入 task store、audit、interrupt gate；对外暴露 stop/cancel 等有序控制，不常规暴露 kill。
- `src/advanced_agent/agents/interactive.py`：interactive agent mock，写 provisional 快速反馈。
- `src/advanced_agent/agents/main.py`：main agent mock，写 authoritative 输出并 supersede interactive。
- `src/advanced_agent/runtime/app.py`：RuntimeApp 组合根，便于后续替换各模块实现。
- `tests/test_core.py`、`tests/test_runtime.py`：基础测试骨架。

验证情况：

- `PYTHONPATH=src python -m advanced_agent.orchestrator` 通过，可看到 interactive provisional 后 main authoritative 覆盖。
- `PYTHONPATH=src python -m compileall -q src tests` 通过。
- 手写 Python runtime checks 通过，包括 interactive/main 流程、安全 task 创建、危险任务 audit 阻止、interrupt gate 基础路径。
- 当前环境没有安装 `pytest`，所以 `python -m pytest -q` 未运行成功，错误为 `No module named pytest`。

下一步建议：

1. 实现 `CodexTaskWorker`：封装 `codex exec --json`，stdout JSONL 进入 `task_output_chunks` 和 `task_events`。
2. 把 supervisor 的 task 执行改成 asyncio 非阻塞 subprocess。
3. 实现 summarizer worker：从 task tail 生成 progress summary。
4. 接入真实 main/interactive 模型前，先稳定 prompt 输入输出 schema。
5. 实现 vector memory adapter 接口，先可用本地轻量向量库或 mock vector store。

## 2026-05-28 pytest 虚拟环境验证记录

用户确认缺失库可以用项目内 venv 安装。已创建 `.venv` 并安装：

- `pip 26.1.1`
- `pytest 9.0.3`

验证命令：

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

结果：

```text
9 passed in 0.23s
```

说明当前第一版 runtime 骨架测试全部通过。注意：首次安装 pytest 时 sandbox 内网络不可用，后经用户授权联网安装成功。


## 2026-05-28 sqlite-vec 与交互 CLI 实现记录

用户确认 4GB 边缘设备场景下不需要一开始上重型向量数据库，长期记忆价值主要来自 agent 总结与相量标签对齐，因此先接 `sqlite-vec`。

已完成：

- 在 `.venv` 中安装 `sqlite-vec 0.1.9`。
- 新增 `src/advanced_agent/vectors.py`：
  - `HashEmbedding`：确定性轻量 embedding，占位用，后续可替换真实 embedding 模型。
  - `SQLiteVecStore`：加载 sqlite-vec，创建 `vec_memory` 虚拟表，写入/搜索向量。
  - `MemoryAlignment`：第一版规则标签生成器，后续替换成廉价 memory-alignment 子 agent。
- `RuntimeApp` 接入 `SQLiteVecStore`，提供：
  - `remember(text, scope, type_)`
  - `search_memory(query, scope, top_k)`
- 新增 `src/advanced_agent/cli.py`，可终端交互试用：
  - `/mem TEXT`
  - `/search QUERY`
  - 普通文本走 interactive provisional -> main authoritative mock 流程。
- 新增 `tests/test_vectors_cli.py`，验证 sqlite-vec 记忆写入和检索路径。

验证：

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

结果：

```text
10 passed in 0.16s
```

交互 smoke test：

```bash
printf '/mem main agent semantic authority
/search authority
hello
/exit
' | PYTHONPATH=src .venv/bin/python -m advanced_agent.cli --db runtime/demo.sqlite --workdir .
```

已验证 `/mem` 写入、`/search` 命中、普通输入产生 interactive/main 两阶段输出。

注意：当前 `HashEmbedding` 不是语义模型，只用于先打通 sqlite-vec 管线。真正效果要靠后续 memory-alignment agent 生成高质量标签，以及替换更好的本地 embedding 后端。


## 2026-05-28 真实模型配置接入记录

用户希望使用 JSON 格式 `.env`，按模型名字分类，每个模型名对应自己的 `base_url` / `api_key`，并能指定：

- `interactive_model`
- `main_model`
- `audit_model`
- `codex_model` 使用默认

已实现：

- 新增 `.env.example.json` 模板。
- `.gitignore` 忽略 `.env.json` 和 `.env.*.json`，但保留 `.env.example.json`。
- 新增 `src/advanced_agent/config.py`：加载 JSON 配置，按 role 找 model。
- 新增 `src/advanced_agent/llm.py`：最小 OpenAI-compatible `/chat/completions` client，避免 SDK 绑定。
- `InteractiveAgent` 可选接入真实 fast model；失败时回退规则快速反馈。
- `MainAgent` 可选接入真实 main model；失败时回退规则权威回复。
- CLI 新增 `--config .env.json` 参数，默认读取 `.env.json`，不存在则使用 fallback。
- 新增 `tests/test_config.py`。

验证：

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

结果：

```text
11 passed
```

当前尚未把 `audit_model` 接入 LLM 审核，仍为规则审核；`codex_model` 仍按设计保留给 Codex CLI 默认配置。


## 2026-05-28 ikuncode 403/1010 调试记录

用户用 `.env.json` 接入 `https://api.ikuncode.cc/v1` 后，main 模型调用失败：

```text
LLM HTTP 403: error code: 1010
```

直接用 `.env.json` 的 main_model 发送最小 `/chat/completions` 请求，确认：

- URL: `https://api.ikuncode.cc/v1/chat/completions`
- model: `gpt-5.5`
- 默认 `Python-urllib` User-Agent 被 Cloudflare 拒绝：`Error 1010 browser_signature_banned`
- 改为 `User-Agent: curl/8.5.0` 或 `OpenAI/Python 1.0` 后请求成功返回 `OK`

已修复 `src/advanced_agent/llm.py`：请求头增加：

```text
Accept: application/json
User-Agent: OpenAI/Python 1.0
```

## 2026-05-28 interactive 先返回修正记录

用户指出当前 CLI 虽然数据结构区分了 `interactive/provisional` 和 `main/authoritative`，但实际输出仍等 main 完成后一起打印，不符合快速反馈目标。

已修正：

- `RuntimeApp.start_user_request(session_id, text)`：只执行 interactive，立即返回 `request_id` 和 provisional delta。
- `RuntimeApp.finish_user_request(session_id, request_id, workdir)`：对已有 request 执行 main authoritative 步骤。
- `RuntimeApp.handle_user_text(...)` 保留为兼容同步封装。
- CLI 改为先打印 interactive delta 并 flush，再调用 main 并打印 authoritative delta。
- 新增测试 `test_request_can_return_interactive_before_main`。

验证：

```text
12 passed in 0.23s
```

注意：这一步实现的是“交互层先返回”，还不是模型 token-level streaming。真正 token streaming 下一步需要扩展 LLM client 支持流式响应，并让 `interaction_streams` 按 token/chunk 追加。

## 2026-05-28 hook 唤醒语义修正

用户 уточ明：定时唤醒主要应唤醒 `main-agent` 做内部状态检查，不一定对用户说话。只有 main 判断有必要时，才触发 `interactive-agent` 对用户输出。

已调整：

- `HookKind.CHECK_STATE` 表示内部状态检查。
- `HookScheduler` 文档说明：hook 默认是内部 wake，不是 user notification。
- `sleep_backoff_for_idle()` 表示下一次 main-agent 内部检查间隔，而不是交互提示间隔。
- 新增测试 `test_hook_scheduler_wakes_internally`。

## 2026-05-28 架构基线固化

用户确认当前架构方向可以，并强调项目会长期演进，好的架构比急于求成更重要。

已新增：

- `docs/architecture_v1.md`

该文件固化当前第一版架构基线：

- supervisor / main / interactive / audit / task agent 职责；
- 用户不直接和 main agent 交流，main 内容由 interactive 复述；
- shared/private/task/memory context 分层；
- SQLite 与 sqlite-vec 分工；
- vector-first 长期记忆；
- hook 唤醒 main 但不默认对用户说话；
- audit > main > user interrupt > interactive；
- stop 优先、kill 兜底；
- JSON 模型配置；
- 当前已实现和未完成事项；
- 新功能加入前必须先明确 ownership/context/storage/audit/backend。

## 2026-05-28 基础设施优先阶段记录

用户要求先搭鲁棒、高性能基础架构，完成后再继续做 demo。

已新增/增强：

- `docs/infrastructure_v1.md`：基础设施层目标和边界。
- `src/advanced_agent/errors.py`：统一 runtime 错误类型。
- `src/advanced_agent/events.py`：持久化 in-process `EventBus` 和 `EventStore`。
- `src/advanced_agent/health.py`：基础健康检查。
- `SQLiteStore` 增强：
  - `PRAGMA journal_mode=WAL`
  - `PRAGMA synchronous=NORMAL`
  - `PRAGMA busy_timeout=5000`
  - `PRAGMA temp_store=MEMORY`
  - `transaction()` 上下文
  - `optimize()`
  - `close()`
- schema 新增 `runtime_events` 表和索引。
- `RuntimeApp` 接入 `EventBus` 和 `HealthChecker`，关键流程写入 runtime event：
  - `session.created`
  - `interactive.provisional`
  - `main.decided`
  - `interactive.authoritative_render`
- 新增 `tests/test_infrastructure.py`，覆盖事件持久化、事务回滚、健康检查和 RuntimeApp 事件记录。

验证：

```text
16 passed in 0.13s
```

下一步基础设施建议：

1. 持久化 hook 表和 hook runtime loop。
2. async subprocess 基础执行器，为 CodexTaskWorker 做准备。
3. task output ring buffer 和 backpressure。
4. 统一配置校验和 doctor 命令。
5. conversation compaction/cleanup job。

## 2026-05-28 Async subprocess/tail 基础设施记录

用户继续基础设施优先，并询问 subprocess 是否需要随时返回 tail、对话和工具调用，以便上层 agent 无干扰查看进度。结论：需要。上层 agent 不应打扰 task agent，而应读 supervisor 管理的 stdout/stderr tail、task events 和后续 summaries。

同时用户确认当前不急于 Docker 化。最终目标是系统上的管理 AI，是系统核心依赖，需要管理宿主机，因此默认应跑在宿主机上；Docker 后续只能作为可选 task isolation，不作为核心 runtime 默认形态。

已新增：

- `docs/subprocess_runtime.md`
- `src/advanced_agent/processes.py`
- `tests/test_processes.py`

实现内容：

- `TailBuffer`：限制行数和字符数的 ring tail。
- `AsyncSubprocessRunner`：基于 `asyncio.create_subprocess_exec` 的非阻塞子进程运行器。
- `ManagedProcess`：保存 command/cwd/process/tail/returncode/timestamps。
- 支持：
  - stdout/stderr 实时读取；
  - output callback；
  - `tail(process_id, stream, limit)`；
  - `wait(process_id)` 等待读取器收尾；
  - `stop(process_id)` 优雅 terminate，超时后 kill 兜底。

验证：

```text
19 passed in 0.40s
```

后续 CodexTaskWorker 应基于 `AsyncSubprocessRunner`，把 Codex JSONL/stdout/stderr 解析成：

- task_output_chunks;
- task_events;
- tool_call request/output;
- final report;
- usage;
- error events。

## 2026-05-28 CodexTaskWorker 基础层记录

继续基础设施优先。本阶段没有真实跑 Codex，而是先实现可测试的 Codex task backend 边界。

已新增：

- `docs/codex_task_worker.md`
- `src/advanced_agent/codex_worker.py`
- `tests/test_codex_worker.py`

实现内容：

- `CodexJsonlParser`：解析 `codex exec --json` 的 JSONL 行，归一化为 task event 类型。
  - `thread.started` -> `codex.thread.started`
  - `turn.completed` -> `codex.turn.completed`
  - `item.completed` with `agent_message` -> `codex.item.agent_message`
  - 非 JSON 行 -> `codex.raw_text`
- `CodexTaskWorker`：
  - 构造 `codex exec --json --skip-git-repo-check -C <workdir> <prompt>`；
  - 基于 `AsyncSubprocessRunner` 启动子进程；
  - stdout/stderr 写入 `task_output_chunks`；
  - stdout JSONL 解析后写入 `task_events`；
  - wait 后更新 task_state 为 `completed/failed` 并写 `codex.process.exit`。
- 测试使用 fake JSONL Python 子进程，不消耗真实模型调用，验证 stdout/tail/event/state 全链路。

验证：

```text
21 passed in 0.45s
```

下一步基础设施建议：

1. 将 `CodexTaskWorker` 接入 `Supervisor.spawn_task` 的 backend 路由，但默认仍可不自动真实执行。
2. 增加 task history 查询接口，聚合 state/tail/events/output。
3. 增加 summarizer 基础接口，从 tail/events 生成 progress summary。
4. 增加 backpressure：限制 task_output_chunks 写入频率和单条大小。

## 2026-05-28 PreferenceWorker/Profile 基础设施记录

用户要求先完成 task history/summarizer/backpressure 等基础设施，并试做用户喜好总结/用户画像 agent。用户特别提出：可以通过格式、分类、字数限制来控制总字数，同时保持效果。

已完成：

- schema 新增：
  - `user_profiles`
  - `prompt_overlays`
- 新增 `src/advanced_agent/stores/profile_store.py`：
  - `ProfileStore.upsert_profile/get_profile`
  - `PromptOverlayStore.replace_overlay/overlays_for`
  - 支持 overlay 总长度限制。
- 新增 `src/advanced_agent/preferences.py`：
  - `PreferenceWorker`
  - `PreferenceLimits`
  - 按 category 维护 bounded profile：architecture / interaction / safety / memory。
  - 生成 main 和 interactive 的 prompt overlay。
- 新增 `src/advanced_agent/summarizer.py`：
  - `TailSummarizer`，第一版规则 summarizer，后续可替换小模型。
- `TaskStore` 增强：
  - `append_output(..., max_chunk_chars=8192)`，超长 chunk 截断并标记 `[truncated]`。
  - `append_summary(...)`
  - `history(...)` 聚合 state/output/events/summaries。
- `RuntimeApp` 接入 profiles/overlays/preferences。
- 新增测试：
  - `tests/test_preferences.py`
  - `tests/test_task_history_summary.py`

验证：

```text
24 passed in 0.48s
```

当前 PreferenceWorker 仍是规则版。后续可以替换成专门的 preference-maintenance 子 agent，但应继续保持：分类输出、单类字数限制、总 profile 字数限制、overlay 总注入长度限制。

## 2026-05-28 CodexTaskWorker 完善记录

用户要求继续完善 Codex 调用相关基础设施。

已完成：

- 新增 `CodexCommandSpec`：
  - `prompt`
  - `workdir`
  - `sandbox`
  - `approval`
  - `skip_git_repo_check`
  - `extra_args`
- `CodexTaskWorker.build_command()` 支持按 policy 构造：
  - `--sandbox <mode>`
  - `--ask-for-approval <mode>`
  - `--skip-git-repo-check`
  - `extra_args`，如 `--ephemeral`
- `CodexTaskHandle` 记录：
  - `latest_agent_message`
  - `usage`
- `CodexTaskWorker` 对解析事件做进一步处理：
  - `codex.item.agent_message` 写入 `task_summaries(kind=codex_agent_message)` 并更新 latest summary；
  - `codex.turn.completed` 提取 usage，写入 `task_summaries(kind=usage)`；
  - function/tool 类事件更新 task stage 为 `tool`；
  - wait 后写 `codex.process.exit`，并将最新 agent message 写成 `task_summaries(kind=final)`。
- 修正 `TaskStore.append_summary()`：不再把已完成任务状态错误改回 `running`，只更新 `latest_summary`。
- 测试增强：
  - fake Codex JSONL 现在验证 agent_message、usage、final summary；
  - 验证 `CodexCommandSpec` 的 sandbox/approval/extra_args 构造。

验证：

```text
25 passed in 0.53s
```

## 2026-05-28 自动化 hook/维护引擎记录

用户强调：手动维护不现实，必须通过大量 hook 和定时自动触发来维护记忆、画像、索引和上下文。

已完成第一版自动化基础：

- schema 新增 `runtime_hooks` 表和索引。
- `HookKind` 新增：
  - `PREFERENCE_MAINTENANCE`
  - `MEMORY_INDEX`
- 新增 `src/advanced_agent/stores/hook_store.py`：
  - `schedule`
  - `schedule_in`
  - `ensure_unique`
  - `due`
  - `mark_fired`
- 新增 `src/advanced_agent/automation.py`：
  - `AutomationEngine`
  - `ensure_session_maintenance`
  - `tick`
  - 当前自动处理 `PREFERENCE_MAINTENANCE`，调用 `PreferenceWorker.update_from_session`。
- `RuntimeApp.start_user_request` 自动为 session 安排 preference maintenance hook。
- hook 触发后写入 `runtime_events` 的 `hook.fired`。
- 新增 `docs/automation_hooks.md`。
- 新增 `tests/test_automation.py`。

当前自动链路：

```text
user message
  -> schedule PREFERENCE_MAINTENANCE hook
  -> AutomationEngine.tick
  -> PreferenceWorker
  -> user_profiles / prompt_overlays
  -> hook.fired event
```

验证：

```text
27 passed in 0.60s
```

下一步应继续把以下维护任务接到 hook 系统：

1. `MEMORY_INDEX`：自动把 memory candidates/indexable summaries 写入 sqlite-vec。
2. `CHECK_STATE`：唤醒 main-agent 内部检查 task/session 状态，不默认对用户说话。
3. `COMPACT_MEMORY`：对话压缩、旧输出清理、profile 刷新。
4. 后台 runtime loop：周期性调用 `AutomationEngine.tick()`。

## 2026-05-28 上下文预算与自动压缩记录

用户指出有相量数据库后，对话总长度没必要太长，太长很贵。可以在超过最大容量约 50% 时，把旧对话放进数据库，后续通过短期检索取回。

已实现第一版 char-budget 方案：

- 新增 `src/advanced_agent/context_budget.py`
  - `ContextBudget(max_chars, compact_threshold_ratio=0.5, recent_ratio, retrieved_ratio)`。
- 新增 `src/advanced_agent/compaction.py`
  - `ConversationCompactor.maybe_compact(session_id, scope)`。
  - 当未压缩消息超过阈值时，保留 recent window，把旧 prefix 总结成 `session_summary` 写入 sqlite-vec，并将旧消息标记 `compacted=1`。
- 新增 `src/advanced_agent/context_builder.py`
  - `ContextBuilder.build_for_main(session_id, query, scope)`。
  - 从 uncompacted recent messages + sqlite-vec retrieved memories 组装 bounded context。
- `SessionStore` 增强：
  - `session_messages`
  - `uncompacted_char_count`
  - `mark_compacted_before`
- `AutomationEngine` 的 `COMPACT_MEMORY` hook 现在可调用 `ConversationCompactor`。
- `RuntimeApp` 接入：
  - `compactor`
  - `context_builder`
- 新增 `docs/context_budget_compaction.md`。
- 新增 `tests/test_compaction_context.py`。

当前策略：

```text
live dialogue > 50% budget
  -> compact older messages
  -> write session_summary memory
  -> index into sqlite-vec
  -> mark old raw messages compacted
  -> ContextBuilder later retrieves relevant summaries
```

验证：

```text
29 passed in 0.62s
```

当前是字符预算近似，后续可以替换为 token-aware budget，但接口不变。

## 2026-05-28 外部插件 hook 接口记录

用户提出：可以提供额外插件文件夹，用于群总结等其他接入；核心模式和分工基本冻结。插件接入也要能让 agent 设置 hook、触发 agent，然后由 agent 自己写入。写入细节可由外部插件自己处理，核心主要提供 hook 接口。

已完成：

- `HookSpec.kind` 改为可扩展字符串，保留内建 `HookKind` 常量，同时支持 `plugin.*` 自定义 hook。
- `HookStore` 支持自定义 hook kind，不再强制枚举反序列化。
- `AutomationEngine` 遇到 `plugin.*` hook 时不做业务处理，而是发布：
  - `plugin.hook.requested`
- 新增 `src/advanced_agent/plugins.py`：
  - `PluginHookSpec`
  - `PluginManifest`
  - `PluginRegistry`
  - 从 `plugins/<name>/plugin.json` 加载 manifest；
  - 将插件默认 hook 注册进 `HookStore`。
- 新增 `plugins/README.md`。
- 新增示例插件：
  - `plugins/group_summary/plugin.json`
- 新增 `docs/plugin_hooks.md`。
- 新增 `tests/test_plugins.py`。

当前插件机制：

```text
plugins/<name>/plugin.json
  -> PluginRegistry.load()
  -> schedule_default_hooks()
  -> HookStore
  -> AutomationEngine.tick()
  -> runtime_events: plugin.hook.requested
  -> plugin-specific agent/worker 自己处理读写
```

验证：

```text
30 passed in 0.52s
```

## 2026-05-28 架构审查记录

用户要求进一步打磨核心架构，先看架构有没有问题，优先打磨架构，确认没问题后再替换占位实现。

已新增：

- `docs/architecture_review_2026-05-28.md`

审查结论：当前核心角色拆分是合理的，可作为 baseline 冻结：

```text
supervisor / main / interactive / audit / task / memory / plugin
```

主要风险不是角色拆分，而是以下契约还不够强：

1. main decisions 需要一等持久化，不能只靠 stream/render return value。
2. schema 需要 migration/version 机制。
3. ContextBuilder 应成为唯一 prompt 组装路径。
4. AutomationEngine 需要真实 runtime loop。
5. MemoryIndexer 需要统一管线。
6. 插件 hook 后续需要 plugin worker/permission/data-dir 合约。

建议下一步先修结构契约，顺序：

1. `MainDecisionStore` 和 `main_decisions` 表。
2. 中央化 ContextBuilder prompt assembly。
3. DB migration/version。
4. MemoryIndexer。
5. background automation loop。
6. 最后再替换真实 embedding/model/audit/streaming。

## 2026-05-28 MainDecisionStore 与架构图记录

用户要求先完成架构问题，并询问能否把架构变成图，而不是隐式相互调用。

已完成：

- schema 新增 `main_decisions` 表和索引。
- 新增 `src/advanced_agent/stores/main_decision_store.py`：
  - `MainDecision`
  - `MainDecisionStore.add`
  - `MainDecisionStore.latest_for_request`
- `MainAgent` 现在会把内部语义结论持久化为 `main_decisions`。
- `RuntimeApp.finish_user_request` 从 `MainDecisionStore` 读取 `user_visible_instruction`，再交给 `InteractiveAgent` 渲染。
- `runtime_events.main.decided` 现在记录 `decision_id`。
- 新增 `docs/architecture_diagrams.md`，包含 Mermaid 图：
  - process/role topology;
  - user request flow;
  - task/Codex progress inspection;
  - memory indexing/retrieval;
  - hook automation;
  - plugin hook flow。

这一步把 main -> interactive 从临时返回值推进到持久决策表，减少隐式耦合。

验证：

```text
30 passed in 0.57s
```

## 2026-05-28 测试分层与插件防护记录

用户提出为了长期维护，应有单独文件夹测试核心模块和接入模块；外接模块要防严，避免把核心炸掉。

已完成：

- 测试目录重组：
  - `tests/core/`：核心 store/runtime/config/process/infrastructure。
  - `tests/integration/`：automation、Codex worker、compaction、preferences、vector memory 等跨模块流。
  - `tests/plugins/`：外部插件接口和严格校验。
- 新增 `tests/README.md`。
- 新增 `docs/testing_strategy.md`。
- `PluginRegistry` 增强 manifest 校验：
  - plugin name 必须非空且 path-safe；
  - hook kind 必须在自身 namespace 下：`plugin.<name>.*`；
  - hook target 必须以 `plugin:` 开头，不能直接指向 core/supervisor；
  - hooks 数量上限 32；
  - `repeat_ms` 不得小于 1000；
  - payload JSON 大小上限 4096 字符。
- 新增 `PluginValidationError`。
- 新增 `tests/plugins/test_plugin_validation.py`，覆盖越界 hook namespace、非法 target、过快 repeat。

验证：

```text
33 passed in 0.60s
```

## 2026-05-28 MigrationRunner 与 Doctor 记录

用户要求继续补最重要的核心模型/基础契约。本阶段完成 DB schema version 与 doctor 命令。

已完成：

- 新增 `src/advanced_agent/migrations.py`：
  - `CURRENT_SCHEMA_VERSION = 1`
  - `MigrationRunner`
  - `MigrationStatus`
  - `schema_meta` 表维护 `schema_version`
- `SQLiteStore.init_schema()` 改为调用 `MigrationRunner.migrate()`。
- 新增 `src/advanced_agent/doctor.py`：
  - `Doctor`
  - `DoctorReport`
  - CLI: `python -m advanced_agent.doctor`
- 新增 `docs/migrations_doctor.md`。
- 新增 `tests/core/test_migrations_doctor.py`。

Doctor 当前检查：

- SQLite health；
- schema version；
- sqlite-vec；
- Codex CLI；
- `.env.json` 配置加载；
- interactive/main/audit model 是否配置 key；
- plugin manifest 校验。

验证：

```bash
PYTHONPATH=src .venv/bin/python -m advanced_agent.doctor --db runtime/doctor.sqlite --config .env.json --json
```

当前本机输出显示核心检查均通过，包括 sqlite-vec、Codex CLI、模型配置、插件加载。

测试：

```text
35 passed in 0.58s
```

下一步建议继续修核心契约：让 `ContextBuilder` 成为唯一 prompt assembly 路径，避免 prompt 分散在 agent 内部。

## 2026-05-28 PromptBuilder 中央化记录

继续补核心架构契约：让 `ContextBuilder`/`PromptBuilder` 成为 prompt assembly 的唯一入口，避免 interactive/main 各自散拼 prompt。

已完成：

- 新增 `src/advanced_agent/prompt_builder.py`：
  - `PromptBundle`
  - `PromptBuilder`
  - `interactive_quick(user_text)`
  - `interactive_render(main_text)`
  - `main_decision(session_id, request_id, user_text)`
- `PromptBuilder` 统一注入：
  - role base instruction；
  - `prompt_overlays`；
  - `ContextBuilder` recent context；
  - sqlite-vec retrieved memory；
  - latest user message。
- `InteractiveAgent` 改为通过 `PromptBuilder` 获取 quick/render prompt。
- `MainAgent` 改为通过 `PromptBuilder` 获取 main decision prompt。
- `RuntimeApp` 创建并注入统一 `PromptBuilder`。
- 新增 `docs/prompt_builder.md`。
- 新增 `tests/core/test_prompt_builder.py`。

验证：

```text
37 passed in 0.63s
```

剩余核心契约优先级：

1. `MemoryIndexer` 统一管线。
2. background runtime loop。
3. 真实 embedding/alignment/audit/streaming 替换。

## 2026-05-28 工具资源模型修正

用户指出工具调用不应在 prompt 中硬编码“工具不可用”，而应根据实际可用工具来分配；工具应作为资源进行分配。需要维护 Codex 下层执行可用工具/能力，同时讨论 main agent 是否提供工具调用。

结论：

- 工具是 runtime capability/resource，由 supervisor/resource manager 分配。
- main agent 应有基本受控工具调用能力，用于系统管理和判断：task state/tail/history、memory search、hook scheduling、task request、stop/cancel request、audit request、capability inspection。
- main agent 不应直接拥有 raw shell 或危险 OS 工具。
- interactive agent 只应拥有最小只读能力和 interrupt submission，不直接执行工具。
- 重型/危险执行交给 task agent/CodexTaskWorker。
- Codex 可用能力由 Codex CLI config、sandbox、approval、workdir、audit policy、runtime permission policy 决定；核心应维护 Codex backend capability record，让 main 能知道可委派任务类型。

已完成：

- 新增 `docs/tool_resource_model.md`。
- 修正 `PromptBuilder.interactive_quick`：不再说工具不可用，而是说不要声称已执行工具，实际可用工具由 runtime capability/resource 决定。

后续需要实现：

- `ToolRegistry`
- `CapabilityView`
- `ToolRequest/ToolResult`
- `ResourcePolicy`
- `CodexCapabilityProbe`

## 2026-05-28 CapabilityRouter/BackendRegistry 记录

用户提出：skill 和工具不应自己重造，重型 skill 交给 Codex，下层可用工具/skill 由 Codex 管；但延迟敏感和系统管理能力应留在 core。需要抽象能力路由而不是暴露所有底层工具。

已完成：

- 新增 `src/advanced_agent/capabilities.py`：
  - `LatencyClass`
  - `RiskClass`
  - `Capability`
  - `RouteDecision`
  - `BackendRegistry`
  - `CapabilityRouter`
- 默认能力：
  - `task_state` -> core, low latency;
  - `memory_search` -> core;
  - `hook_schedule` -> core;
  - `interrupt_request` -> core;
  - `code_editing` -> codex-cli, high latency, task + audit;
  - `project_analysis` -> codex-cli;
  - `document_generation` -> codex-cli;
  - `plugin_hook` -> plugin。
- `RuntimeApp` 接入：
  - `capabilities`
  - `capability_router`
- `PromptBuilder.main_decision` 现在注入 abstract capability list，而不是注入底层所有工具/skill。
- 新增 `docs/capability_router.md`。
- 新增 `tests/core/test_capabilities.py`。

设计结论：

- main agent 看抽象 capability，不看所有 Codex skill。
- core 只保留低延迟管理能力。
- 重型代码/文件/shell/文档任务走 CodexTaskWorker。
- interactive 仍不直接执行工具。

验证：

```text
40 passed in 0.69s
```

## 2026-05-28 MemoryIndexer 统一管线记录

继续补核心契约：统一记忆写入/标签/索引路径，避免 `/mem`、compaction、summaries 各自写一套。

已完成：

- 新增 `src/advanced_agent/memory_indexer.py`：
  - `MemoryCandidate`
  - `MemoryIndexResult`
  - `MemoryIndexer`
- `MemoryIndexer.index()` 流程：
  - 根据 `source_type/source_id/content` 生成 `source_ref`；
  - 用 `source_ref` 去重；
  - 调用 `MemoryAlignment.labels_for()`；
  - 调用 `SQLiteVecStore.add_memory()` 写入 `memory_items`、`sqlite-vec`、`memory_vectors`。
- `SQLiteVecStore.add_memory()` 支持：
  - `confidence`
  - `source_ref`
- `RuntimeApp.remember()` 改为走 `MemoryIndexer`。
- `RuntimeApp` 接入 `memory_indexer`。
- `AutomationEngine` 接入 `memory_indexer`，`HookKind.MEMORY_INDEX` 现在可自动索引 payload 里的文本。
- 新增 `docs/memory_indexer.md`。
- 新增 `tests/integration/test_memory_indexer.py`。

验证：

```text
42 passed in 0.72s
```

当前仍是规则 `MemoryAlignment` + `HashEmbedding`，但写入管线已经统一。后续替换 alignment agent 或 embedding backend 不影响上层。

## 2026-05-28 RuntimeLoop 与 Codex backend 骨架记录

本轮继续按“架构优先、可维护性优先”推进，先补运行时骨架，不急着做 UI/demo。

已完成：

- 新增 `src/advanced_agent/runtime/loop.py`：
  - `RuntimeLoopConfig`；
  - `RuntimeLoop.tick_once()`；
  - async `start()` / `stop()`；
  - 周期调用 `AutomationEngine.tick()`；
  - 发布 `runtime.loop.started`、`runtime.tick`、`runtime.loop.stopped`、`runtime.loop.error` 事件。
- 新增 `src/advanced_agent/runtime/service.py`：
  - `RuntimeService` 作为 `RuntimeApp + RuntimeLoop` 的嵌入式服务封装；
  - 支持 async context manager，方便后续 daemon/CLI/UI 复用。
- `RuntimeApp` 接入：
  - `AsyncSubprocessRunner`；
  - `CodexTaskWorker`；
  - `Supervisor(..., codex_worker=...)`。
- `Supervisor` 增强为真正 task backend 管理入口：
  - 保留同步 `spawn_task()` 作为只入队的 admission path；
  - 新增 async `spawn_task_async(..., start=True)`；
  - 新增 async `start_task()`；
  - 保存 `task_handles`、`task_waiters`、`task_workers`，上层可无干扰查看 task/process 映射；
  - 新增 async `request_task_control_async()`，可在接受 stop/cancel 后停止底层 backend；
  - 目前支持 `codex-cli` backend，测试中用 fake JSONL subprocess，不依赖真实 Codex。
- `TaskStore` 新增 `get_task_spec()`，用于 supervisor 从 SQLite 恢复 task 启动参数。
- 新增测试：
  - `tests/core/test_runtime_loop.py`；
  - `tests/integration/test_supervisor_codex_backend.py`。

验证：

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

结果：

```text
46 passed in 0.91s
```

下一步建议：

1. 做 `CapabilityExecutor`，把 main agent 能调用的核心能力抽象成结构化请求/结果：task_state、task_tail、task_history、memory_search、hook_schedule、interrupt_request。
2. 再把 main agent 的“抽象能力列表”与 executor 对齐，不暴露底层 Codex 工具细节。
3. 然后实现 interaction streaming：interactive 快速输出、main 后台决策、interactive 统一 render main 输出。

## 2026-05-28 CapabilityExecutor 结构化能力接口记录

本轮根据“官方 LLM tool-call 可用，但内部不要绑定模型接口”的原则，补了结构化能力层。

核心边界：

```text
官方 LLM tool-call / 本地 JSON / plugin event
  -> adapter
  -> CapabilityRequest
  -> CapabilityExecutor
  -> Supervisor / TaskStore / SQLiteVecStore / HookStore / CodexTaskWorker
  -> CapabilityResult
```

已完成：

- 新增 `src/advanced_agent/capability_executor.py`：
  - `CapabilityRequest`：provider-neutral 内部调用 IR；
  - `CapabilityResult`：统一结果；
  - `CapabilityExecutor`：统一执行入口；
  - `OpenAIToolAdapter`：官方 OpenAI-style tool schema 与内部 CapabilityRequest 之间的 adapter。
- 第一批内部能力：
  - `task_state`
  - `task_tail`
  - `task_history`
  - `memory_search`
  - `hook_schedule`
  - `interrupt_request`
  - `spawn_task`
- `RuntimeApp` 接入 `capability_executor`。
- `BackendRegistry` 增补与 executor 对齐的能力项：`task_tail`、`task_history`、`spawn_task`。
- 新增 `docs/capability_executor.md`，记录边界，避免以后把官方 tool schema、runtime 执行逻辑、底层工具混在一起变成屎山。
- 新增 `tests/core/test_capability_executor.py`，验证 task/memory/hook/spawn/audit/tool-adapter 路径。

验证：

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

结果：

```text
50 passed in 0.96s
```

下一步建议：

1. 让 main agent 的模型调用真正支持官方 tool-call：模型输出 tool call -> `OpenAIToolAdapter` -> `CapabilityExecutor` -> tool result -> main 继续推理。
2. 给 capability 增加 per-role permission policy，明确 main / interactive / audit / plugin 各自能调用什么。
3. 对 `spawn_task`、`interrupt_request`、`plugin.*` 增加更完整的 audit 策略。

## 2026-05-28 MainAgent 官方 tool-call 循环记录

本轮完成 main agent 的第一版官方 tool-call 使用路径，同时保持 runtime 内部 Capability 边界。

已完成：

- `src/advanced_agent/llm.py`：
  - `ChatMessage` 支持 `tool_call_id` / `tool_calls`；
  - 新增 `ToolCall`；
  - 新增 `ChatResponse`；
  - `OpenAICompatibleClient.chat_complete(..., tools=..., tool_choice=...)` 支持 OpenAI-style tool calling；
  - 原 `chat()` 保持兼容，返回文本。
- `src/advanced_agent/agents/main.py`：
  - main agent 在有 `capability_executor` 和支持 `chat_complete` 的模型时进入 tool loop；
  - 使用 `OpenAIToolAdapter.tool_schemas()` 给模型提供官方 tool schema；
  - 模型 tool call -> `CapabilityRequest` -> `CapabilityExecutor` -> tool message -> 模型继续；
  - tool loop 有最大轮数限制，避免无限循环；
  - main decision 写入 `main_decisions`，tool 执行记录写入 `task_requests_json`；
  - 用户侧仍由 interactive render main 结论。
- `RuntimeApp` 给 `MainAgent` 注入 `capability_executor`。
- 新增 `docs/main_tool_loop.md`。
- 新增 `tests/integration/test_main_tool_loop.py`，用 fake model 验证：
  - main 输出官方 tool call；
  - adapter 转内部 CapabilityRequest；
  - executor 执行 `memory_search`；
  - tool result 回给 main；
  - main 返回最终结论；
  - interactive 渲染用户可见回复。

验证：

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

结果：

```text
51 passed in 1.10s
```

下一步建议：

1. 增加 per-role capability permission policy，防止 interactive/plugin 等越权调用。
2. 给 high/medium risk capability 接上更细的 audit policy。
3. 再做 interactive/main 的后台非阻塞请求流，避免 CLI 里看起来 interactive 和 main 一起返回。

## 2026-05-28 Capability 权限与审核补强记录

继续按模块边界补核心安全/维护结构：

- `CapabilityExecutor` 新增 first-pass per-role permission policy：
  - `main`：task read / memory_search / hook_schedule / interrupt_request / spawn_task；
  - `interactive`：只允许低延迟 task read，即 `task_state` / `task_tail`；
  - `audit`：task read / memory_search / interrupt_request；
  - `memory`：memory_search / hook_schedule；
  - `task`：task read；
  - `supervisor`：全部。
- 未授权 capability 默认拒绝，避免 interactive/plugin 等路径越权。
- `interrupt_request` 增加 audit 记录；plugin hook schedule 也进入 audit 路径。
- `spawn_task` 继续由 `Supervisor` 走 audit admission。
- `docs/capability_executor.md` 增补 role permission 说明。
- `tests/core/test_capability_executor.py` 增补权限与 interrupt audit 测试。

验证：

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

结果：

```text
53 passed in 0.97s
```

下一步建议：实现 interactive/main 的真正非阻塞请求路径，让用户请求先返回 interactive provisional，main 在后台跑完后再通过 interactive authoritative render 追加输出。

## 2026-05-28 Background interaction 骨架记录

本轮补 interactive/main 两阶段后台请求骨架，目标是让用户请求先得到 interactive provisional，main 后台完成后再由 interactive authoritative render 追加输出。

已完成：

- `RuntimeApp` 新增：
  - `background_requests`：记录 request_id -> asyncio task；
  - `start_user_request_background(session_id, text, workdir)`：立即写入用户消息并返回 interactive provisional，同时创建后台 main 任务；
  - `wait_user_request(request_id, timeout_seconds)`：等待后台 main/render 完成；
  - `_finish_user_request_task(...)`：后台执行 main decision + interactive render，并发布完成/失败事件。
- 新增事件：
  - `interaction.background.started`
  - `interaction.background.completed`
  - `interaction.background.failed`
- 新增 `tests/integration/test_background_interaction.py`，验证：
  - provisional 先返回；
  - main 后台完成后追加 authoritative；
  - 事件正确落库。

验证：

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

结果：

```text
54 passed in 1.11s
```

注意：当前底层 `OpenAICompatibleClient` 仍是同步 urllib 实现，SQLite connection 也不适合直接跨线程乱用。因此这一版 background 是运行时语义骨架：先保证交互流和事件边界。后续如果要做到真正高并发非阻塞，需要在同一边界下替换为 async HTTP client 或给后台 worker 独立 DB connection。

## 2026-05-28 Async LLM backend 升级记录

用户确认可以加入稳定网络依赖，后续升级容易即可。本轮加入 `httpx`，用于真正异步 LLM HTTP 路径。

已完成：

- `pyproject.toml` 增加：
  - `httpx>=0.27`
- 已在项目 `.venv` 安装 `httpx 0.28.1` 及依赖。
- `OpenAICompatibleClient` 增强：
  - 保留同步 `chat()` / `chat_complete()`；
  - 新增 `chat_complete_async()`，内部使用 `httpx.AsyncClient`；
  - sync/async 共用 payload 构造和 response 解析，减少分叉维护。
- `MainAgent` 增强：
  - 新增 `handle_request_async()`；
  - async 路径优先使用模型的 `chat_complete_async()`；
  - async tool loop 使用 `CapabilityExecutor.execute_async()`；
  - sync 路径保持兼容。
- `RuntimeApp.finish_user_request_async()` 新增；
- background interaction 现在调用 async main path：
  - `start_user_request_background()` -> `_finish_user_request_task()` -> `finish_user_request_async()`。
- `docs/main_tool_loop.md` 增补 async model path 说明。
- `tests/integration/test_main_tool_loop.py` 增补 async fake model 测试，确保 background main 使用 async tool loop 而不是 sync fallback。

验证：

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

结果：

```text
55 passed in 1.09s
```

当前边界仍然清晰：异步 HTTP 只是 `OpenAICompatibleClient` 的 backend 实现，main/tool/capability/runtime 结构不依赖 httpx 细节。

## 2026-05-28 单默认对话与按时间清上下文记录

用户明确：既然长期内容已经上相量数据库，不需要打开就创建很多对话；默认应继续一个对话。所谓“回档”本质是按时间清上下文，不是删除历史。

已完成：

- `SessionStore` 新增：
  - `get_or_create_default_session(title, now_ms)`：默认继续已有 active session；
  - `clear_context_before_ms(session_id, cutoff_ms)`：把某时间点及之前的消息标记为 compacted，不再进入普通 prompt context；
  - `rollback_context_to_ms(session_id, cutoff_ms)`：把某时间点之后的消息标记为 compacted，实现“回档式”上下文清理；
  - `context_stats(session_id)`：查看 total/active/compacted message 和 active chars。
- `RuntimeApp` 新增：
  - `default_session()`；
  - `clear_context_before_ms()`；
  - `rollback_context_to_ms()`；
  - 对应 runtime events。
- CLI 默认从 `app.default_session("default")` 继续，不再每次创建新 session。
- CLI 新增：
  - `--session-title`；
  - `--new-session`；
  - `/context`；
  - `/clear-before MS`；
  - `/rollback-to MS`。
- 新增 `docs/session_lifecycle.md`。
- 新增 `tests/core/test_session_context_lifecycle.py`。

语义边界：

- 回档/清上下文只影响 prompt context；
- SQLite 原始历史不删除，仍可审计；
- 长期召回依赖 vector memory / summaries；
- 默认交互只有一个持续 session，除非显式 `--new-session`。

验证：

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

结果：

```text
57 passed in 1.10s
```

## 2026-05-28 TaskSummaryWorker 与 CLI 对话骨架记录

继续补语音之外的核心内容，优先保证 CLI 对话路径和任务进度摘要。

已完成：

- 新增 `src/advanced_agent/task_summary_worker.py`：
  - `TaskSummaryWorker.summarize_task()`；
  - `TaskSummaryWorker.summarize_active()`；
  - 第一版使用现有 `TailSummarizer`，后续可替换为小模型摘要 worker。
- `TaskStore` 新增 `list_tasks(statuses=None, limit=50)`。
- `AutomationEngine` 的 `CHECK_TASKS` hook 接入 `TaskSummaryWorker`：
  - hook 触发后汇总 active/recent tasks；
  - 写入 `task_summaries` 和 `task_state.latest_summary`。
- `RuntimeApp` 接入 `task_summary_worker`。
- CLI 对话改为 async main 路径：
  - 普通文本使用 `start_user_request_background()`；
  - 先打印 interactive provisional；
  - 再等待 main async 完成并打印 authoritative render。
- CLI 新增任务查看命令：
  - `/tasks`
  - `/task TASK_ID`
- 新增 `tests/integration/test_task_summary_worker.py`。

验证：

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

结果：

```text
59 passed in 0.96s
```

当前 CLI 已经是可对话骨架：默认继续单会话，普通输入走 interactive -> async main -> render；同时支持 memory/context/task 基本查看。语音输入可以以后作为 input adapter 接入，不需要改核心 agent 分工。

## 2026-05-28 CLI 用户态输出与多 agent 弱化记录

用户实测指出：CLI 默认输出仍暴露 `interactive/provisional`、`interactive/authoritative` 等多 agent 状态；普通问候也不需要重复回复。设计目标应是“一个更拟人的统一 AI”，背后可以有多 agent/tool，但用户侧弱化为一个 AI 在思考、调用工具、继续处理。

已调整：

- `PromptBuilder.interactive_quick()`：
  - 改成“用户交互声音”；
  - 明确不要暴露多个 agent；
  - 禁止说“主 agent”。
- `PromptBuilder.interactive_render()`：
  - 要求把内部结论复述成统一 AI 口吻；
  - 禁止提 main/interactive agent 分工；
  - 不主动展示 request_id/task_id 等调试编号。
- `InteractiveAgent` fallback 文案改为更自然：
  - “收到，我先看一下。”
  - 模型失败时不再说“转交主 agent”。
- `InteractiveAgent._sanitize_internal_terms()`：
  - fallback 渲染时弱化/替换 main agent、interactive、audit、supervisor 等内部词。
- `MainAgent` fallback 文案改为用户态，不再说 main/audit/supervisor 分工。
- CLI 默认输出改为用户态：
  - 不显示 `writer/authority`；
  - 不显示 `request=...`；
  - 新增 `--debug-stream` 才显示 stream metadata 和 request id。
- CLI 增加冗余回复抑制：
  - 两次问候类回复会只显示一次；
  - 避免普通“你好”出现 provisional 和 authoritative 两条相似回复。
- 新增 `tests/core/test_cli_user_facing.py`。

验证：

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

结果：

```text
61 passed in 1.09s
```

当前原则：内部仍然保留 agent/authority/task/request 的完整记录；CLI 默认是用户态展示，debug 信息需要显式 `--debug-stream`。

## 2026-05-28 上下文可见性与 context fork 记录

用户实测指出：系统仍会说“没有保留上一段上下文/无法访问完整历史”，说明上下文构建还不完整；同时用户希望后续支持类似 fork 的上下文资源分配，以便子 agent 遵从更好、目标对齐、并尽量提高缓存命中。

已修正上下文：

- `SessionStore.session_context_lines()` 新增：
  - 不只读取 `messages` 里的 user 输入；
  - 同时读取 `interaction_streams` 中用户可见的 authoritative assistant 输出；
  - 组合为 user/assistant 对话线。
- `ContextBuilder.build_for_main()` 改用 `session_context_lines()`。
- `PromptBuilder.main_decision()` 增加约束：
  - Recent context 是当前可见记录；
  - 只要其中有内容，就不要声称完全没有上下文或记录；
  - 记录不足时要说“基于当前可见记录...”并给下一步检查方式。
- `PromptBuilder.interactive_quick()` 增加约束：
  - 用户问记录/上下文/之前做什么时，只说“我查一下记录/我看一下上下文”；
  - 不说职责有限、不说要交给主 agent。

新增 context fork 骨架：

- `src/advanced_agent/context_fork.py`：
  - `ContextForkSpec`；
  - `ContextFork`；
  - `ContextForkBuilder`。
- `RuntimeApp` 接入 `context_fork_builder`。
- `docs/context_forking.md` 记录设计：
  - parent session/request/goal；
  - recent user-visible context；
  - retrieved vector memories；
  - role/focus/constraints；
  - stable cache key；
  - 给 task/sub-agent 一个边界清楚、可缓存、可审计的上下文包。
- 新增测试：
  - `tests/core/test_context_includes_stream.py`；
  - `tests/core/test_context_fork.py`。

验证：

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

结果：

```text
64 passed in 1.12s
```

当前原则：main 的上下文必须包含用户输入和用户可见回复；长期靠 vector memory；复杂任务通过 context fork 复制必要上下文资源给子任务，而不是让主循环无限增长。

## 2026-05-28 CLI 输入卡住/输出混行修复记录

用户反馈交互界面有 bug：信息会卡住或挤在一起，输入框内容删不掉。判断这是普通 `input()` 在复杂终端交互/异步输出场景下不够稳，应该换稳定终端交互轮子。

已完成：

- `pyproject.toml` 增加稳定依赖：
  - `prompt_toolkit>=3.0`
- 已在 `.venv` 安装：
  - `prompt_toolkit 3.0.52`
  - `wcwidth 0.7.0`
- `src/advanced_agent/cli.py` 改为：
  - TTY 环境优先使用 `PromptSession.prompt_async()`；
  - 使用 `patch_stdout()` 避免后台输出打乱当前输入行；
  - 非 TTY/管道环境自动 fallback 到 `input()`，保留脚本 smoke test 能力；
  - 输出统一走 `_safe_print()`。
- 修复改造时的 CLI 命令分支缩进问题，并全量回归。

验证：

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

结果：

```text
64 passed in 1.10s
```

额外 smoke test：

```bash
printf '/help\n/exit\n' | PYTHONPATH=src .venv/bin/python -m advanced_agent.cli --config /tmp/no-config.json --db /tmp/advanced-agent-cli-pt.sqlite --workdir .
```

通过。后续真实手动 CLI 应该支持正常删除输入、方向键/行编辑，并减少输出与输入行混在一起的问题。

## 2026-05-28 任务追踪/项目位置能力与 interactive 沉默记录

用户实测：interactive 仍会人格分裂/乱说能力边界，例如“看不到文件系统”“部署在高级 AI 服务里”；任务启动后没有 task_id，后续无法查状态；任务有输出但没有结果转发；同时用户要求 interactive 应有保持沉默能力，必要时等待结果，结果回来后也可不说。

本轮修正：

### interactive 幻觉收敛

- `InteractiveAgent._deterministic_quick_reply()` 新增常见查询的规则快速回复：
  - 记录/上下文/之前/刚才 -> “我查一下记录。”
  - 项目/目录/路径/文件系统 -> “我查一下运行目录。”
  - 任务状态/任务进度/task/tail/status/hook -> “我查一下任务状态。”
- 这些场景不再让小模型自由发挥，避免它说“我看不到文件系统/职责有限/交给主 agent”。

### core capability 补全

- 新增 `project_info` capability：返回当前运行 cwd、推断 project_root、项目标记文件。
- 新增 `task_list` capability：没有 task_id 时列出最近任务。
- `BackendRegistry`、`CapabilityExecutor`、OpenAI tool schemas、MainAgent tool loop 均已接入。
- main prompt 增加策略：
  - 问项目位置优先 `project_info`，不要启动后台任务；
  - 问任务状态但没有 task_id，优先 `task_list`，再查 `task_state/task_tail`。

### task_id 展示策略调整

- interactive render prompt 改为：
  - 不主动展示 request_id；
  - 若用户后续需要追踪后台任务，可以展示 task_id；
  - 否则不要展示 task_id。

### interactive 沉默能力

- prompt 增加 `<silent>` 协议：
  - quick 阶段如果立即回复只制造噪音，可以输出 `<silent>`；
  - render 阶段如果结果不需要用户可见，也可以输出 `<silent>`。
- `InteractiveAgent._normalize_silence()` 将 `<silent>` / `[silent]` / `silent` / `沉默` / `不回复` 转为空字符串。
- CLI 默认不打印空 delta，因此 interactive 可以等待、不说，或者结果回来也不说。

### 测试

新增/更新：

- `tests/core/test_core_capabilities.py`
- `tests/core/test_interactive_silence.py`

验证：

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

结果：

```text
69 passed in 1.25s
```

备注：当前 `runtime/advanced_agent.sqlite` 中只查到一个旧的 queued 任务：`task_447b6c...`，没有看到用户刚才 CLI 里提到的两个新任务，可能是 CLI 使用了其他 db/session，或模型口头说“启动任务”但实际走的是未启动/未落库路径。新增 `task_list` 和 `project_info` 后，这类查询不应再依赖凭空 task_id。

## 2026-05-28 task_id 内部化与嘴替风格记录

用户进一步明确：task_id 模型/运行时内部知道且能查即可，用户没必要看；小模型应作为大模型管理下的嘴替和发言方式，用户不应感知大小模型差异，否则小模型没有意义。

已调整：

- `PromptBuilder.interactive_quick()`：
  - 明确背后的深度思考、大小模型、工具调用、任务执行都不要暴露成多个 agent/模型；
  - 小模型风格由深度思考层管理；
  - 认真、直接、有一点个性，但不编造事实、不乱说能力边界。
- `PromptBuilder.interactive_render()`：
  - interactive 是深度思考结果的嘴替/表达层；
  - 用户应感知为同一个 AI；
  - 不提 main/interactive agent、大小模型或内部 agent 分工；
  - 不展示 task_id，必要时说“刚才那个后台任务/最近的检查任务”；
  - request_id 继续隐藏。
- `InteractiveAgent._sanitize_internal_terms()`：
  - 自动把 `task_<hex>` 替换为“刚才那个后台任务”；
  - 自动把 `req_<hex>` 替换为“这次请求”。
- 新增测试覆盖内部 id 隐藏。

验证：

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

结果：

```text
70 passed in 1.28s
```

当前原则：内部 task_id/request_id 保留并可查；用户态默认不需要看编号。用户问任务状态时，main 应通过 `task_list` 找最近任务并查状态，而不是要求用户记 task_id。

## 2026-05-28 小模型优先与规则回退修正记录

用户打断指出：不要把 interactive 全部改成硬编码“我查一下”式应付，还是应该让小模型作为嘴替回复；问题应通过更好的提示词、上下文和鲁棒回退解决。

已调整：

- `InteractiveAgent._quick_reply()`：
  - 取消优先硬编码 deterministic quick reply；
  - 有小模型时优先让小模型回复；
  - quick 模型失败时返回空字符串，让 CLI 保持沉默，等待 main 结果，不再把 HTTP 403 等原始错误显示给用户。
- `PromptBuilder.interactive_quick()`：
  - 注入 Runtime capabilities 摘要；
  - 要求小模型回答工具/能力问题时只根据 Advanced Agent runtime capabilities 概括；
  - 禁止引用 ChatGPT/宿主调试环境工具，避免说“只有 image_gen”。
- `SessionStore.get_or_create_default_session()`：
  - 若没有同名 default session，会回退复用最近 active session，并把 title 更新为 default；
  - 修复旧 CLI 创建大量 `cli` session 后，新版 default session 看不到旧对话的问题。
- `MainAgent` LLMError 回退：
  - 不再把 `LLM HTTP 403` 等原始错误暴露给用户；
  - 改为本地规则回退：
    - 工具/能力问题：列 runtime capabilities；
    - 记录/上下文问题：读取当前 session 最近 user/assistant context；
    - 项目/目录问题：调用 `project_info`；
    - 任务/进度问题：调用 `task_list`；
    - 其他问题：给出简短本地处理回复。
- 新增测试：
  - default session 复用最近 active session；
  - main LLM 失败时不泄露 HTTP error；
  - main 规则回退能回答工具和上下文问题。

验证：

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

结果：

```text
73 passed in 1.33s
```

现状：小模型仍是优先嘴替；规则回退只在模型失败时兜底，而且尽量给真实本地信息，不显示原始错误。

## 2026-05-28 Main preflight runtime facts 记录

用户实测仍然难绷：问“工作路径”时模型只说“我先看一下”但不给结果；问“刚才任务怎么样”时模型把旧 queued 任务当结果；说明仅靠模型自发 tool-call 不稳定。问题不是底层 SQLite/能力完全坏了，而是 main 在明显查询上没有先取事实再交给模型表达。

已增加 main preflight facts：

- `MainAgent._preflight_facts(session_id, text)`：
  - 项目/目录/路径/工作路径 -> 先执行 `project_info`；
  - 工具/能力 -> 注入 runtime capabilities；
  - 刚刚/之前/记录/上下文 -> 注入最近 user/assistant context；
  - 任务/进度/输出/hook -> 注入 `task_list` 最近任务。
- `MainAgent._append_preflight_facts(...)`：
  - 把事实以 system message 注入给 main model；
  - 明确：Use these facts directly; do not claim you cannot access them.
- 这样仍然保留模型作为表达/判断层，但 obvious runtime facts 不再完全依赖模型自发 tool-call。

新增测试：

- `tests/core/test_main_preflight_facts.py`：
  - 工作路径问题会注入 `project_info`；
  - 上下文问题会注入 `recent_context`。

验证：

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

结果：

```text
75 passed in 1.29s
```

当前判断：这是架构中“模型自发工具调用不可靠”的问题。解决原则是 obvious facts 由 runtime 先取，模型负责表达和进一步决策；复杂任务再走 tool-call/context fork。

## 2026-05-28 toolcall 路径更正记录

用户指出：不要为了测试绕开 toolcall；Codex 这类系统就是靠工具调用闭环，真实使用中不能靠预计算事实/硬塞答案。这是测试阶段暴露的问题，但架构应继续走 official toolcall。

已更正：

- 撤掉 main 的 preflight facts 注入路径，不再在模型前绕开 toolcall 塞 `project_info/task_list` 结果。
- 改为 toolcall 路由：`MainAgent._tool_choice_for_intent(text)`。
  - 项目/目录/路径/工作路径 -> 强制首轮 `tool_choice=project_info`；
  - 任务/进度/输出/hook -> 强制首轮 `tool_choice=task_list`；
  - 工具/能力、上下文等仍 `auto`，让模型决定是否调用工具。
- tool 执行仍走：
  - official tool call -> `OpenAIToolAdapter` -> `CapabilityExecutor` -> tool result -> main model final answer。
- 删除了为 preflight facts 写的测试，改成测试 tool_choice routing：
  - `tests/core/test_main_tool_choice_routing.py`。

验证：

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

结果：

```text
75 passed in 1.37s
```

当前原则：明显需要工具的请求可以由 runtime 选择首轮 tool_choice，但仍必须通过官方 toolcall 和 CapabilityExecutor 闭环，不绕开工具协议。

## 2026-05-28 main-direct 与动态 fork 入口记录

用户同意改成更接近“直接和大模型对话”，interactive 不再作为第二个语义模型抢答；打断/新输入时应能自动动态 fork，而不是串上下文。

已完成第一步骨架：

- `SessionStore.message_for_request(session_id, request_id)` 新增。
- `MainAgent` 改为优先按 `request_id` 读取对应用户消息，不再总是读 latest user message。
  - 这对并发/动态 fork 很关键：多个后台请求同时跑时不会互相串话。
- `RuntimeApp.start_main_request_background()` 新增：
  - 记录 user message；
  - 直接启动 main async；
  - 不产生 interactive quick 语义回复；
  - final 仍可由 interactive renderer 统一表达。
- `RuntimeApp.completed_background` 新增：
  - 已完成后台请求也可被 `wait_user_request()` 获取；
  - 避免快速完成后从 `background_requests` pop 掉导致 KeyError。
- CLI 默认普通输入改为 main-direct：
  - 不再等待 quick 小模型先答；
  - 输入后立即回到 prompt；
  - main 完成后异步打印结果；
  - 用户在 main 未完成时继续输入，会形成另一个后台 main request，作为动态 fork 的第一版行为。
- 新增 `tests/integration/test_main_direct_fork.py`：
  - 验证两个并发后台请求各自按 request_id 保存 intent，不读错 latest user message。

验证：

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

结果：

```text
76 passed in 1.44s
```

当前状态：这还不是完整 interrupt/cancel/fork policy，但主路径已经从“interactive 小模型先答”切换为“main direct + 后台请求可并发 + request_id 隔离”。下一步可以在用户新输入时根据旧请求状态决定：继续并行 fork、标记旧请求 superseded、或请求 stop/cancel。

## 2026-05-28 MCP/runtime tool bridge 与 timer/wait 记录

用户决定：在局部项目提供项目级工具，让 Codex/MCP 使用我们的记录、标注和相量数据库检索；同时需要各种中断、等待、定时器接入。

本轮完成第一版项目级 runtime tool bridge：

- 新增 `docs/mcp_runtime_bridge.md`：
  - 解释 MCP 和 toolcall 的关系：MCP 是工具提供协议，toolcall 是模型调用动作格式；
  - Codex/MCP client 发现 MCP server tools，把它们呈现给模型，模型发 toolcall 后再调用 MCP tool；
  - Advanced Agent 应作为本项目局部 MCP/tool provider，不做全局 skill。
- 新增 `src/advanced_agent/runtime_tools.py`：
  - `RuntimeToolSpec`；
  - `RuntimeToolBridge`；
  - 不绑定具体 MCP Python 包，先形成稳定内部工具层，后续 MCP stdio/server wrapper 调它即可。
- 第一批 runtime tools：
  - `memory.search`
  - `memory.write`
  - `session.recent`
  - `task.list`
  - `task.state`
  - `task.tail`
  - `project.info`
  - `timer.schedule`
  - `event.wait`
- `timer.schedule` 语义：
  - 不让模型真的睡眠；
  - 写入 runtime hook，返回 `hook_id`。
- `event.wait` 语义：
  - 有界等待，最大 30s；
  - 超时返回 `{event: None, timeout: True}`；
  - 长等待应转为 hook/wake，不阻塞模型无限等待。
- 新增 `tests/core/test_runtime_tools.py`。

验证：

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

结果：

```text
79 passed in 1.40s
```

当前边界：`RuntimeToolBridge` 是项目级 MCP server 的核心工具层；真正 MCP 协议封装后续只做薄 wrapper，不把业务逻辑写进 MCP 框架里。

## 2026-05-28 context.get 与上下文维护接入记录

用户指出：上下文维护不能完全靠 agent 自己想起来调用；能否直接接入上下文维护，或者至少给 agent 一个明确工具注入上下文。

设计结论：

- Advanced Agent 自己的 main runtime：应自动注入 bounded recent context + vector memory retrieval，不能每轮都靠模型自觉调用。
- Codex/MCP 等外部 agent：如果客户端不支持我们强行注入私有上下文，就提供一个明确 `context.get` 工具，并在 MCP/tool prompt 中要求上下文相关任务先调用。

已完成：

- `RuntimeToolBridge` 新增 `context.get`：
  - 输入：`query`、`session_id`、`scope`、`recent_limit`、`memory_top_k`；
  - 输出：recent user-visible context lines + vector memory hits；
  - 附带 instruction：先使用该上下文，不足再调用更具体工具。
- `docs/mcp_runtime_bridge.md` 增补 Context maintenance mode：
  - 自动注入路径；
  - MCP/Codex on-demand tool 路径；
  - 不完全依赖“模型记得搜索记忆”。
- `tests/core/test_runtime_tools.py` 增补 `context.get` 测试。

验证：

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

结果：

```text
80 passed in 1.35s
```

## 2026-05-28 Codex vs Advanced Agent 分工与 LLM 记忆标注记录

用户澄清：先理解 Codex 自带能力和我们要补什么；当前更应该先做记忆和习惯整理。用户认为“用 LLM 打标签再进相量数据库”本身就很有用。

分工判断：

- Codex 自带/擅长：交互式 coding、文件读写、shell/test、patch、工具调用习惯、局部项目执行。
- Advanced Agent 要补：长期记忆、用户习惯/画像、跨会话上下文、记忆标注与相量索引、hook/task 生命周期、事件/等待、系统级 runtime 状态。
- 当前优先级：先把 memory/profile 做扎实，再接 MCP/Codex。

已实现 LLM memory alignment 框架：

- 新增 `src/advanced_agent/memory_alignment.py`：
  - `MemoryAligner` protocol；
  - `LLMMemoryAlignment`：调用可配置 `memory_model` 生成 JSON 标签；
  - 标签键：`semantic`、`task_intent`、`decision`、`agent_relevance`；
  - LLM 失败/非 JSON 时 fallback 到原 `MemoryAlignment` 规则标签。
- `MemoryIndexer` 改为依赖 `MemoryAligner` 协议，不再写死规则标签类型。
- `ModelRouter` 支持 `memory_model` role。
- `RuntimeApp` 接入 `LLMMemoryAlignment(router.client_for("memory_model"), fallback=MemoryAlignment())`。
- `.env.example.json` 增加 `memory_model` / `memory-cheap` 示例。
- 新增 `tests/core/test_memory_alignment.py`。

验证：

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

结果：

```text
82 passed in 1.35s
```

当前意义：长期记忆写入仍走统一 `MemoryIndexer`，LLM 只负责生成检索标签，不直接写库；这使记忆质量可以提升，同时保持可审计和可回退。

## 2026-05-28 增强交互式 Codex wrapper 记录

用户明确：还是要交互式，本质是增强交互式 Codex，而不是替代 Codex。

本轮实现第一版交互式 wrapper 骨架：

- 新增 `src/advanced_agent/codex_interactive.py`：
  - 恢复/创建 Advanced Agent 默认 session；
  - 用 PTY 启动原生 `codex`；
  - stdin/stdout 直接透传，保留 Codex 原生交互体验；
  - 设置环境变量：
    - `ADVANCED_AGENT_SESSION`
    - `ADVANCED_AGENT_DB`
    - `ADVANCED_AGENT_CODEX_LOG`
  - 将终端字节流 tee 到 `runtime/codex_interactive/*.terminal.log`；
  - Codex 退出后，把 transcript tail 作为 `codex_interactive_log` 通过 `MemoryIndexer` 入库；
  - 发布 `codex.interactive.logged` event。
- 新增 `docs/enhanced_interactive_codex.md`。
- 新增 `tests/core/test_codex_interactive_wrapper.py`。

运行方式：

```bash
PYTHONPATH=src .venv/bin/python -m advanced_agent.codex_interactive --db runtime/advanced_agent.sqlite --config .env.json --
```

注意：

- PTY 记录是终端字节流，不是结构化 Codex event；
- 长期高质量记忆仍应靠 session summary 或 MCP `memory.write/context.get`；
- 这个 wrapper 的价值是保留 Codex 原生交互，同时接上 Advanced Agent 的 session/log/memory。

验证：

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

结果：

```text
83 passed in 1.33s
```

## 2026-05-28 MCP 记忆入库与 toolcall 验证记录

方向调整为“增强交互式 Codex + Advanced Agent MCP/runtime/memory 层”：Codex 保持交互式编码主体验，Advanced Agent 作为项目级 MCP server 提供记忆、上下文、任务、hook 等工具。

本阶段已完成：

- 新增 `src/advanced_agent/memory_service.py`：统一封装记忆写入、向量检索、hydration 和 recent 列表。
- 新增 `src/advanced_agent/mcp_server.py`：基于官方 `mcp` Python 包暴露项目级 stdio MCP server。
- MCP 工具已接入：
  - `context.get`
  - `memory.write`
  - `memory.search`
  - `memory.recent`
  - `session.recent`
  - `project.info`
  - `task.list/state/tail`
  - `timer.schedule`
  - `event.wait`
- `RuntimeToolBridge` 的记忆读写改为走 `MemoryService`，`memory.search` 返回带 content snippet 的 hydrated record，不再只返回向量 hit 元数据。
- 新增 `docs/codex_mcp_memory_quickstart.md`，记录 Codex MCP 注册命令和 smoke test。
- `pyproject.toml` 加入 `mcp>=1.27`。

验证：

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

结果：

```text
87 passed
```

下一步：把增强 Codex wrapper 与 MCP 配置/启动流程合并得更顺手，并让 Codex 在关键节点主动 `memory.write` 写入用户偏好、项目决策、未完成事项。

## 2026-05-28 自有入口接管 Codex + MCP 记录

用户确认项目内可用即可，入口使用 Advanced Agent 自己的入口，不要求手动维护全局 Codex MCP 配置。

已完成：

- `advanced_agent.codex_interactive` 默认注入项目级 MCP server：通过 Codex 临时 `-c mcp_servers.advanced-agent...` 参数传入，不修改 `~/.codex/config.toml`。
- 保留 `--no-mcp` 作为 raw Codex wrapper 调试开关。
- `pyproject.toml` 增加 console scripts：
  - `advanced-agent-codex = advanced_agent.codex_interactive:main`
  - `advanced-agent-mcp = advanced_agent.mcp_server:main`
- 文档更新：`docs/enhanced_interactive_codex.md` 和 `docs/codex_mcp_memory_quickstart.md` 都改为优先使用自有 wrapper 入口。

推荐入口：

```bash
PYTHONPATH=src .venv/bin/python -m advanced_agent.codex_interactive \
  --db runtime/advanced_agent.sqlite \
  --config .env.json \
  --
```

验证：

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

结果：

```text
88 passed
```

## 2026-05-28 写入问题修复记录

用户通过自有入口进入 Codex 后，要求“看看项目在干什么然后记录一些内容”，发现记忆没有写入。排查结果：

1. `memory_items` 初始为 0，说明 Codex 没有成功调用记忆写入工具。
2. 直接通过 MCP 调 `memory_write` 时出现 `sqlite3.OperationalError: database is locked`。
3. 根因之一是 `SQLiteStore.execute()` 在 Python sqlite3 默认事务模式下判断 `conn.in_transaction` 后不提交，DML 会留下打开事务，从而锁住 runtime DB。
4. 另一个兼容性风险是 dotted MCP tool name（如 `memory.write`）对 Codex/OpenAI-style tool/function name 不够稳。

已修复：

- `SQLiteStore` 改为 `isolation_level=None` autocommit，并加入显式 `_transaction_depth`，普通 `execute/executemany` 不再留下未提交事务。
- `busy_timeout` 增加到 30000ms。
- MCP server 保留 dotted 名称，同时新增 Codex 友好的 underscore aliases：
  - `context_get`
  - `memory_write`
  - `memory_search`
  - `memory_recent`
  - `session_recent`
  - `project_info`
  - `task_list/task_state/task_tail`
  - `timer_schedule/event_wait`
- 新增 `AGENTS.md`，要求 Codex 对“之前内容/项目状态”先调用 `context_get`，对“记录/记住/写入”调用 `memory_write`。

验证：

- 通过 `memory_write` alias 写入 runtime DB 成功。
- 通过 `memory_search` alias 能召回刚写入记录。
- `runtime/advanced_agent.sqlite` 中 `memory_items` 已可持久化看到验证记录。
- 全量测试：`88 passed`。

## 2026-05-28 PTY 输入修复记录

用户反馈通过自有 Codex wrapper 输入方向键时显示 `^[[C/^[[D/^[[A/^[[B`，上下左右输入炸了。

根因：wrapper 作为 PTY proxy 时只给 Codex 分配了子 PTY，但父终端 stdin 没有切到 raw mode，方向键等控制序列会被行缓冲后作为普通文本传给 Codex。

已修复：

- `src/advanced_agent/codex_interactive.py` 在 `_run_pty()` 中进入代理循环前对父终端执行 `tty.setraw(sys.stdin.fileno())`。
- 退出时用 `termios.tcsetattr(..., TCSADRAIN, old_tty_attrs)` 恢复原终端状态。
- 新增窗口大小同步：启动时复制 winsize，`SIGWINCH` 时同步到 PTY，避免 TUI 尺寸错乱。

验证：

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

结果：

```text
88 passed
```

## 2026-05-28 第一版记忆自动注入/替换/标签/相量库完成记录

用户要求开始做“记忆的自动注入还有替换、自动生成标签、接入相量数据库”，作为第一版完成线。

已完成：

- 自动注入：
  - `ContextBuilder` 改为通过 `MemoryService` 检索 hydrated memory records。
  - `PromptBuilder.main_decision()` 注入 memory summary + bounded content，不再只注入 vector hit 摘要。
  - MCP `context_get` 返回 recent context + hydrated memories + maintenance 状态。
- 替换/压缩：
  - `AutomationEngine.ensure_session_maintenance()` 同时安排 preference maintenance 和 `COMPACT_MEMORY` hook。
  - `context_get` 会先执行 `compactor.maybe_compact()`，超预算上下文可自动压缩为 `session_summary` 记忆。
  - `SessionStore.session_context_lines()` 过滤已 compacted request 对应的 authoritative assistant stream，避免压缩后 live context 仍重复旧回复。
- 自动标签：
  - `MemoryIndexer` 仍统一走 `LLMMemoryAlignment`，失败时规则 fallback。
  - schema v2 新增 `memory_vectors.label_text`，工具返回可看到实际生成的标签文本。
- 相量数据库：
  - sqlite-vec 仍作为第一版相量库后端。
  - 每条 memory 由多个 label kind 写入多个向量：`semantic/task_intent/decision/agent_relevance`。
- 迁移：
  - schema version 升到 2。
  - v1 -> v2 自动 `ALTER TABLE memory_vectors ADD COLUMN label_text`。
- 文档：
  - 新增 `docs/memory_auto_injection.md`。

验证：

- `RuntimeApp.create('runtime/advanced_agent.sqlite')` 已把 runtime DB 迁移到 schema v2。
- 通过 `MemoryService.write()` 写入“第一版记忆自动注入验证”成功。
- recent memory 可看到四类标签文本：`semantic/decision/task_intent/agent_relevance`。
- 全量测试：

```text
91 passed
```

## 2026-05-28 `codexx` 默认入口与环境变量记录

用户要求“多自动化一些，加入系统环境变量，直接 `codexx` 启动，一个默认文件即可，可以更信任相量数据库”。

已完成：

- 新增 `src/advanced_agent/defaults.py`，统一默认值与环境变量读取：
  - `ADVANCED_AGENT_DB` -> `runtime/advanced_agent.sqlite`
  - `ADVANCED_AGENT_CONFIG` -> `.env.json`
  - `ADVANCED_AGENT_LOG_DIR` -> `runtime/codex_interactive`
  - `ADVANCED_AGENT_SCOPE` -> `project:advanced_agent`
  - `ADVANCED_AGENT_MEMORY_TRUST` -> `high`
- `advanced_agent.codex_interactive` 默认读取这些环境变量，无参数即可启动。
- `advanced_agent.mcp_server` 也默认读取同一套环境变量。
- `codex_mcp_config_args()` 注入 MCP server 时会把 `ADVANCED_AGENT_DB/CONFIG/SCOPE/MEMORY_TRUST` 传给 MCP 子进程。
- 在 `.venv/bin/` 写入项目级启动脚本：
  - `codexx`
  - `advanced-agent-mcp`
- `pyproject.toml` 也声明了 console script：
  - `codexx = advanced_agent.codex_interactive:main`
- `AGENTS.md` 和 `PromptBuilder` 已强化：相量数据库是可信的长期项目记忆；如果 `context_get/memory_search` 命中相关内容，不要轻易说没有上下文。
- 新增文档：`docs/codexx_entrypoint.md`。
- README 增加推荐入口说明。

现在推荐启动方式：

```bash
source .venv/bin/activate
codexx
```

默认唯一配置文件仍是：

```text
.env.json
```

验证：

```text
93 passed
```

## 2026-05-28 `codexx` 自动虚拟环境记录

用户要求虚拟环境也自动，不想每次 `source .venv/bin/activate`。

已完成：

- 新增项目脚本：
  - `bin/codexx`
  - `bin/advanced-agent-mcp`
- 脚本内部自动：
  - `cd` 到项目根目录；
  - 设置 `VIRTUAL_ENV=$ROOT/.venv`；
  - 把 `$ROOT/.venv/bin` 加到 `PATH`；
  - 设置 `PYTHONPATH=$ROOT/src`；
  - 设置默认 `ADVANCED_AGENT_*` 环境变量；
  - 使用 `$ROOT/.venv/bin/python -m advanced_agent...` 启动。
- 已把脚本链接到用户 PATH：
  - `~/.local/bin/codexx -> <project>/bin/codexx`
  - `~/.local/bin/advanced-agent-mcp -> <project>/bin/advanced-agent-mcp`

现在无需激活 venv，直接：

```bash
codexx
```

验证：

```bash
env -u VIRTUAL_ENV PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin" codexx --help
```

成功显示帮助；全量测试仍为：

```text
93 passed
```

## 2026-05-28 系统变更记录与移除脚本

用户要求记录所有对系统的变更，并提供移除 bash。

已记录：`docs/system_changes.md`

当前系统/用户级变更只有 `~/.local/bin` 下的用户级 symlink：

```text
~/.local/bin/codexx -> <project>/bin/codexx
~/.local/bin/advanced-agent-mcp -> <project>/bin/advanced-agent-mcp
~/.local/bin/advanced-agentd -> <project>/bin/advanced-agentd
```

没有修改 shell rc 文件，没有写 root/systemd/system 目录。

已新增移除脚本：

```bash
bash scripts/remove_system_changes.sh
```

默认只移除指向本项目的 `~/.local/bin` symlink；不会删除同名但不指向本项目的文件。

预览：

```bash
bash scripts/remove_system_changes.sh --dry-run
```

连项目内生成 launcher 一起删：

```bash
bash scripts/remove_system_changes.sh --project-local
```

验证：

- `--dry-run` 能正确识别三个 symlink。
- 全量测试：`94 passed`。

## 2026-05-29 多维相量记忆控制面与 raw tail 记录

用户确认记忆不应拆成两个语义库，而应在统一相量数据库中按不同维度/facet 控制：项目、时间、方法论、项目特点、唠嗑等都作为入库分类和检索权重处理；raw_message 只需要类似环形缓冲区的 bounded tail，防止上下文溢出，模型需要时可以自动 tail 调用。

已完成第一版实现：

- 新增 `src/advanced_agent/memory_facets.py`：
  - 定义统一 facet 集合：`semantic/project/time/methodology/project_feature/implementation/decision/preference/procedure/risk/handoff/chat/agent_relevance`；
  - 定义 query profiles：`auto/general/design/project/methodology/preference/procedure/risk/handoff/chat/recent`；
  - 支持 `normalize_facets()` 和 profile 权重推导。
- `MemoryAlignment` / `LLMMemoryAlignment` 从少量 label 升级为多维 facet 生成。
- `MemoryCandidate` 增加 `facets` / `metadata`，`MemoryIndexer` 入库时统一 facet 归一化。
- `SQLiteVecStore.search()` 增加 `query_profile` / `facet_weights`，当前 sqlite-vec 通过 overfetch + facet-weighted rerank 模拟多维控制面。
- `MemoryService.search()`、`RuntimeToolBridge.memory.search`、`context.get` 接入 query profile。
- 新增 `SessionStore.raw_tail_lines()` 和 runtime/MCP 工具：
  - `session.raw_tail`
  - `session_raw_tail`
  用作 raw dialogue 的 bounded ring-buffer-like tail；默认不把全部 raw history 注入 prompt。
- main prompt 已提示：如果需要更多原始最近消息，应调用 `session.raw_tail/session_raw_tail`，不要要求用户重述。
- 文档更新：
  - `docs/memory_design.md`
  - `docs/memory_auto_injection.md`
  - `docs/vector_memory.md`
  - `docs/memory_indexer.md`

验证：

```text
.venv/bin/python -m pytest tests/core/test_runtime_tools.py tests/integration/test_memory_indexer.py tests/integration/test_vectors_cli.py
11 passed
```

注意：当前项目目录所在文件系统对 `.pytest_cache` 写入报 read-only warning，但测试本身通过。

## 2026-05-29 系统级 `cd` 内建命令记录

用户指出 Advanced Agent 应该是系统级 AI，不应只有项目级工作目录；`cd` 应作为内建运行时命令。

已完成第一版实现：

- 新增 `src/advanced_agent/workspace.py`：
  - `WorkspaceState.cwd` 保存 runtime 工作目录；
  - 相对路径基于当前 runtime cwd 解析；
  - `info()` 返回 cwd、推断 project root、markers。
- `RuntimeApp` 接入 `WorkspaceState`，task 默认 workdir 改为当前 runtime cwd。
- 新增 capability/tool：
  - internal: `workdir_chdir`
  - runtime/MCP: `workdir.chdir`
  - Codex-friendly alias: `workdir_chdir`
- `project_info` 现在读取 runtime cwd，而不是 Python process cwd。
- CLI 增加：
  - `/pwd`
  - `/cd PATH`
- main agent rule/tool path 能处理 `cd ...` / `/cd ...`，模型工具列表也包含 `workdir_chdir`。
- 新增文档：`docs/workdir_control.md`。

验证：

```text
.venv/bin/python -m pytest tests/core/test_runtime_tools.py tests/core/test_mcp_server.py tests/core/test_prompt_builder.py
13 passed
```

注意：测试仍有 `.pytest_cache` read-only warning，和项目目录挂载状态有关，不影响功能测试结果。

## 2026-05-29 Codex wrapper 组件分布记录

用户询问当前 wrapper 还有什么能升级、组件分散在哪。

已新增文档：

- `docs/codex_wrapper_components.md`

记录内容：

- `codexx` 当前入口链路：
  - `~/.local/bin/codexx`
  - `bin/codexx`
  - `.venv/bin/python -m advanced_agent.codex_interactive`
  - `src/advanced_agent/codex_interactive.py`
  - 原生 `codex`
- wrapper 相关组件分布：
  - launcher / entrypoint
  - Python PTY wrapper
  - defaults/config
  - MCP/runtime tool layer
  - runtime log/SQLite 输出
  - docs/tests/system-change cleanup
- 下一步升级建议：
  1. 抽 `CodexWrapperConfig`，减少 `bin/codexx`、`defaults.py`、`codex_interactive.py` 的默认值分散；
  2. 增加 `codexx --doctor` 或 `advanced-agent doctor codexx`；
  3. raw PTY log 保留作证据，但语义记忆改用结构化事件和显式 `memory.write`；
  4. 区分 wrapper 自身 scope 与调用者 cwd/project scope；
  5. 改进 interrupt 后的 resumable handoff。

推荐下一步先做“wrapper doctor + 配置集中化”，因为这能直接提升日常使用稳定性，同时不改变 core architecture。

## 2026-05-29 MCP 安全工具自动放行与并发安全记录

用户要求：只把 Advanced Agent 自己 MCP 里没危险的内建 tool 自动放行；然后按顺序完成、测试，并把 MCP 做成进程/线程安全，因为可能并发多个终端。

已完成：

### 1. MCP tool 自动放行语义

- 在 `src/advanced_agent/mcp_server.py` 中为所有当前暴露的内建 MCP tool 加了安全 annotations：
  - `destructiveHint=False`
  - `openWorldHint=False`
  - 只读类：`readOnlyHint=True`
  - runtime DB/state 写类：`readOnlyHint=False` 但仍 `destructiveHint=False`
- 自动放行范围仅限本 MCP server 暴露的非破坏性工具：
  - read：`context.get` / `memory.search` / `memory.recent` / `session.recent` / `session.raw_tail` / `project.info` / `task.list` / `task.state` / `task.tail` / `event.wait`
  - safe DB write：`memory.write`
  - safe runtime state write：`workdir.chdir` / `timer.schedule`
- MCP server instructions 明确说明：这些是 project-local runtime tools，可由客户端自动批准；shell/file/system action 不在这里暴露。

### 2. Runtime tool policy 元数据

- `src/advanced_agent/runtime_tools.py` 新增：
  - `RuntimeToolRisk`
  - `SAFE_MCP_AUTO_APPROVE_TOOLS`
  - `runtime_tool_risk()`
  - `runtime_tool_auto_approve()`
- `RuntimeToolSpec` 增加：
  - `risk`
  - `auto_approve`
- 这为后续 doctor/UI/client policy 提供统一来源，避免只靠 prompt。

### 3. MCP 并发/多终端安全

- `src/advanced_agent/stores/sqlite_store.py`：
  - SQLite connection 改为 `check_same_thread=False`；
  - 增加 process-local `threading.RLock`；
  - `execute` / `executemany` / `query_*` / `transaction` / `close` / `optimize` 都走锁；
  - transaction 改为 `BEGIN IMMEDIATE`，减少写事务竞争中的不确定性；
  - 保留 WAL、`busy_timeout=30000`，用于多个 MCP 进程共享同一 DB。
- `src/advanced_agent/vectors.py`：
  - sqlite-vec load/init/search/direct connection access 包进 DB lock；
  - memory vector rowid 不再用 `SELECT MAX(...) + 1`，改成随机正 63-bit rowid，避免多个 MCP server 进程并发写入同一个 `vec_memory` 表时分配同一个 rowid。
- `src/advanced_agent/workspace.py`：
  - `WorkspaceState` 加 RLock，避免同一 MCP server 进程内多个线程同时读写 runtime cwd。

边界说明：

- 现在支持“多个终端各自启动一个 MCP server 进程，共享同一个 SQLite/WAL DB”的基本并发写读；
- 也支持“同一个 MCP server 进程里多个线程同时调用工具”的连接级串行化；
- `workdir.chdir` 的 cwd 状态目前仍是每个 MCP server 进程各自一份 runtime state，不是跨终端全局 cwd，这符合 shell-like per-process cwd 语义。

测试：

```text
.venv/bin/python -m pytest tests/core/test_runtime_tools.py tests/core/test_mcp_server.py
12 passed

.venv/bin/python -m pytest \
  tests/core/test_capability_executor.py \
  tests/core/test_config.py \
  tests/core/test_codex_interactive_wrapper.py \
  tests/core/test_defaults_entrypoint.py \
  tests/core/test_migrations.py \
  tests/integration/test_memory_indexer.py \
  tests/integration/test_vectors_cli.py
19 passed
```

仍有已知 warning：项目所在挂载对 `.pytest_cache` 写入报 read-only warning，不影响测试结果。

## 2026-05-29 `codexx` 启动千字上下文 bootstrap 记录

用户确认方向：`codexx` 启动时默认喂约千字历史；之后让模型能自主通过环形缓冲区 toolcall 继续读取；长期记忆走相量数据库。

已完成第一版：

- `src/advanced_agent/codex_interactive.py`
  - 新增 `build_bootstrap_prompt(app, session_id, max_chars=1200)`：
    - 从 `SessionStore.raw_tail_lines()` 拉取 bounded raw tail；
    - 组装成 Codex 初始 prompt；
    - 明确提示：
      - bootstrap 只是最近历史摘录，不是完整上下文；
      - 更深历史用 `context_get`；
      - 更多原始近期消息用 `session_raw_tail`；
      - 长期记忆用 `memory_search`；
      - 决策/偏好/进度/handoff 用 `memory_write`。
  - 新增 `should_inject_bootstrap(codex_args)`：
    - 仅在普通 `codexx` 无显式 prompt / 无 Codex subcommand 时注入；
    - 如果用户传 `codexx "..."`、`codexx exec ...`、`codexx resume ...`，不改 argv 语义。
  - `run_interactive_codex(..., bootstrap_chars=1200)` 默认启用；
  - CLI 新增 `--bootstrap-chars`，也可用环境变量 `ADVANCED_AGENT_BOOTSTRAP_CHARS`；
  - `--bootstrap-chars 0` 可关闭。
- `docs/codexx_entrypoint.md`
  - 记录 startup bootstrap context 行为和关闭方式。

验证：

```text
env -u VIRTUAL_ENV PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin" codexx --help
```

显示新增 `--bootstrap-chars` 参数。

测试：

```text
.venv/bin/python -m pytest tests/core/test_codex_interactive_wrapper.py tests/core/test_mcp_server.py tests/core/test_runtime_tools.py
20 passed

.venv/bin/python -m pytest tests/core/test_capability_executor.py tests/core/test_defaults_entrypoint.py tests/core/test_migrations.py tests/integration/test_memory_indexer.py tests/integration/test_vectors_cli.py
12 passed
```

仍有已知 `.pytest_cache` read-only warning，不影响测试结果。

下一步讨论：DB v2 如何把当前 sqlite-vec 多 facet 原型落成更完整的相量数据库，包括 facet 独立表、FTS/BM25、hybrid rerank、why-hit 解释字段、长期记忆写入/压缩策略。

## 2026-05-29 相量数据库 v2 第一版落地记录

用户明确方向：

- 项目本身也是长期记忆的一个维度，不需要额外把“项目感知”做成多终端共享状态；
- 多终端感知没必要，多个终端共享同一个相量数据库即可；
- wrapper 自动关闭时，记录环形缓冲区最后内容即可；
- 先把 DB v2 做起来；
- “doctor” 不是 Docker；doctor 指诊断命令，Docker/服务化以后再说。

已完成 DB v2 第一版：

### schema v3

- `CURRENT_SCHEMA_VERSION = 3`
- 新增：
  - `memory_facets(memory_id, facet_name, facet_text, weight, created_at_ms)`
  - `memory_fts` FTS5 虚表：`memory_id/scope/type/summary/content/facets`
- 新库 bootstrap schema 已包含 v3 表；
- 旧库迁移：
  - v1 -> v2 继续补 `memory_vectors.label_text`
  - v2 -> v3 创建 `memory_facets` / `memory_fts`
  - 从现有 `memory_vectors.label_kind/label_text` 回填 `memory_facets`
  - 从 `memory_items + memory_facets` 回填 `memory_fts`

### 写入路径

- `SQLiteVecStore.add_memory()` 现在一次写入：
  - `memory_items`
  - `memory_vectors`
  - `memory_facets`
  - `memory_fts`
- 保留 `memory_vectors.label_kind/label_text`，兼容旧检索和旧测试。

### hybrid search

- `SQLiteVecStore.hybrid_search()`：
  - vector candidates：sqlite-vec 多 facet search；
  - keyword candidates：FTS5/BM25；
  - merge by `memory_id`；
  - hydrate metadata/facets；
  - rerank by：
    - vector score
    - keyword score
    - facet score
    - recency
    - importance
    - confidence
  - 返回 `why_hit`，包括：
    - `vector_score`
    - `keyword_score`
    - `facet_score`
    - `recency_score`
    - `importance`
    - `confidence`
    - `matched_facets`
    - `profile`
- `MemoryService.search()` 已切到 hybrid search，并在 `MemoryRecord.to_dict()` 暴露 `score/why_hit`。
- sqlite-vec KNN 查询增加上限，避免 overfetch 过大触发 `k value in knn query too large`。

### wrapper 关闭 raw-tail handoff

- `_ingest_codex_log_tail()` 除了原有 `codex_interactive_log`，现在还调用 `_ingest_session_raw_tail_handoff()`：
  - 读取当前 session 的 bounded raw tail；
  - 写入 `type=handoff` 长期记忆；
  - facets 包括 `handoff/time/chat`；
  - 用于“最后一个关闭的 wrapper 自动记录缓冲区最后内容”。

### 测试

```text
.venv/bin/python -m pytest \
  tests/core/test_migrations.py \
  tests/integration/test_memory_indexer.py \
  tests/integration/test_vectors_cli.py \
  tests/core/test_runtime_tools.py \
  tests/core/test_mcp_server.py \
  tests/core/test_codex_interactive_wrapper.py
26 passed

.venv/bin/python -m pytest \
  tests/core/test_capability_executor.py \
  tests/core/test_defaults_entrypoint.py \
  tests/core/test_config.py
9 passed
```

仍有 `.pytest_cache` read-only warning，不影响结果。

## 2026-05-29 Workstream/workspace/keyword facets

用户指出：`project` 不一定对应文件夹，随便聊天也可能是一个项目/主题；聊天也要有分类；内容也要分类；还需要自由、不定长关键词匹配。

已完成：

- `src/advanced_agent/memory_facets.py`
  - 新增 facet：
    - `workstream`：长期话题/任务线/项目维度，不要求有文件夹；
    - `workspace`：文件系统/repo/path/module/cwd 维度；
    - `content_type`：内容类别；
    - `topic_keywords`：主题关键词；
    - `free_keywords`：自由关键词，不定长但有上限；
  - 保留 legacy `project` facet 兼容旧记忆；
  - `QUERY_PROFILE_WEIGHTS` 改为优先使用 `workstream/topic_keywords/free_keywords/workspace`；
  - `KIND_DEFAULT_FACETS` 对 decision/preference/project_state/session_summary/procedure/warning/handoff/chat/codex_interactive_log 全部加入更合适的新 facet；
  - 新增 `extract_keywords()`：
    - 从文本提取英文 token、路径/模块样式 token、带数字/符号的技术词，以及中文连续词；
    - 去重、简单打分、保留 bounded variable-length keyword list；
  - 新增 `_infer_content_type()` 作为 fallback 内容分类。
- `src/advanced_agent/memory_alignment.py`
  - LLM facet-labeler allowed facets 增加 `workstream/workspace/content_type/topic_keywords/free_keywords`。
- `src/advanced_agent/vectors.py`
  - fallback `MemoryAlignment` 生成上述新 facets；
  - 旧 `project` 改成 legacy alias，而不是唯一项目维度。

测试：

```text
.venv/bin/python -m pytest tests/core/test_runtime_tools.py tests/core/test_memory_alignment.py tests/integration/test_memory_indexer.py tests/integration/test_compaction_context.py tests/core/test_mcp_server.py
22 passed

.venv/bin/python -m pytest tests/core/test_migrations.py tests/core/test_codex_interactive_wrapper.py tests/integration/test_vectors_cli.py
11 passed
```

仍有 `.pytest_cache` read-only warning，不影响结果。

当前语义：

- `workstream` 是“聊的是什么事/长期话题”，可以没有文件夹；
- `workspace` 才是“文件系统在哪里”；
- `project` 只是 legacy alias；
- `content_type` 和 `topic_keywords/free_keywords` 负责按内容分类和自由关键词检索。

## 2026-05-29 Remove legacy project facet and deployment notes

用户要求：旧的直接迁移，不要为了兼容留下屎山；并询问如何在别的电脑部署。

已完成：

- `src/advanced_agent/memory_facets.py`
  - 从 `DEFAULT_MEMORY_FACETS` 移除 `project`；
  - profile 权重不再包含 `project`；
  - fallback 默认 facet 从 `project` 改为 `workstream`；
  - `project_state` 等类型不再写 legacy `project` facet；
  - metadata 中的 `project` 只作为输入信号并入 `workstream`，不再输出独立 facet。
- `src/advanced_agent/memory_alignment.py`
  - allowed facets 移除 `project`。
- `src/advanced_agent/vectors.py`
  - fallback `MemoryAlignment` 不再生成 legacy `project`。
- `src/advanced_agent/migrations.py`
  - schema 升到 `CURRENT_SCHEMA_VERSION = 4`；
  - 新增 v4 migration：
    - `memory_facets.facet_name='project'` 迁移/合并到 `workstream`；
    - `memory_vectors.label_kind='project'` 迁移/合并到 `workstream`；
    - 删除旧 `project` facet；
    - 重建 `memory_fts`，避免 FTS 里残留 legacy project 文本标签。

测试：

```text
.venv/bin/python -m pytest tests/core/test_migrations.py tests/core/test_runtime_tools.py tests/core/test_memory_alignment.py tests/integration/test_memory_indexer.py tests/core/test_mcp_server.py tests/core/test_codex_interactive_wrapper.py
29 passed

env -u VIRTUAL_ENV PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin" codexx --help
```

`codexx --help` 正常，显示 `--bootstrap-chars`。

部署到另一台电脑的当前建议：

1. 拷贝/clone 项目目录；
2. 安装 Python 3.12+、Codex CLI、系统 sqlite；
3. 在项目根目录创建 `.venv` 并安装本项目依赖；
4. 准备 `.env.json`；
5. 建立 `~/.local/bin/codexx -> <project>/bin/codexx` symlink，或直接运行 `bin/codexx`；
6. 如果要带历史，拷贝 `runtime/advanced_agent.sqlite*`；如果要干净新机，就不拷贝 runtime，首次启动会自动建库并迁移到 v4；
7. 验证：`codexx --help`、`codexx`。

注意：当前 `bin/codexx` 里 ROOT 是本机绝对路径；跨机器部署需要改成新机器项目路径，或者后续把 launcher 改成根据 symlink 自定位项目根目录。

## 2026-05-29 Installer and portable launchers

用户要求：改成安装 bash 之类，然后 commit/tag 成正式版本。

已完成代码侧：

- `bin/codexx`
- `bin/advanced-agent-mcp`
- `bin/advanced-agentd`

三者都从硬编码本机绝对路径改为根据脚本路径自定位项目根目录；经 `~/.local/bin` wrapper 或直接 `bash bin/codexx` 调用都可以找到项目根。

新增：

- `scripts/install_user.sh`

功能：

- 创建 `.venv`；
- 默认执行 `pip install -e <project>`；
- 在 `~/.local/bin` 写入用户级 launcher：
  - `codexx`
  - `advanced-agent-mcp`
  - `advanced-agentd`
- 支持：
  - `--no-deps`
  - `--force`
  - `--dry-run`

实现细节：installer 写入的是小 bash wrapper，内容类似 `exec bash <project>/bin/codexx "$@"`，因此即使项目目录所在文件系统不允许 chmod/executable bit，也可以运行。

`.gitignore` 追加忽略：

- `runtime/codex_interactive/*.terminal.log`

验证：

```text
bash scripts/install_user.sh --dry-run --no-deps
bash bin/codexx --help
.venv/bin/python -m pytest tests/core/test_migrations.py tests/core/test_runtime_tools.py tests/core/test_mcp_server.py tests/core/test_codex_interactive_wrapper.py tests/core/test_memory_alignment.py tests/integration/test_memory_indexer.py tests/integration/test_vectors_cli.py
30 passed
```

Git 状态：

- 该目录此前不是 git repo；
- 已执行 `git init` 初始化本地仓库；
- 下一步需要 `git add/commit/tag`。

后续可提升：

1. `memory_facets.weight` 目前默认 `1.0`，后续可按 memory type/profile 写入不同权重；
2. FTS query 目前是保守 OR token，后续可做更稳定的中文分词/英文 token normalize；
3. `why_hit` 已有，但还可以向 `context_get` 增加更紧凑的解释格式；
4. wrapper 关闭时的 handoff 目前记录 raw tail，不做 LLM summary；如果以后接入 summarizer，可把 raw 证据和语义 summary 分开。

## 2026-05-29 Memory facet language normalized to English

用户指出：memory/vector DB 相关内容都用英文即可，这样相量数据库更成熟，模型也更适配。

已完成：

- `src/advanced_agent/memory_alignment.py`
  - LLM facet-labeler system prompt 改为英文；
  - 明确输出 English-style mature multi-dimensional vector-memory facets；
  - allowed facets 保持英文：`semantic/project/time/methodology/project_feature/implementation/decision/preference/procedure/risk/handoff/chat/agent_relevance`。
- `src/advanced_agent/memory_facets.py`
  - `infer_query_profile()` 的启发式关键词改为英文优先；
  - 去掉中文关键词依赖，使 profile inference 更贴近模型英文 facet/query 习惯。
- `tests/core/test_memory_alignment.py`
  - 测试样例改成英文 facet/value，不再使用旧的中文/非标准 `task_intent` 标签。

验证：

```text
.venv/bin/python -m pytest tests/core/test_memory_alignment.py tests/core/test_runtime_tools.py tests/integration/test_memory_indexer.py tests/integration/test_compaction_context.py
18 passed

.venv/bin/python -m pytest tests/core/test_migrations.py tests/core/test_mcp_server.py tests/core/test_codex_interactive_wrapper.py tests/integration/test_vectors_cli.py
14 passed
```

仍有 `.pytest_cache` read-only warning，不影响结果。
