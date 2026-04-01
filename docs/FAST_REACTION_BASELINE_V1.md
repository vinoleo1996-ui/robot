# Fast Reaction Baseline V1

这份文档用于快速收敛当前快反应主线，只回答一个问题：

在模型能力升级开始前，我们把哪五类快反应功能、哪套模型、哪份配置视为当前正式基线。

## 1. 收敛目标

- 五类快反应 `face / gesture / gaze / audio / motion` 全部进入同一条正式 live runtime
- 优先保证实时性、鲁棒性和可回归，而不是先追求单项最强模型
- 4090 上默认使用一套可长期运行的快反应 profile，不和慢反应混用

## 2. 当前基线模型

| Pipeline | Baseline | Why |
|---|---|---|
| `face` | `InsightFace / buffalo_l_legacy` | 当前最成熟，已接入 CUDA，熟人/陌生人事件链最完整 |
| `gesture` | `MediaPipe Gesture Recognizer` | 接入最完整，延迟低，适合先收敛交互闭环 |
| `gaze` | `MediaPipe Face Landmarker / Iris` | 已经稳定接入，足够支撑“是否看我”这类快反应 |
| `audio` | `RMS loud sound detector` | 当前目标只是“声音触发快反应”，不做语义识别 |
| `motion` | `OpenCV motion detector` | 现阶段优先低抖动和低占用，先不用 YOLO 把快链拖重 |

## 3. 为什么现在不把升级模型直接作为主线

- `motion`:
  - `YOLO/ByteTrack` 更强，但现阶段会明显加重快链预算
  - 在我们还没完成 Phase 2 模型升级前，`OpenCV motion` 更适合作为快反应基线

- `gesture`:
  - `YOLO Pose / RTMPose` 还没有形成正式运行时闭环
  - 当前仓里的升级草案和实际 live runtime 还没完全对齐

- `gaze`:
  - 更强 gaze 模型值得做，但要放到 Phase 2，不应该抢在快反应基线收敛前

- `audio`:
  - `Whisper` 属于异步语义增强，不是快反应硬实时主链

## 4. 正式基线配置

- Runtime:
  - [desktop_4090_fast_reaction.yaml](/home/agiuser/桌面/robot_fast_Engine/robot_life_dev/configs/runtime/desktop_4090/desktop_4090_fast_reaction.yaml)
- Detectors:
  - [desktop_4090_fast_reaction.yaml](/home/agiuser/桌面/robot_fast_Engine/robot_life_dev/configs/detectors/desktop_4090/desktop_4090_fast_reaction.yaml)
- Launcher:
  - [run_ui_fast_reaction.sh](/home/agiuser/桌面/robot_fast_Engine/robot_life_dev/scripts/launch/run_ui_fast_reaction.sh)

## 5. 快反应基线预算

- `face`: `8 Hz`, `12 ms`
- `gesture`: `8 Hz`, `8 ms`
- `gaze`: `8 Hz`, `8 ms`
- `audio`: `10 Hz`, `4 ms`
- `motion`: `12 Hz`, `8 ms`
- `fast_cycle_budget_ms`: `24`
- `fast_path_budget_ms`: `28`

## 6. 这一版的含义

这不是“终局模型方案”，而是 Phase 1 的正式快反应基线。

后续所有快反应问题，默认先基于这套 profile 做回归：

- UI 体验
- 门禁 benchmark
- 单人互动回归
- 多触发冲突回归

Phase 2 再在这个基线之上替换：

- `motion -> YOLO + tracking`
- `gaze -> stronger gaze model`
- `gesture -> pose/upper-body or stronger hand gesture route`
