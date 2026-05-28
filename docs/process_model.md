# Process Model

## 1. 结论

Advanced Agent 应该使用一个常驻主进程拉起和管理多个子进程。

主进程不是所有任务的执行者，而是 supervisor / control plane：

- 维护全局状态；
- 启动、停止、重启子 agent；
- 分发事件；
- 管理权限；
- 管理模块版本；
- 处理用户和主 agent 发出的 interrupt；
- 负责崩溃恢复。

复杂任务、工具执行、语音输入、记忆维护、向量库维护等都可以拆成独立子进程。

## 2. 为什么用主进程拉起子进程

多 agent 系统里会遇到几个问题：

1. 子 agent 可能卡死；
2. 工具调用可能阻塞；
3. 语音输入需要常驻监听；
4. 记忆维护可以异步做；
5. 模块可能需要动态更新；
6. 不同模块权限级别不同；
7. 后续边缘设备上资源更紧张，需要能单独关闭某些模块。

如果所有东西都在一个 Python 进程里，热更新、权限隔离、崩溃恢复都会变差。因此初版可以先用简单 subprocess，后续再替换成更完整的 worker runtime。

## 3. 推荐进程划分

```text
advanced-agentd                 # 主进程 / supervisor
├── fast-buffer worker           # 快速交互缓冲，可低延迟重启
├── main-agent worker            # 强模型主思考循环，也可远程 API
├── task-agent worker(s)         # 按任务动态创建和销毁
├── memory-maintainer worker     # 异步总结、分段、打标签、入库
├── voice-input worker           # 麦克风/VAD/ASR/NPU
├── tool-executor worker         # shell/file/gui/device tools
└── vector-store worker          # 可选，本地向量库服务
```

## 4. 主进程职责

主进程应该保存：

- worker registry；
- event log；
- task table；
- module version table；
- permission policy；
- health check 状态；
- interrupt routing table。

主进程不应该直接保存：

- task agent 的完整长上下文；
- 语音模型内部状态；
- 工具执行器的临时输出大文件；
- 向量库内部索引细节。

## 5. Worker 生命周期

每个 worker 至少支持：

- `start`
- `ready`
- `heartbeat`
- `pause`
- `resume`
- `stop`
- `restart`
- `snapshot`
- `upgrade`

Task worker 额外支持：

- `cancel`
- `redirect`
- `progress`
- `final_report`

## 6. 通信方式

初版推荐：

- 主进程与 worker：stdin/stdout JSONL；
- 事件日志：本地 JSONL 文件；
- 大对象：文件路径引用，不直接塞进消息；
- 长期状态：SQLite；
- 向量库：后续单独 adapter。

JSONL IPC 的好处是简单、可调试、容易迁移。后续如果性能不够，再替换为 Unix domain socket、gRPC、ZeroMQ 或 NATS。

## 7. 动态模块更新

动态更新不要让 worker 自己随便替换自己，应该由主进程完成。

推荐流程：

```text
1. 主进程发现或收到 module_update_requested
2. 下载/加载新模块到 staging area
3. 校验 manifest、版本、hash、权限声明
4. 用新版本启动 shadow worker
5. shadow worker 自检 ready
6. 主进程把新请求切到新 worker
7. 老 worker drain 当前任务
8. 老 worker stop
9. 更新 module version table
```

这相当于小型 blue-green deployment，避免热更新把正在执行的任务搞坏。

## 8. 模块 Manifest

每个动态模块都应该带 manifest：

```json
{
  "name": "memory_maintainer",
  "version": "0.1.0",
  "entrypoint": "python -m advanced_agent.workers.memory",
  "protocol": "jsonl-ipc-v1",
  "permissions": ["read_event_log", "write_memory_store"],
  "healthcheck": {"kind": "heartbeat", "interval_seconds": 10}
}
```

## 9. 安全边界

主进程拉起子进程时应控制：

- cwd；
- 环境变量；
- 可读写目录；
- 可用工具；
- 网络权限；
- 最大运行时间；
- 最大输出大小；
- 是否需要用户确认。

工具执行器尤其不能和主 agent 混在同一进程里。
