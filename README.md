# Advanced Agent

一个面向本地计算机管理与高效交流的 agent 架构原型。目标是做成类似 OpenClaw 的本地智能控制层，但更强调清晰边界、可迁移架构、可观察性和长期可维护性。

当前阶段已完成第一版可运行骨架：SQLite schema、上下文接口、supervisor、interrupt gate、audit agent mock、interactive/main agent mock。后续可接入语音输入、本地 NPU 模型、向量数据库、记忆维护模型、真实 OpenAI/本地模型后端和 Codex task worker。

## 推荐入口

直接启动增强交互式 Codex：

```bash
codexx
```

`codexx` 会自动使用本项目的 `.venv`，不需要手动激活虚拟环境。

`codexx` 使用一个默认配置文件 `.env.json`，并自动设置项目内运行时环境变量：

- `ADVANCED_AGENT_DB=runtime/advanced_agent.sqlite`
- `ADVANCED_AGENT_CONFIG=.env.json`
- `ADVANCED_AGENT_SCOPE=project:advanced_agent`
- `ADVANCED_AGENT_MEMORY_TRUST=high`

它会启动 Codex，并自动注入项目级 MCP server，让 Codex 能调用
`context_get`、`memory_write`、`memory_search` 等记忆/上下文工具。

## 核心思想

- **主 Agent 负责判断和思想反馈**：由强模型承担状态判断、总体策略、任务拆分、风险控制和与用户的关键沟通。
- **快速缓冲层负责低延迟交互**：小模型/轻量策略层夹在用户和主 Agent 之间，处理确认、澄清、临时反馈、等待提示，并允许用户或主 Agent 随时打断。
- **Fork 型任务 Agent 负责复杂执行**：主 Agent 可以把自身上下文裁剪后 fork 成任务态 agent，专心完成复杂任务，避免污染主循环上下文。
- **记忆不是聊天记录堆积**：用廉价但价值对齐的记忆维护模型，对对话和任务结果分段、摘要、打标签，再写入向量库和结构化索引。
- **本地优先，边缘可迁移**：I/O、模型、记忆库、工具执行全部通过接口隔离，方便从桌面迁移到边缘设备。
- **主进程监督子进程**：主进程作为 supervisor 拉起 fast buffer、task agent、memory worker、voice worker、tool executor，并负责中断、重启和动态模块更新。

## 初版目录

```text
advanced_agent/
├── README.md
├── AGENT.md                    # 给后续开发者/agent 的项目说明
├── docs/
│   ├── architecture.md          # 系统架构
│   ├── roadmap.md               # 开发路线
│   └── memory_design.md         # 记忆和向量库设计
├── src/advanced_agent/
│   ├── core.py                  # 领域对象和接口
│   ├── orchestrator.py          # 主循环原型
│   └── __init__.py
├── src/advanced_agent/
│   ├── agents/                  # interactive/main agent mock
│   ├── stores/                  # SQLite-backed data access interfaces
│   ├── runtime/                 # RuntimeApp composition root
│   ├── audit.py                 # rule-based audit agent skeleton
│   ├── interrupts.py            # interrupt gate/cooldown
│   ├── models.py                # shared data models
│   ├── supervisor.py            # process/task control plane
│   └── time_service.py          # wall/monotonic time service
└── tests/
    ├── test_core.py
    └── test_runtime.py
```

## 运行原型

```bash
python -m advanced_agent.orchestrator
```

如果没有安装成包，可临时运行：

```bash
PYTHONPATH=src python -m advanced_agent.orchestrator
```


## 交互试用

项目内虚拟环境已安装 `pytest` 和 `sqlite-vec`。启动本地交互原型：

```bash
source .venv/bin/activate
PYTHONPATH=src python -m advanced_agent.cli --db runtime/advanced_agent.sqlite --workdir .
```

可用命令：

```text
/mem TEXT       把 TEXT 写入 sqlite-vec 向量记忆
/search QUERY   搜索向量记忆
/help           查看帮助
/exit           退出
```

普通输入会走 `interactive-agent -> main-agent` mock 流程，先输出 provisional 快速反馈，再输出 authoritative 主 agent 结果。


## 真实模型配置

本项目使用 JSON 格式本地配置，默认读取 `.env.json`。该文件已被 `.gitignore` 忽略，不要提交 API key。可从模板复制：

```bash
cp .env.example.json .env.json
```

格式核心是：

```json
{
  "roles": {
    "interactive_model": "fast-local-or-cheap",
    "main_model": "strong-main",
    "audit_model": "audit-cheap",
    "codex_model": "default"
  },
  "models": {
    "strong-main": {
      "provider": "openai_compatible",
      "model": "MODEL_NAME",
      "base_url": "https://api.example.com/v1",
      "api_key_env": "MAIN_MODEL_API_KEY"
    }
  }
}
```

`codex_model: default` 表示 Codex task worker 仍使用 Codex CLI 自己的默认配置。`interactive_model` 和 `main_model` 若配置存在，会走 OpenAI-compatible `/chat/completions`；若 `.env.json` 不存在或角色为 `default`，则自动使用 mock/rule fallback。

运行：

```bash
PYTHONPATH=src python -m advanced_agent.cli --config .env.json --db runtime/advanced_agent.sqlite
```
