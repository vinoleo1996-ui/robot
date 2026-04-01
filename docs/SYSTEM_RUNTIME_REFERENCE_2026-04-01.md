# 系统运行总览（2026-04-01）

这份文档用于对齐当前本地五路感知主线的系统架构、交互状态机、事件检测频率、场景优先级和冷却逻辑。内容以当前代码与配置为准，主要覆盖 `hybrid -> local_mac` 这条本地主线。

## 1. 当前主线与 Profile

单一 profile 源定义在 `src/robot_life/profiles.py`。

- `hybrid -> local_mac`
- `full-gpu -> local_mac_full_gpu`
- `realtime -> local_mac_realtime`
- `lite -> local_mac_lite`

当前默认本地体验主线是 `hybrid`，它映射到：

- runtime: `configs/runtime/local/local_mac_fast_reaction.yaml`
- detectors: `configs/detectors/local/local_mac_fast_reaction.yaml`
- stabilizer: `configs/stabilizer/local/local_mac_fast_reaction.yaml`
- arbitration: `configs/arbitration/default.yaml`

## 2. 运行拓扑

### 2.1 主链路

当前 live runtime 的核心主链路在 `src/robot_life/runtime/live_loop.py`，运行顺序可以概括为：

1. `SourceBundle.read_packets()` 从 camera / microphone 读取最新输入
2. `collect_frames()` 把 camera 包装成 `CameraFrameDispatch`
3. `registry.process_all()` 跑五路 detector
4. `EventBuilder` 生成 detection event
5. `EventStabilizer` 做防抖、回滞、去重、冷却、TTL
6. `TemporalEventLayer` 做时序补充
7. `SceneAggregator` 把稳定事件提升为 scene candidate
8. `SceneCoordinator` 统一做 scene 合并、冷却过滤、target governance、按 path 分批
9. `ArbitrationRuntime / Arbitrator` 决定执行、排队、丢弃、抢占
10. `ExecutionManager` 下发 behavior 执行
11. `InteractionStateMachine` 根据结果更新交互状态
12. `RobotContextStore` 同步机器人上下文
13. `ResourceLoadShedder` 根据时延和排队压力做削峰

### 2.2 关键模块职责

- `src/robot_life/runtime/live_loop.py`
  - 负责采集、感知调度、排队、削峰、状态更新
- `src/robot_life/event_engine/scene_aggregator.py`
  - 负责把单点稳定事件提升为多信号 scene
- `src/robot_life/runtime/scene_coordinator.py`
  - 负责 scene 合并、过滤、target 治理、按 `safety/social` 分路
- `src/robot_life/common/state_machine.py`
  - 负责高层交互状态机
- `src/robot_life/event_engine/cooldown_manager.py`
  - 负责全局 / scene 层冷却
- `src/robot_life/event_engine/stabilizer.py`
  - 负责 event 层冷却与稳态

### 2.3 当前异步策略

本地 `hybrid` runtime 配置如下：

- `fast_path_budget_ms: 26`
- `fast_path_pending_limit: 24`
- `max_scenes_per_cycle: 3`
- `async_perception_enabled: true`
- `async_perception_queue_limit: 2`
- `async_perception_result_max_age_ms: 140`
- `async_perception_result_max_frame_lag: 3`
- `async_executor_enabled: true`
- `async_executor_queue_limit: 16`
- `async_capture_enabled: false`

这意味着：

- 感知计算允许异步
- 行为执行允许异步
- camera / mic 采集仍是主循环读
- 本地主线强调“稳定快反应”，不是最大吞吐

## 3. 五路感知配置

### 3.1 `hybrid` 默认五路

| 路由 | detector | 模型 / 实现 | 频率 | budget | 设备分配 |
| --- | --- | --- | --- | --- | --- |
| face | `mediapipe_face` | `face_landmarker.task` | `6 Hz` | `18 ms` | GPU 优先，失败回 CPU |
| gesture | `mediapipe_gesture` | `gesture_recognizer.task` | `5 Hz` | `12 ms` | CPU |
| gaze | `mediapipe_iris` | `face_landmarker.task` | `4 Hz` | `12 ms` | CPU |
| audio | `panns_whisper` | `PANNs + Silero VAD`，Whisper 默认关闭 | `2 Hz` | `18 ms` | `PANNs` 为 `auto`，Mac 上优先 MPS；其余 CPU |
| motion | `opencv` | 内建运动检测 | `6 Hz` | `12 ms` | CPU |

全局 detector 参数：

- 分辨率：`640 x 360`
- camera fps：`30`
- `fast_parallel_workers: 4`
- 麦克风采样率：`16000`
- 麦克风 blocksize：`2048`
- 麦克风最大缓存包数：`48`

### 3.2 `full-gpu` 与 `hybrid` 的区别

`full-gpu` 不是“五路全都在 GPU”。

- `face / gesture / gaze` 改成 GPU 优先
- `audio` 的 `PANNs` 固定 `mps`
- `motion` 仍是 CPU
- `Silero VAD` 仍是 CPU
- `Whisper` 即使打开，当前配置也是 CPU

## 4. 系统状态机

状态机定义在 `src/robot_life/common/state_machine.py`。

### 4.1 状态

- `IDLE`
- `NOTICED_HUMAN`
- `MUTUAL_ATTENTION`
- `ENGAGING`
- `ONGOING_INTERACTION`
- `RECOVERY`
- `SAFETY_OVERRIDE`

### 4.2 事件

- `NOTICE_HUMAN`
- `MUTUAL_ATTENTION`
- `ENGAGEMENT_BID`
- `INTERACTION_STARTED`
- `INTERACTION_FINISHED`
- `ATTENTION_LOST`
- `SAFETY_EVENT`
- `SAFETY_RESOLVED`

### 4.3 关键转移

| 输入事件 | 典型来源 | 状态变化 |
| --- | --- | --- |
| `NOTICE_HUMAN` | notice signal | `IDLE/RECOVERY -> NOTICED_HUMAN` |
| `MUTUAL_ATTENTION` | gaze / mutual attention signal | `NOTICED_HUMAN -> MUTUAL_ATTENTION` |
| `ENGAGEMENT_BID` | engagement scene | `NOTICED_HUMAN/MUTUAL_ATTENTION -> ENGAGING` |
| `INTERACTION_STARTED` | social execution 开始 | `ENGAGING -> ONGOING_INTERACTION` |
| `ATTENTION_LOST` | lost signal | 任意活跃交互态 -> `RECOVERY` |
| `SAFETY_EVENT` | P0 event 或 safety scene | 任意态 -> `SAFETY_OVERRIDE` |
| `SAFETY_RESOLVED` | safety clear | `SAFETY_OVERRIDE -> RECOVERY` |

### 4.4 超时

| 状态 | 超时 | 超时后转移 |
| --- | --- | --- |
| `NOTICED_HUMAN` | `5s` | `IDLE` |
| `MUTUAL_ATTENTION` | `6s` | `RECOVERY` |
| `ENGAGING` | `8s` | `RECOVERY` |
| `ONGOING_INTERACTION` | `30s` | `RECOVERY` |
| `RECOVERY` | `3s` | `IDLE` |
| `SAFETY_OVERRIDE` | `10s` | `RECOVERY` |

### 4.5 live loop 如何驱动状态机

`src/robot_life/runtime/live_loop.py` 的 `_update_life_state()` 当前按以下优先级触发：

1. 先看 `P0` stable event
2. 再看 `safety scene`
3. 如果还在 `SAFETY_OVERRIDE` 且安全已清除，则 `SAFETY_RESOLVED`
4. 再看 `attention_lost`
5. 再看 social execution
6. 再看 engagement scene
7. 再看 mutual attention signal
8. 最后看 notice signal

这意味着安全信号永远先于社交状态推进。

## 5. 事件检测频率与预算

### 5.1 五路检测频率

| 管线 | `sample_rate_hz` | 说明 |
| --- | --- | --- |
| face | `6` | 约每 `167 ms` 触发一次 |
| gesture | `5` | 约每 `200 ms` |
| gaze | `4` | 约每 `250 ms` |
| audio | `2` | 约每 `500 ms` |
| motion | `6` | 约每 `167 ms` |

### 5.2 fast path 预算

当前 `hybrid` 主线：

- 单周期 fast path 预算：`26 ms`
- backlog 上限：`24`
- 每周期最多保留 `3` 个 scene

这套配置配合 `async_perception_result_max_age_ms: 140` 和 `async_perception_result_max_frame_lag: 3`，核心目标是：

- 宁可丢弃过旧感知结果
- 也不让系统拿旧帧做社交反应

## 6. 场景生成与优先级

### 6.1 scene 聚合逻辑

`src/robot_life/event_engine/scene_aggregator.py` 的当前主要融合规则：

- `loud_sound + motion -> safety_alert_scene`
- `familiar_face + gaze -> greeting_scene`
- `stranger_face + gaze -> stranger_attention_scene`
- `gesture + gaze -> gesture_bond_scene`
- `motion -> ambient_tracking_scene`

单弱信号默认不会直接形成 scene，除非：

- 它是 P0 安全事件
- 或者分数超过 `min_single_signal_score`

### 6.2 事件优先级

优先级定义在 `configs/arbitration/default.yaml`。

| 优先级 | 事件 |
| --- | --- |
| `P0` | `safety_alert_detected` `emergency_stop_detected` `collision_warning_detected` `loud_sound_detected` |
| `P1` | `familiar_face_detected` `gesture_detected` `direct_interaction` `user_calling` |
| `P2` | `stranger_face_detected` `attention_request` `gaze_sustained_detected` `gaze_away_detected` |
| `P3` | `motion_detected` `ambient_tracking` `background_monitoring` |

### 6.3 scene 到 behavior 的映射

| scene | behavior | priority |
| --- | --- | --- |
| `greeting_scene` | `perform_greeting` | `P1` |
| `stranger_attention_scene` | `perform_attention` | `P2` |
| `attention_scene` | `perform_attention` | `P2` |
| `safety_alert_scene` | `perform_safety_alert` | `P0` |
| `gesture_bond_scene` | `perform_gesture_response` | `P1` |
| `ambient_tracking_scene` | `perform_tracking` | `P3` |

### 6.4 优先级行为策略

| 优先级 | interrupt | queue timeout |
| --- | --- | --- |
| `P0` | `immediate` | `0 ms` |
| `P1` | `soft` | `5000 ms` |
| `P2` | `queue` | `10000 ms` |
| `P3` | `never` | `15000 ms` |

### 6.5 path 分路

`SceneCoordinator` 会先做：

1. scene 合并
2. cooldown 过滤
3. target governance
4. 按 `safety` / `social` 分路

如果本周期已有 safety scene 成功执行，当前周期的 social scene 会被整体压制。

## 7. 冷却逻辑

### 7.1 第一层：事件稳态冷却

stabilizer 默认参数：

- `debounce_count: 2`
- `debounce_window_ms: 260`
- `cooldown_ms: 900`
- `dedup_window_ms: 320`
- `hysteresis_threshold: 0.58`
- `hysteresis_transition_high: 0.78`
- `hysteresis_transition_low: 0.52`
- `default_ttl_ms: 2200`

关键 event override：

| event | cooldown | dedup | ttl |
| --- | --- | --- | --- |
| familiar face | `1800 ms` | `800 ms` | `2600 ms` |
| stranger face | `1200 ms` | `550 ms` | `2200 ms` |
| gesture | `1500 ms` | `500 ms` | `1800 ms` |
| gaze sustained | `1200 ms` | `420 ms` | `1800 ms` |
| loud sound | `1000 ms` | `240 ms` | `1600 ms` |
| motion | `1000 ms` | `260 ms` | `1200 ms` |

### 7.2 第二层：全局 / scene 冷却

`CooldownManager` 采用三层模型：

- Layer 1: global cooldown
- Layer 2: scene cooldown
- Layer 3: event cooldown 交给 stabilizer

当前全局规则：

- `global_cooldown_s = 3.0`
- 任意 behavior 执行后，新的 `P2/P3` scene 在 3 秒内会被压制
- `P0/P1` 不受这一层影响

当前 scene cooldown：

| scene | cooldown |
| --- | --- |
| `greeting_scene` | `1800s` |
| `attention_scene` | `300s` |
| `gesture_bond_scene` | `10s` |
| `ambient_tracking_scene` | `5s` |
| `safety_alert_scene` | `30s` |

### 7.3 第三层：饱和保护

为了防止机器人频繁主动发起低价值行为，当前还启用了 proactive saturation：

- 窗口：`20s`
- 限额：`3`

对 `P2/P3` 的主动 scene 生效，主要覆盖：

- `greeting_scene`
- `attention_scene`
- `gesture_bond_scene`
- `ambient_tracking_scene`
- `stranger_attention_scene`

## 8. 当前系统的设计意图

当前本地主线并不是“把所有模型都堆到 GPU”，而是：

- 安全与交互的决策路径优先保持实时性
- vision 里最值得先吃 GPU 的是 face
- audio 的语义分类可以吃 MPS，但转写不强制进入主线
- 通过 stabilizer + cooldown + scene priority 保证行为不炸、不乱抢、不刷屏

## 9. 当前已知运行约束

### 9.1 macOS camera 读帧约束

`src/robot_life/runtime/sources.py` 在 macOS 上禁用了后台线程 `cv2.VideoCapture.read()`。

原因是 AVFoundation 路径在 Python worker thread 上有过原生崩溃风险。当前策略是：

- Darwin: camera read 保持同步
- 非 Darwin: 允许共享 worker 线程

### 9.2 本地主线更像“稳定优先”

这也是为什么 `hybrid` 选择：

- `async_capture_enabled: false`
- `gesture/gaze/motion` 保持 CPU 稳定路径
- `Whisper` 默认关闭

目标不是最大模型能力，而是本地真机体验先稳。
