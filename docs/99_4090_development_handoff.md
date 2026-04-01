# 机器人生命感系统 4090 开发启动文档

## 1. 文档目的

本文档用于把当前已经确认的产品方向、系统架构、模型选型、开发目录和启动建议整理成一份统一材料，方便在另一台带 RTX 4090 的机器上直接开始 MVP 开发。

适用目标：

- 在 4090 桌面端搭建开发环境
- 启动机器人生命感系统 MVP 开发
- 先完成快思考主链路和慢思考基础接入

---

## 2. 当前项目目标

本项目目标不是做一个“会聊天的机器人”，而是做一个有生命感的主动交互引擎，让机器人在家庭或陪伴场景中表现出：

- 有呼吸
- 有判断
- 有变化
- 有边界
- 有连续性

当前总体架构分成两部分：

### 2.1 快思考系统

负责即时反馈，偏条件反射。

首期覆盖五类事件：

1. 人脸识别：熟人 / 陌生人
2. 高分贝突变与声音分类
3. 手势识别
4. 注视检测
5. 动态物体注意力抢占

### 2.2 慢思考系统

负责复杂语义场景理解，不进入实时主环。

职责：

- 对复杂场景做多模态理解
- 输出结构化 Scene JSON
- 将 Scene JSON 作为系统提示的一部分传给云端 LLM

---

## 3. MVP 的核心技术判断

当前最难的不是事件检测本身，而是：

- 事件稳定化
- 场景聚合
- 优先级仲裁
- 冷却与打扰边界控制
- 行为执行与恢复

因此 MVP 的主链路必须固定为：

```text
DetectionResult
  -> RawEvent
  -> StableEvent
  -> SceneCandidate
  -> ArbitrationResult
  -> Behavior Execution
```

不能让 detector 直接触发表情、动作或 TTS。

---

## 4. 4090 机器上的开发目标

4090 机器不是为了证明量产性能，而是为了完成这些事：

1. 跑通系统主链路
2. 集成五类感知能力
3. 验证事件稳定化 / 场景聚合 / 仲裁逻辑
4. 接入慢思考多模态模型
5. 建立 trace、日志、参数配置和回放能力

不在 4090 上直接证明：

- Orin NX 长稳
- 共享内存极限
- 最终功耗和热设计
- 最终 TensorRT 上限

---

## 5. 4090 MVP 模型选型结论

当前建议的主线模型如下：

| 模块 | MVP 主线 | 备选 | 原因 |
|---|---|---|---|
| 手势识别 | MediaPipe Gesture Recognizer | HaGRID v2 自定义训练 | 实时性强，集成成本低 |
| 表情/情绪 | HSEmotion | DeepFace | 情绪只做 scene hint，不做强决策 |
| 注视检测 | MediaPipe Face Mesh / Iris | MobileGaze | MVP 先做是否看我 |
| 声音事件 | RMS + YAMNet | PANNs | 快触发 + 异步补标签最符合架构 |
| 熟人识别 | InsightFace | DeepFace | 更利于后续迁移 Orin NX |
| 动态跟踪 | YOLO + ByteTrack | DeepStream/TAO | 4090 上最稳妥 |
| 慢思考 | Qwen3-VL-4B-Instruct | Qwen3.5 后续观察 | 公开落地路径更清晰 |

### 5.1 不建议作为首发主线

- DeepFace 全家桶式接入
- PANNs 直接进主链路
- Qwen3.5 作为首个本地多模态基线

---

## 6. 当前确定的工程结构

开发目录根路径建议为：

```text
robot_life_dev/
  docs/
  configs/
  data/
  logs/
  runtime/
  scripts/
  src/
  tests/
  tools/
```

源码结构：

```text
src/
  robot_life/
    common/
    perception/
    event_engine/
    behavior/
    slow_scene/
```

模块职责：

- `common`：schema、配置、日志、trace
- `perception`：五类感知 pipeline 和 adapter
- `event_engine`：事件构建、稳定化、场景聚合、仲裁
- `behavior`：资源管理、执行器、后续 BehaviorTree.CPP 集成
- `slow_scene`：多模态慢思考和 Scene JSON

---

## 7. 当前已经准备好的文档

在 `docs/` 下已整理好的文档：

- `00_project_structure.md`
- `01_prd.md`
- `02_sdd.md`
- `03_validation_4090.md`
- `04_migration_orin_nx.md`
- `05_model_selection_4090.md`

如果要带到 4090 机器上，建议整份 `docs/` 目录一起复制。

---

## 8. 当前工程骨架状态

当前已经准备好的内容：

- `pyproject.toml`
- 基础 Python 包结构
- 统一 schema
- 配置目录骨架
- 基础启动脚本
- synthetic demo 主链路骨架

关键文件包括：

- `pyproject.toml`
- `src/robot_life/app.py`
- `src/robot_life/common/schemas.py`
- `src/robot_life/common/config.py`
- `src/robot_life/event_engine/builder.py`
- `src/robot_life/event_engine/stabilizer.py`
- `src/robot_life/event_engine/scene_aggregator.py`
- `src/robot_life/event_engine/arbitrator.py`
- `src/robot_life/behavior/executor.py`
- `src/robot_life/slow_scene/service.py`

注意：

- 当前是“可启动开发的脚手架”
- 还不是完整可跑的业务系统
- 五类真实 detector 还没有正式接入

---

## 9. 4090 机器建议开发环境

### 9.1 硬件建议

- GPU：RTX 4090
- CPU：16 核以上优先
- 内存：64GB 以上优先
- 摄像头：1080p USB 摄像头
- 麦克风：单麦或阵列麦克风

### 9.2 软件建议

- Ubuntu 22.04 优先
- Python 3.10 或 3.11
- CUDA 与显卡驱动匹配
- Git
- CMake
- GCC / G++

### 9.3 Python 依赖建议

基础：

- pydantic
- pyyaml
- rich
- typer
- pytest
- ruff

按模块补：

- mediapipe
- insightface
- hsemotion
- ultralytics
- onnxruntime
- tensorflow 或 YAMNet 可运行环境
- torch
- transformers

---

## 10. 建议启动顺序

### Phase 1：先跑通工程骨架

目标：

- 安装 Python 环境
- 安装项目依赖
- 跑通 CLI 和 synthetic demo

建议命令：

```bash
cd robot_life_dev
bash scripts/bootstrap/bootstrap_env.sh
source .venv/bin/activate
python -m robot_life.app doctor
python -m robot_life.app run
pytest
```

### Phase 2：接入第一条真实 detector 链路

建议优先顺序：

1. `MediaPipe Gesture Recognizer`
2. `InsightFace`
3. `MediaPipe Face Mesh / Iris`

原因：

- 这三条更容易快速看到真实体验
- 更适合先验证事件稳定化和仲裁逻辑

### Phase 3：补上真正的事件稳定化

需要实现：

- debounce
- hysteresis
- dedup
- cooldown
- ttl

### Phase 4：补场景聚合

首批建议场景：

- `greeting_scene`
- `attention_scene`
- `safety_alert_scene`
- `gesture_bond_scene`
- `ambient_tracking_scene`

### Phase 5：补行为执行

短期：

- 先用 mock executor
- 输出日志、动作意图、TTS 意图

后续：

- 接 `BehaviorTree.CPP`

### Phase 6：接入慢思考

建议先用：

- `Qwen3-VL-4B-Instruct`

目标：

- 输出结构化 Scene JSON
- 异步运行
- 不阻塞主循环

---

## 11. MVP 验收重点

在 4090 开发阶段，优先验收这些指标：

### 11.1 系统正确性

- 五类事件可以统一进入事件链路
- detector 不直接触发行为
- 事件可以被稳定化、聚合和仲裁

### 11.2 体验正确性

- 不明显刷屏式打扰
- 同类事件不短时间重复触发
- 存在非语音反馈比例
- 行为有一定随机性和衰减

### 11.3 工程正确性

- 参数配置化
- 全链路 trace
- 可回放
- 模块边界清晰

---

## 12. 带到 4090 机器上的建议清单

建议直接带过去这些内容：

1. `robot_life_dev/docs/`
2. `robot_life_dev/configs/`
3. `robot_life_dev/scripts/`
4. `robot_life_dev/src/robot_life/`
5. `robot_life_dev/tests/`
6. `robot_life_dev/pyproject.toml`

如果只是先启动开发，优先保证：

- 文档
- 配置
- Python 包结构
- 启动脚本

---

## 13. 当前结论

当前状态已经满足：

- MVP 启动开发条件
- 4090 桌面端环境搭建条件
- 第一条真实检测链路接入条件

当前还未完成：

- 真正的模型接入
- 真正的稳定化逻辑
- 真正的行为树执行
- 真正的慢思考推理接入

所以准确判断是：

**现在已经完成“开发准备”，可以在 4090 机器上正式进入 MVP 实现阶段。**
