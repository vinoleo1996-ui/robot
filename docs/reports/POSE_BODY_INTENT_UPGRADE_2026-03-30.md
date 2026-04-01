# Pose / Body-Intent 升级回看报告（2026-03-30）

目标：在 `D / H / G / E` 完成后，重新评估 pose / body-intent 技术路线，回答三个问题：

1. 当前仓库里的 pose 代码到底能做什么。
2. 它离“挥手招呼 / 张开双臂求抱抱 / 靠近迎接 / 转身离开”还有多远。
3. 面向 4090 的终局方案，应该继续修现有实现，还是切到更强路线。

## 执行摘要

结论先行：

- `pose` 长期确实需要，尤其是 body-intent 级别需求。
- 当前仓库里的 pose 代码只能算“实验原型”，还不能进入默认主线。
- 如果目标是 4090 上稳定支撑 `挥手招呼 / 求抱抱 / 靠近迎接 / 转身离开`，推荐路线不是继续堆 heuristic，而是：
  - `Fast-path`: `RTMPose / RTMW whole-body + tracking + rule gate`
  - `Second-stage`: 时间序列 body-intent classifier
  - 与现有 `face / gaze / audio / motion` 融合进入 scene arbitration

不推荐把当前 `MediaPipe Pose` 或 `YOLO Pose` 直接升成主线产品能力。更合理的做法是：

- 短期：保留现有 pose adapter 作为实验分支
- 中期：基于更强 whole-body pose 路线重建 body-intent
- 长期：形成 `person track -> whole-body keypoints -> body-intent state -> scene aggregation` 的正式链路

## 1. 当前代码真实能力

### 1.1 MediaPipe Pose 路线

代码位置：

- [mediapipe_pose_adapter.py](/Users/zheliu/Desktop/robot_life_dev/src/robot_life/perception/adapters/mediapipe_pose_adapter.py)

当前这条线做的是：

- 用 MediaPipe Pose 取 33 个身体关键点
- 基于肩膀和手腕的简单几何规则，检测：
  - `gesture_hug`
  - `gesture_waving`

它的特点是：

- 优点：轻、接入简单、本地机也能跑
- 缺点：规则非常硬，泛化差，场景稍一变化就容易误报/漏报

当前还存在两个实现级问题：

1. `waving` 逻辑里使用了 `np.diff` / `np.sum`，但文件没有导入 `numpy as np`
2. 这条路线没有进入当前默认本地 / 4090 主线快反应 profile，也没有专项 smoke / 回放集

所以这条线的真实定位应该是：

- 不是“已可交付能力”
- 而是“方向正确但实现尚未收口的实验原型”

### 1.2 YOLO Pose 路线

代码位置：

- [yolo_pose_adapter.py](/Users/zheliu/Desktop/robot_life_dev/src/robot_life/perception/adapters/yolo_pose_adapter.py)

当前这条线的设计意图是：

- 用 YOLO pose 拿关键点
- 再识别：
  - `open_palm`
  - `closed_fist`
  - `thumbs_up`
  - `victory`
  - `pointing`

但当前实现有一个结构性错位：

- YOLO 标准 pose 输出通常是人体 17 点
- 这里的手势模板却按 21 个手部关键点在写

所以它现在更像：

- “想做 skeleton/hand hybrid gesture”
- 但数据定义和模板假设没有对齐

结论：

- 当前这条线不适合作为主线 gesture / pose 方案
- 至少需要重新定义输入关键点语义后才能继续

## 2. 产品需求与 pose 的关系

你当前关心的几类能力：

1. `挥手招呼机器人过来`
2. `张开双臂求抱抱`
3. `靠近迎接`
4. `转身离开 / 不再互动`

这四类里，只有第一类可能被“纯手势”勉强覆盖，剩下三类都更偏 body-intent，而不是裸 gesture。

所以更准确的能力分层应该是：

- `face`: 识别是谁
- `gaze`: 是否看着机器人、是否持续等待回应
- `gesture`: 细粒度手势
- `pose / body-intent`: 身体级互动意图

也就是说，`pose` 的产品价值不是“再多一个 detector”，而是补齐 “生命感交互里的身体语言”。

## 3. 候选路线评估

### 3.1 MediaPipe Pose

来源：

- [MediaPipe Pose](https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker)

判断：

- 适合原型和本地轻量验证
- 不适合 4090 终局主线

原因：

- 强项是轻量、开箱快
- 弱项是 whole-body 细粒度不足，复杂 body-intent 需要大量 heuristic

适合位置：

- 本地原型 / 调试 / 小样本实验

不适合位置：

- 4090 主线产品能力

### 3.2 YOLO11 Pose

来源：

- [Ultralytics YOLO11](https://docs.ultralytics.com/models/yolo11/)

官方文档说明 YOLO11 支持 pose estimation、tracking 等多任务，适合生产部署；同时 Ultralytics 仍提供 AGPL-3.0 和商业许可两条路线。

判断：

- 如果你想要“接入简单、和现有 YOLO/motion 技术栈一致”的方案，YOLO11 pose 是可以评估的。
- 但它更适合“人体关键点 + 跟踪”的基础能力，不是现成的 body-intent 解决方案。

优点：

- 工程接入简单
- 和现有 Ultralytics 生态一致
- 4090 友好

风险：

- license 需要单独确认
- 如果只拿 17 点人体骨架，像“求抱抱”这种动作仍然要自己做时序与规则设计

适合位置：

- 作为 `person detect + pose track` 的工程方案

### 3.3 RTMPose / RTMW

来源：

- [MMPose 文档：RTMPose body 2D](https://mmpose.readthedocs.io/en/latest/model_zoo/body_2d_keypoint.html)
- [MMPose 文档：wholebody 2D](https://mmpose.readthedocs.io/en/latest/model_zoo/wholebody_2d_keypoint.html)
- [RTMPose 论文摘要页](https://huggingface.co/papers/2303.07399)
- [RTMW 论文摘要页](https://huggingface.co/papers/2407.08634)

当前公开信息里，RTMPose 是非常合适的候选：

- Hugging Face 论文页给出的摘要指出：`RTMPose-m` 在 COCO 上可达到 `75.8% AP`，并且在 Intel i7-11700 CPU 上 `90+ FPS`、在 GTX 1660 Ti 上 `430+ FPS`
- MMPose 文档里，`RTMPose-m 256x192` 给出 `74.9 AP`、`13.59M params`、`1.93G FLOPs`
- whole-body 文档还给出了 `rtmpose-m` 在 COCO-WholeBody 上的结果，说明它不是只看躯干，而是支持 face / hand / foot 在内的更细粒度人体关键点

这条路线对你最有价值的地方在于：

- 它比 MediaPipe Pose 更像“正式的 4090 产线候选”
- 它比当前 YOLO hand-template 路线更契合 whole-body body-intent
- 它天然更适合接 tracking 和时间序列状态机

结论：

- 如果要选一个最像“4090 主线 pose/body-intent 基座”的候选，我会优先选 `RTMPose / RTMW`

### 3.4 ViTPose / ViTPose++

来源：

- [Hugging Face Transformers: ViTPose](https://huggingface.co/docs/transformers/model_doc/vitpose)

Hugging Face 文档明确说明：

- ViTPose 是 top-down pose estimator
- 需要先有人体 detector，再做姿态估计
- ViTPose++ 支持多数据集 expert head，包括 COCO-WholeBody

判断：

- 这条路线更偏研究和高精度
- 如果目标是高质量 pose、并且 4090 算力充足，可以评估
- 但从工程落地角度，它比 RTMPose 更重

适合位置：

- second-stage 精细复核
- 研究 / 数据集适配

不适合位置：

- 当前快反应 fast-path 首选

## 4. 推荐技术路线

### 4.1 当前阶段

当前阶段不要把 pose 拉进默认主线。应该做的是：

1. 保留当前 pose adapter 作为实验分支
2. 不再继续往默认 profile 里塞现有 `MediaPipe Pose / YOLO Pose`
3. 先把本地主线继续稳定在 `face / gesture / gaze / audio / motion`

### 4.2 4090 下一阶段推荐方案

推荐主路线：

1. `person detection / tracking`
   建议沿用当前 YOLO 路线做 person track，后面接 body pose
2. `whole-body pose`
   优先评估 `RTMPose / RTMW`
3. `body-intent state`
   不是直接把 pose 当事件，而是按目标人 track 维护状态：
   - wave_calling
   - arms_open_hug_request
   - approach_ready
   - turn_away
4. `scene aggregation`
   把 body-intent 和 face/gaze/audio/motion 融合，而不是 pose 直接抢执行权

推荐目标能力：

- `body_wave_calling`
- `arms_open_hug_request`
- `approach_ready`
- `body_turn_away`

## 5. 替换成本评估

### 方案 A：继续修现有 MediaPipe Pose

范围：

- 修当前实现 bug
- 为 4 个 body-intent 写更多 heuristic
- 补 smoke / replay / UI 可观测性

成本：

- 低到中

问题：

- 规则会越来越脆
- 复杂度会不断堆在 heuristic 上
- 后续还是大概率要重做

结论：

- 只适合短期原型，不适合作为 4090 终局方案

### 方案 B：切到 RTMPose / RTMW，重建 body-intent

范围：

- 接入新的 pose pipeline
- 接 tracking
- 新增 body-intent temporal logic
- 接入 scene aggregation / replay / smoke

成本：

- 中

问题：

- 接入成本比修 MediaPipe 高
- 需要重新设计 pose -> body-intent -> scene 的接口

结论：

- 这是最值得做的正式路线

### 方案 C：YOLO11 pose 继续演进

范围：

- 保持 Ultralytics 技术栈统一
- 用 YOLO11 pose + track 替掉当前 YOLOv8 pose 试验代码

成本：

- 中

问题：

- 如果仍是 17 点骨架，body-intent 表达力不如 whole-body
- 仍需要自己搭时序和行为语义层

结论：

- 可以作为工程上手快的备选，但我仍把它排在 RTMPose / RTMW 后面

## 6. 潜在问题

1. `pose != body-intent`
   只升级 pose 模型并不能直接得到“求抱抱”这种产品能力，中间必须有时序状态层。

2. 需要 tracking
   没有稳定人 track，body-intent 很容易抖动、串人。

3. 需要和 gaze / face 做融合
   举例：双臂张开但没有看机器人，不一定应该触发“抱抱”。

4. 需要动作样本回放
   pose 主线化以后，必须补专门的 replay / smoke，不然很难稳定验证。

5. 商业许可要单独确认
   Ultralytics 的 AGPL / 商业许可边界、以及 face 相关 SDK 的 license 都要在量产前单独审查。

## 7. 最终建议

当前建议按这个节奏走：

1. 当前阶段不把 pose 纳入默认主线
2. 在 4090 下一阶段里，把 pose 升级成单独专题
3. 正式立项时优先评估：
   - `RTMPose / RTMW`
   - `YOLO11 pose`
   - `ViTPose` 只作为高精度备选
4. 目标不是“姿态检测”，而是“body-intent detection”
5. 第一批只做 4 个产品动作：
   - 挥手招呼
   - 张开双臂求抱抱
   - 靠近迎接
   - 转身离开

一句话收口：

`pose` 这件事该做，但不该继续沿着当前 heuristic adapter 小修小补地硬上主线。面向 4090，最优先的方向是用更强的 whole-body pose 基座，把它重新定义成 body-intent 能力。 
