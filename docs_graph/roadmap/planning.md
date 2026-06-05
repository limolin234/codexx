# Roadmap

## Phase 0: 架构固定

- [x] 写明核心模块边界。
- [x] 写明主 agent / buffer / task agent / memory maintainer 职责。
- [x] 创建 Python 最小接口骨架。
- [ ] 固定事件日志 JSONL 格式。
- [ ] 固定工具权限模型。

## Phase 1: 本地最小可运行系统

- [ ] 实现事件总线。
- [ ] 实现 mock main agent。
- [ ] 实现 mock fast buffer。
- [ ] 实现 task agent 生命周期：start / progress / pause / cancel / finish。
- [ ] 实现本地文件日志。
- [ ] 加入单元测试。

## Phase 2: 真实模型接入

- [ ] 接入强模型后端作为 main agent。
- [ ] 接入小模型后端作为 fast buffer。
- [ ] 接入廉价模型作为 memory maintainer。
- [ ] 加入上下文裁剪与 fork prompt 模板。

## Phase 3: 计算机管理能力

- [ ] shell 工具执行器。
- [ ] 文件读写工具执行器。
- [ ] 权限确认与风险分级。
- [ ] 操作日志和回滚提示。

## Phase 4: 语音与 NPU

- [ ] 输入适配器接口。
- [ ] VAD/ASR pipeline。
- [ ] NPU 后端探测。
- [ ] 本地唤醒/静音/打断策略。

## Phase 5: 边缘设备迁移

- [ ] 把模型、记忆、工具、语音全部替换为接口实现。
- [ ] 减少 Python 重依赖。
- [ ] 提供轻量部署配置。
