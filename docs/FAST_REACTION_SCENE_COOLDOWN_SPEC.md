# Fast Reaction 场景、优先级与冷却链路说明

更新时间：2026-03-30

## 1. 当前 5 路感知与算力分配（代码真实行为）

当前 profile（`local_mac_fast_reaction*`）下的默认目标分配：

1. `face`：配置倾向 GPU（`use_gpu: true`，`require_gpu: false`），允许回落 CPU。
2. `gesture`：CPU（`use_gpu: false`）。
3. `gaze`：CPU（`use_gpu: false`）。
4. `audio`：CPU（RMS/YAMNet 路径都是 CPU）。
5. `motion`：CPU（OpenCV / torch-cpu 默认路径）。

说明：

- 在 macOS + MediaPipe 下，是否真正跑到 GPU，取决于 delegate 初始化结果。
- 快反应处理已支持受控并行：通过 `detector_global.fast_parallel_workers` 配置（默认 `1` 为串行）。
- 现在 UI 的 `compute_target` 已优先展示运行态（不是只看配置）。如果你看到 `gpu_requested_but_runtime_fallback_cpu`，表示“请求了 GPU，但运行时回退到了 CPU”。
- 你日志里出现 `Created TensorFlow Lite XNNPACK delegate for CPU`，就代表该路当前实际是 CPU 跑。

## 2. 场景 -> 行为（触发表情/动作/TTS）的最终大类

系统最终行为场景（`SceneAggregator + arbitration config`）是 6 类：

1. `safety_alert_scene`
2. `greeting_scene`
3. `gesture_bond_scene`
4. `stranger_attention_scene`
5. `attention_scene`
6. `ambient_tracking_scene`

对应行为（`configs/arbitration/default.yaml` + UI Playbook）：

1. `safety_alert_scene` -> `perform_safety_alert`
2. `greeting_scene` -> `perform_greeting`（降级：`greeting_visual_only`）
3. `gesture_bond_scene` -> `perform_gesture_response`（降级：`gesture_visual_only`）
4. `stranger_attention_scene` -> `perform_attention`（降级：`attention_minimal`）
5. `attention_scene` -> `perform_attention`（降级：`attention_minimal`）
6. `ambient_tracking_scene` -> `perform_tracking`

UI 自然语言面板中的 `动作 / 表情 / TTS` 来自 `ui_demo.py::_behavior_playbook()`。

## 3. 优先级与仲裁策略

事件优先级（`configs/arbitration/default.yaml`）：

1. P0：`safety_alert_detected` / `emergency_stop_detected` / `collision_warning_detected` / `loud_sound_detected`
2. P1：`familiar_face_detected` / `gesture_detected` / `direct_interaction` / `user_calling`
3. P2：`stranger_face_detected` / `attention_request` / `gaze_sustained_detected` / `gaze_away_detected`
4. P3：`motion_detected` / `ambient_tracking` / `background_monitoring`

仲裁模式：

1. P0：`immediate`（硬打断）
2. P1：`soft`（软打断）
3. P2：`queue`
4. P3：`never`（只排队/可丢弃）

## 4. 冷却与防抖：内外两层

### 4.1 内层（事件级）

内层发生在 detector/stabilizer 内：

1. Detector 冷却（例：audio `cooldown_s`，motion `motion_cooldown_sec`）。
2. Stabilizer：
   - debounce（防抖）
   - hysteresis（回滞）
   - dedup（去重）
   - cooldown（稳定事件冷却）
   - ttl（过期过滤）

`local_mac_fast_reaction` 中 `loud_sound_detected` 当前 override：

1. `debounce_count: 1`
2. `cooldown_ms: 1000`
3. `hysteresis_threshold: 0.5`

音频阈值当前已调整为更容易触发（本地 profile）：

1. `rms_threshold: 0.015`
2. `energy_threshold_db: -45`
3. `threshold_mode: any`（满足 RMS 或 dB 其一即可触发）
4. `relative_multiplier: 2.0`（支持相对基线突增触发，降低“绝对阈值在不同麦克风上失真”的漏检）
5. `relative_min_rms: 0.03`（避免安静底噪被放大误触发）
6. `baseline_alpha: 0.12`（运行时自适应环境噪声基线）

### 4.2 外层（场景级）

外层发生在 `CooldownManager`：

1. 全局冷却：默认 `3s`，抑制 P2/P3（P0/P1绕过）。
2. 场景冷却：按 scene_type 配置（如 greeting 30min、attention 5min、tracking 5s 等）。

本次修复：

- **P0 安全事件不再被外层场景冷却抑制**（`CooldownManager.check` 已调整），避免“明明有巨响却不触发安全反应”。

## 5. 为什么会出现“audio=1 但大声没反应”

高概率原因按优先级：

1. 首次触发后被外层安全场景冷却抑制（已修复 P0 bypass）。
2. 麦克风设备选中错误（有输入帧但不是你在说话的设备）。
3. 阈值双条件过严（已改为 `threshold_mode:any` 且下调阈值）。
4. 当前 cycle 压力大，音频事件在 fast path 被延后（可从 UI 的 queue/pending 与 telemetry 观察）。
5. 选中的输入设备不是你实际说话的麦克风（现在 preflight 会打印 `selected_name` 和设备列表）。

## 6. 专家评议核对（有则改之）

### 6.1 感知引擎串行化

结论：**基本属实（高优问题）**。

- `PipelineRegistry.process_all()` 仍是单循环串行调用，整体时延是各 pipeline 时延叠加。
- 当前架构虽有 async capture/perception/executor，但 perception worker 内部仍是串行。
- 建议：下一阶段引入“pipeline 并行执行 + 时间片预算 + 结果时效丢弃”。

### 6.2 CUDA 耦合风险

结论：**部分属实**。

- ONNX/InsightFace/Motion 等路径中存在 CUDA provider 与 `cuda:0` 默认值。
- 但 MediaPipe 在 Mac 走 delegate 路径（GPU 可用则走 GPU，不可用回落 CPU）。
- 建议：统一抽象 `device_policy`，显式输出“请求设备 vs 实际设备”，并分平台给默认策略。

### 6.3 预处理冗余

结论：**属实（中高优）**。

- 多模型路径各自做颜色转换/resize，存在重复 CPU 拷贝。
- 建议：引入共享预处理缓存（按 frame_id）与按模型需求切片，减少重复转换。

## 7. 你现在要看的关键可观测字段

1. `pipeline_monitors[*].compute_target`：实际算力位。
2. `pipeline_monitors[audio].last_event`：实时 rms/db 与阈值。
3. `gpu_backend / gpu_note / gpu_estimated_percent`：GPU 监控状态。
4. `event_transitions`：检测 -> 稳定 -> 场景 -> 决策 -> 执行链路。
5. `latest_reaction`：最终动作/表情/TTS。
