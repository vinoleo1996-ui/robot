# 4090 MVP 模型选型建议

## 1. 选型原则

- 优先保证体验闭环，而不是单模型能力最大化；
- 快思考优先选择实时、成熟、好集成的方案；
- 慢思考优先选择结构化输出稳定的多模态模型；
- 桌面端验证与 Orin NX 迁移之间保持接口不变、后端可替换。

---

## 2. 最终主线选型

| 模块 | MVP 主线 | 备选 | 说明 |
|---|---|---|---|
| 手势识别 | MediaPipe Gesture Recognizer | HaGRID v2 自定义训练 | 先追求实时与集成成本 |
| 表情/情绪 | HSEmotion | DeepFace | 情绪只做 scene hint |
| 注视检测 | MediaPipe Face Mesh / Iris | MobileGaze | MVP 先做是否看我 |
| 声音事件 | RMS + YAMNet | PANNs | 先快触发再异步补标签 |
| 熟人识别 | InsightFace | DeepFace | 更利于后续迁移 |
| 动态跟踪 | YOLO + ByteTrack | DeepStream/TAO | MVP 先用 Ultralytics |
| 慢思考 | Qwen3-VL-4B-Instruct | Qwen3.5 后续观察 | 先看结构化 Scene JSON 效果 |

## 2.5 当前代码基线收敛

现阶段真正已经收口到 live runtime 的快反应基线是：

| 模块 | 当前正式基线 | 原因 |
|---|---|---|
| 手势识别 | MediaPipe Gesture Recognizer | 已稳定接入，低延迟 |
| 注视检测 | MediaPipe Face Landmarker / Iris | 已稳定接入，足够支撑“是否看我” |
| 声音事件 | RMS Loud Sound | 快链只需要声响触发，不做语义 |
| 熟人识别 | InsightFace / buffalo_l_legacy | 当前集成最成熟 |
| 动态感知 | OpenCV Motion | 当前 Phase 1 优先低抖动，不把 YOLO 再压进快链 |

也就是说：

- `YOLO + ByteTrack` 仍然是 `motion` 的下一阶段升级主线
- 但在 Phase 1 快反应收敛期间，正式基线先固定为 `OpenCV motion`
- 对应 profile 见 [FAST_REACTION_BASELINE_V1.md](/home/agiuser/桌面/robot_fast_Engine/robot_life_dev/docs/FAST_REACTION_BASELINE_V1.md)

---

## 3. 暂不作为首发主线的方案

- DeepFace 全家桶式接入：适合 demo，不适合长期工程主线
- PANNs 直接进入主链路：偏重
- Qwen3.5 作为首个本地多模态基线：公开落地路径还不如 Qwen3-VL 清晰

---

## 4. 依赖建议

### 基础开发依赖

- `pydantic`
- `pyyaml`
- `rich`
- `pytest`

### 分模块依赖

- 手势 / 注视：`mediapipe`
- 表情：`hsemotion`
- 熟人识别：`insightface`
- 动态跟踪：`ultralytics`
- 声音：`tensorflow` 或等价运行时用于 YAMNet
- 慢思考：`transformers`、`torch`

---

## 5. 接口约束

所有 detector 只输出标准化 `DetectionResult`，不直接驱动行为。

慢思考只输出 `Scene JSON`，不直接驱动硬件动作。

---

## 6. 迁移原则

- 迁移到 Orin NX 时优先替换推理后端，而不是重写上层逻辑；
- 感知、事件链路、行为树、慢思考接口保持不变；
- 优先替换为 ONNX / TensorRT / DeepStream 兼容实现。
