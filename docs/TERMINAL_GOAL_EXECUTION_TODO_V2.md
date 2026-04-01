# Terminal Goal Execution Todo v2

## A. Baseline Closure

- [x] 复核当前缺口：快反应全量接入、仲裁鲁棒性、慢反应稳态、真实回归链路。
- [ ] 建立 full-stack 稳定配置：`face/gesture/gaze/audio/motion` 五类 pipeline 全开。
- [ ] 让真实回归脚本接入麦克风并输出 `microphone_packets`。
- [ ] 让真实回归脚本支持把麦克风链路纳入门禁。

## B. Fast Path Completion

- [ ] 让 `gesture/gaze/audio` 正式进入 live runtime 的稳定运行路径。
- [ ] 修正快反应优先级为配置驱动，不再只靠代码关键词猜测。
- [ ] 修正 `stabilizer` 配置与运行时 canonical event 名称漂移。
- [ ] 让 UI/运行态正确反映 full-stack 快反应加载和运行状态。

## C. Robust Arbitration And Slow Scene Stability

- [ ] 改造同优先级事件仲裁，避免简单 `DROP`。
- [ ] 让队列窗口去抖真正生效，并补齐公平淘汰策略。
- [ ] 加固慢反应按 `target/scene` 的背压与 pending 清理。
- [ ] 验证快慢反应在并发场景下不会互相拖垮。

## D. Regression And Final Review

- [ ] 复用现有 unit smoke 并补齐新增单测。
- [ ] 用本地摄像头做 full-stack 真机回归。
- [ ] 用本地麦克风做真机回归。
- [ ] 产出 full-stack 4090 基准结果：延迟、FPS、队列、GPU、显存。
- [ ] 全量完成后再做一遍完整 code review。
- [ ] 输出最终性能测试报告。
