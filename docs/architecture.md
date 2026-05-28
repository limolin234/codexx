# Advanced Agent Architecture

## 1. 总览

系统由五层组成：

```text
User / Voice Input
       │
       ▼
Fast Interaction Buffer  ◄────────────── interrupt/control ─────┐
       │                                                         │
       ▼                                                         │
Main Reasoning Agent ───── fork/context slice ─────► Task Agent(s)
       │                                  │                      │
       │                                  ▼                      │
       │                           Tool Executor                 │
       │                                  │                      │
       ▼                                  ▼                      │
Memory Maintainer ─────► Structured Memory + Vector Database ◄───┘
```

## 2. 模块职责

### 2.1 Fast Interaction Buffer

快速缓冲层位于用户和主 agent 之间。它解决的是交互延迟问题，不解决深度思考问题。

职责：

- 快速确认用户输入已经收到；
- 在主 agent 或 task agent 工作时，向用户说明当前状态；
- 接收用户中途补充、取消、改方向；
- 把打断事件传给主 agent 或正在运行的 task agent；
- 对明显简单的问题可直接回答，但必须标记为 `buffer_final`，便于主 agent 后续审计。

非职责：

- 不做长期规划；
- 不直接执行高风险工具；
- 不直接写长期记忆；
- 不擅自替主 agent 完成复杂任务。

### 2.2 Main Reasoning Agent

主 agent 是系统的思考核心。它维护当前会话状态、用户意图、任务队列和风险判断。

职责：

- 判断用户意图；
- 决定是否需要澄清；
- 决定是否 fork task agent；
- 决定工具权限级别；
- 整合 task agent 结果；
- 决定哪些内容进入长期记忆；
- 给用户输出关键思想反馈。

设计约束：

- 主 agent 的上下文必须保持轻量；
- 长任务只保留摘要和关键状态，不保留完整过程；
- 主 agent 可以打断 buffer 或 task agent；
- 所有状态变化都写入事件日志。

### 2.3 Task Agent

Task agent 是由主 agent fork 出来的任务态 agent。它可以继承裁剪后的上下文，并专注完成一个边界清晰的任务。

职责：

- 完成复杂代码、文档、调研、调试、文件操作等任务；
- 在自己的局部上下文里保留详细过程；
- 定期向主 agent 汇报状态摘要；
- 接收 cancel / pause / redirect；
- 返回最终结果、变更列表、风险和后续建议。

Task agent 的创建输入：

- `task_id`
- `goal`
- `context_slice`
- `allowed_tools`
- `risk_level`
- `report_interval`

### 2.4 Memory Maintainer

记忆维护模型是廉价但价值对齐的小模型/中模型。它不直接决定行动，而是把事件流变成可检索的长期记忆。

职责：

- 分段；
- 摘要；
- 打标签；
- 判断记忆类型；
- 写入结构化索引和向量库；
- 定期压缩过期或重复记忆。

### 2.5 Tool Executor

工具执行层管理计算机操作。它必须独立于模型层，避免模型直接拥有无限系统权限。

职责：

- shell / 文件 / 浏览器 / GUI / 设备控制等工具适配；
- 权限检查；
- dry-run；
- 操作日志；
- 可回滚建议；
- 风险分级。

## 3. 事件模型

系统内部以事件驱动为主：

- `user_message`
- `buffer_reply`
- `main_agent_decision`
- `task_started`
- `task_progress`
- `task_finished`
- `tool_call_requested`
- `tool_call_finished`
- `interrupt_requested`
- `memory_candidate`
- `memory_committed`

事件日志是调试、审计、记忆维护和恢复会话的基础。

## 4. 中断模型

中断优先级：

1. 用户显式取消/改方向；
2. 主 agent 安全中断；
3. 工具层风险中断；
4. buffer 的低风险澄清中断。

Task agent 必须支持：

- `cancel`: 放弃任务并输出当前状态；
- `pause`: 暂停，等待主 agent 决策；
- `redirect`: 保留已有上下文，但修改目标；
- `snapshot`: 生成可恢复摘要。

## 5. 进程模型

系统默认由一个常驻主进程拉起多个子进程。主进程负责 supervisor / control plane，不把所有任务都塞进一个 Python 进程。

推荐拆分：

- `advanced-agentd`: 主进程，维护事件、状态、权限和 worker registry；
- `fast-buffer worker`: 低延迟交互；
- `main-agent worker`: 强模型思考核心；
- `task-agent worker(s)`: 按任务动态创建；
- `memory-maintainer worker`: 异步记忆维护；
- `voice-input worker`: 语音/VAD/ASR/NPU；
- `tool-executor worker`: 工具执行和权限隔离。

动态模块更新应由主进程执行：新模块先进入 staging，启动 shadow worker，自检通过后切流量，最后 drain 并停止旧 worker。详细见 `docs/process_model.md`。

## 6. 边缘设备迁移

为了后续迁移到边缘设备，以下部分必须接口化：

- LLM backend：云端强模型、本地小模型、本地 NPU 模型；
- Voice backend：麦克风、系统音频、ASR、VAD；
- Memory backend：本地 SQLite、向量库、文件日志；
- Tool backend：Linux shell、Android shell、IoT 控制、浏览器自动化。
