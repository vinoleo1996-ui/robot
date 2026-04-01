# Phase Execution Todo V1

面向“终局可体验目标”的分阶段执行清单。按顺序推进，每完成一项就打勾并补回归。

## Phase 1 快反应体验版

- [x] 快链预算化：为 `face / motion / gesture / gaze / audio` 配置硬频率与硬预算，并接入 registry 级 cycle budget
- [x] 主循环快链收口：从“串行大循环”继续收口成更强预算控制的实时链
- [x] 同周期批量决策：同帧多事件统一进入 batch arbitration
- [x] P1/P2 公平队列：补齐覆盖、去抖、短时记忆与 starvation 防护
- [x] 动作 / 语音互斥矩阵与恢复语义闭环
- [x] 摄像头采集异步化：`collect_frames/read_packets` 脱离主循环，主循环只消费最新快照
- [ ] 单人互动体验回归：靠近、注视、挥手、环境运动、声音触发稳定响应
- [x] 多触发冲突回归：事件不打架、不饿死
- [ ] Phase 1 门禁回归：快反应单独运行 `p95 < 50ms`、连续运行 `1h` 无异常

## Phase 2 模型能力升级

- [ ] `motion` 升级到检测 + 跟踪路线
- [ ] `gaze` 升级到更强 gaze 模型
- [ ] `gesture` 路线定型并替换
- [ ] `face` 是否升级 embedding 模型评估与决策
- [ ] 模型升级后重跑 Phase 1 门禁

## Phase 3 快慢协同产品化

- [ ] 慢反应独立预算闭环
- [ ] GPU 优先级、回退与降载策略固化
- [ ] 慢反应必要时单独进程化
- [ ] UI / 日志补齐阶段耗时与决策原因观测
- [ ] Phase 3 门禁回归：快慢同时运行 `p95 < 80ms`、连续运行 `2h` 稳定

## Phase 4 终局可体验版 V1

- [ ] 固化 4090 默认配置
- [ ] 固化启动脚本、状态页、回归脚本
- [ ] 固化场景测试集与发布门禁
- [ ] 单人互动 / 双事件并发 / 家庭噪声 / 多目标切换 / 长稳运行完整验收

## 当前阶段回顾

- 本轮已完成：快链预算化、主循环快链收口、同周期批量决策、P1/P2 公平队列、动作/语音互斥矩阵与恢复语义闭环
- 本轮新增完成：多触发冲突回归
- 本轮新增完成：摄像头采集异步化（主循环去阻塞）
- 代码位置：
  - `PipelineSpec` 增加 `runtime_budget_ms`
  - `PipelineRegistry` 增加 pipeline reservation + cycle budget
  - `desktop_4090_stable/full_stable` 增加各 pipeline `runtime_budget_ms` 与 `fast_cycle_budget_ms`
  - `LiveLoop` 增加 fast-path budget、优先级优先处理、deferred backlog 与 backlog 上限
  - `LiveLoop` 增加同周期 scene coalesce 与 `max_scenes_per_cycle`
  - `ArbitrationRuntime` 增加 P2 覆盖队列、target-aware 公平淘汰与 starvation 提升
  - `BehaviorSafetyGuard` 扩展默认互斥矩阵，`BehaviorExecutor` 对 `HARD_INTERRUPT + resume_previous=false` 清空 stale resume
  - `BehaviorExecutor` 安全判定改为只参考“当前仍在执行的行为”，已结束行为不会错误阻塞后续排队动作
  - `validate_4090.py` 增加自动摄像头回退、`duration_sec`、`warmup_iterations` 与 JSON 报告
  - `validate_fast_reaction_experience.py` 新增单人互动体验回归脚本，可统计 `face/gaze/gesture/motion/audio` 触发覆盖
- 回归结果：
  - `pytest -q tests/unit/test_pipeline_factory.py tests/unit/test_live_loop_budget.py` => `28 passed`
  - `pytest -q tests/unit/test_live_loop_budget.py tests/unit/test_arbitration_batching.py` => `16 passed`
  - `pytest -q tests/unit/test_arbitration_batching.py tests/unit/test_live_loop_budget.py` => `18 passed`
  - `pytest -q tests/unit/test_behavior_safety_guard.py tests/unit/test_behavior_runtime.py tests/unit/test_live_loop_flows.py tests/unit/test_arbitration_batching.py` => `25 passed`
  - `validate_4090.py` 真机回归 => `camera_packets=59` `microphone_packets=31` `p50=25.11ms` `p95=57.20ms` `p99=213.53ms`
  - `pytest -q tests/unit/test_behavior_safety_guard.py tests/unit/test_arbitration_batching.py tests/unit/test_live_loop_budget.py` => `26 passed`
  - `pytest -q tests/unit/test_cli_smoke.py -k validate_4090_script_smoke` => `1 passed`
  - `python3 scripts/validate/validate_fast_reaction_experience.py --config configs/runtime/app.default.yaml ...` => mock smoke 通过，输出 `face/gaze/gesture/motion/audio` 覆盖统计
  - `validate_4090.py --warmup-iterations 12 --camera-device-index 0 --camera-read-timeout-ms 80 ...` 真机快链门禁基线 => `camera_device(actual)=5` `camera_packets=120` `microphone_packets=71` `p50=1.46ms` `p95=18.75ms` `p99=20.24ms`
  - 门禁剩余项：`1h` 长稳 soak 尚未完成；`单人互动体验回归` 仍需真人在镜头前完成动作清单
