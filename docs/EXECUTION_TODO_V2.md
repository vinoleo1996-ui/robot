# Execution Todo V2

面向终局目标的本轮执行清单。每完成一项，都需要补回归测试并打勾。

## P0 Core

- [x] 快反应正式运行链路补全：`face / gesture / gaze / audio / motion` 全部接入稳定运行配置
- [x] 事件优先级改为配置驱动，消除运行时关键词推断漂移
- [x] 同优先级仲裁增强：P1 短队列、公平淘汰、窗口去抖、覆盖策略
- [x] 慢反应稳态治理：按 `target/scene` 节流、pending 清理、背压闭环
- [x] 本地摄像头真实回归：快反应全量开启、慢反应开启、输出回归结果

## P1 Reliability

- [x] 完整 UI / CLI 状态可观测性核对：检测器加载、队列深度、仲裁结果、慢反应状态
- [x] 建立全量快反应稳定配置与启动脚本
- [x] 建立真实基准脚本：端到端延迟、loop fps、queue pending、slow queue、GPU 显存/利用率

## P2 Review

- [x] 完整单测回归
- [x] 本地摄像头实测回归
- [x] 最终 code review 报告
- [x] 最终性能测试报告

## 本轮回归摘要

- `pytest -q`：`133 passed`
- `detector-status`：五类快反应 pipeline 全部初始化成功
- `validate_4090.py`：本地摄像头 + 真慢反应 + 真麦克风回退链路通过
- live 音频：`sounddevice` 不可用时自动切到 `arecord`，本轮实测 `microphone_packets=37`
- 端到端回归：`camera_packets=58`，`latency_ms p50=20.30 p95=62.04 p99=207.66`
