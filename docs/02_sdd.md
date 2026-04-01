# 机器人主动交互引擎系统设计文档

## 1. 文档信息

- 文档名称：机器人主动交互引擎系统设计文档
- 文档版本：V1.0
- 文档类型：系统设计文档
- 适用阶段：MVP 验证
- 适用对象：算法、端侧软件、测试、联调、架构

---

## 2. 设计目标

系统目标是构建一个端侧实时主动交互引擎，实现：

1. 多源感知统一事件化；
2. 检测结果稳定化；
3. 多事件场景化聚合；
4. 优先级和资源统一仲裁；
5. 行为树执行与打断恢复；
6. 慢思考语义理解异步接入；
7. 全链路可追踪、可调参、可回放。

---

## 3. 总体架构

### 3.1 分层架构

```text
Perception Layer
  -> Event Builder
  -> Event Stabilizer
  -> Scene Aggregator
  -> Arbitrator
  -> Resource Manager
  -> BehaviorTree Executor
  -> Drivers / Renderers

Parallel Side Path
  -> Slow Scene Understanding Service (Qwen-VL)
  -> Scene JSON
  -> Cloud LLM Strategy Layer
```

### 3.2 设计原则

- 感知模块不得直接触发动作；
- 慢思考模块不得直接控制底层硬件；
- 仲裁器负责决定“执行什么”；
- 行为树执行器负责决定“如何执行”；
- 所有行为必须显式声明资源；
- 所有关键对象均需 trace_id。

---

## 4. 模块划分

### 4.1 Perception Core

职责：

- 统一管理摄像头、麦克风和其他输入源；
- 调度多个感知 pipeline；
- 输出统一 `DetectionResult`；
- 处理采样率、帧率提升和降级策略。

内部以插件化 pipeline 组织：

- face pipeline
- gesture pipeline
- gaze pipeline
- audio pipeline
- motion pipeline

### 4.2 Event Builder

职责：

- 将 `DetectionResult` 转换为统一 `RawEvent`；
- 补齐事件元数据；
- 生成 `event_id`、`cooldown_key`、`ttl` 等字段。

### 4.3 Event Stabilizer

职责：

- debounce 去抖；
- hysteresis 迟滞；
- dedup 去重；
- cooldown 检查；
- ttl 校验；
- 生成 `StableEvent`。

### 4.4 Scene Aggregator

职责：

- 将多个 `StableEvent` 聚合成 `SceneCandidate`；
- 形成更高业务语义的场景候选；
- 为仲裁器提供更稳定的输入。

### 4.5 Arbitrator

职责：

- 基于优先级、状态、冷却、资源成本做决策；
- 生成 `ArbitrationResult`；
- 规定抢占、软打断、排队、降级或丢弃。

### 4.6 Resource Manager

职责：

- 管理 `AudioOut`、`HeadMotion`、`FaceExpression`、`BodyMotion` 等资源；
- 执行互斥、共享、ducking、降级授权；
- 输出 `ResourceGrant`。

### 4.7 BehaviorTree Executor

职责：

- 使用 `BehaviorTree.CPP` 执行具体行为树；
- 支持中断、软打断、恢复、降级；
- 输出 `ExecutionResult`。

### 4.8 Slow Scene Understanding Service

职责：

- 调用端侧轻量 Qwen 多模态模型；
- 生成结构化 `Scene JSON`；
- 作为高层语义理解服务异步工作；
- 不进入实时主环。

### 4.9 Trace Logger

职责：

- 记录原始检测、稳定事件、场景候选、仲裁结果、执行结果；
- 提供回放与分析能力；
- 为体验调优提供证据。

---

## 5. 感知系统设计

### 5.1 统一感知模块策略

MVP 采用“统一感知服务 + 插件化 pipeline”设计：

- 对上层暴露一个统一的感知接口；
- 内部各 pipeline 可独立维护、替换和调试；
- 统一时间基准、配置系统、日志和指标；
- 避免多个独立服务产生同步和维护成本。

### 5.2 各 pipeline 职责

#### face pipeline

- 输入：摄像头帧
- 能力：人脸检测、熟人识别、陌生人判定
- 输出：人脸相关 `DetectionResult`

#### gesture pipeline

- 输入：摄像头帧
- 能力：手部关键点与手势分类
- 输出：手势相关 `DetectionResult`

#### gaze pipeline

- 输入：摄像头帧
- 能力：注视近似检测、注视时长估计
- 输出：注视相关 `DetectionResult`

#### audio pipeline

- 输入：麦克风流
- 能力：RMS 监控、突发声检测、异步声音分类
- 输出：音频相关 `DetectionResult`

#### motion pipeline

- 输入：摄像头帧
- 能力：目标检测、跟踪、运动速度估计
- 输出：动态物体相关 `DetectionResult`

### 5.3 动态帧率策略

系统支持低功耗常态与短时增强模式：

- 常态：低采样率和低帧率；
- 触发后：提升局部 pipeline 的采样率；
- 事件结束后：逐步恢复默认采样。

用途：

- 降低长期资源消耗；
- 保证注意力聚焦阶段的感知质量；
- 兼顾生命感与实时性。

---

## 6. 数据模型

### 6.1 DetectionResult

```json
{
  "trace_id": "uuid",
  "source": "vision",
  "detector": "face_pipeline",
  "type": "familiar_face",
  "timestamp": 1710000000,
  "confidence": 0.93,
  "payload": {
    "target_id": "user_dad",
    "bbox": [0.12, 0.2, 0.28, 0.4],
    "face_area_ratio": 0.08
  }
}
```

### 6.2 RawEvent

```json
{
  "event_id": "uuid",
  "trace_id": "uuid",
  "event_type": "familiar_face_detected",
  "priority": "P2",
  "timestamp": 1710000000,
  "confidence": 0.93,
  "source": "face_pipeline",
  "ttl_ms": 3000,
  "cooldown_key": "face_user_dad",
  "payload": {
    "target_id": "user_dad"
  }
}
```

### 6.3 StableEvent

```json
{
  "stable_event_id": "uuid",
  "base_event_id": "uuid",
  "trace_id": "uuid",
  "event_type": "familiar_face_detected",
  "priority": "P2",
  "valid_until": 1710000005,
  "stabilized_by": ["debounce", "cooldown"],
  "payload": {
    "target_id": "user_dad"
  }
}
```

### 6.4 SceneCandidate

```json
{
  "scene_id": "uuid",
  "trace_id": "uuid",
  "scene_type": "greeting_scene",
  "based_on_events": ["E101", "E106"],
  "score_hint": 0.78,
  "target_id": "user_dad",
  "valid_until": 1710000008
}
```

### 6.5 ArbitrationResult

```json
{
  "decision_id": "uuid",
  "trace_id": "uuid",
  "target_behavior": "greeting_light",
  "priority": "P2",
  "mode": "SOFT_INTERRUPT",
  "required_resources": ["HeadMotion", "FaceExpression"],
  "optional_resources": ["AudioOut"],
  "degraded_behavior": "greeting_visual_only",
  "resume_previous": true,
  "reason": "greeting_scene won arbitration"
}
```

### 6.6 ResourceGrant

```json
{
  "grant_id": "uuid",
  "decision_id": "uuid",
  "granted": true,
  "granted_resources": ["HeadMotion", "FaceExpression"],
  "denied_resources": ["AudioOut"],
  "degrade_required": true,
  "queue_required": false
}
```

### 6.7 ExecutionResult

```json
{
  "execution_id": "uuid",
  "trace_id": "uuid",
  "behavior_id": "greeting_light",
  "status": "finished",
  "interrupted": false,
  "degraded": true,
  "started_at": 1710000001,
  "ended_at": 1710000003
}
```

### 6.8 Scene JSON

```json
{
  "scene_type": "child_staring_with_hesitation",
  "confidence": 0.74,
  "involved_targets": ["child_01"],
  "emotion_hint": "curious_and_waiting",
  "urgency_hint": "low",
  "recommended_strategy": "gentle_nonverbal_attention_first",
  "escalate_to_cloud": true
}
```

---

## 7. 事件稳定化设计

### 7.1 目标

事件稳定化的目标不是“让检测更准”，而是让系统行为更稳。

### 7.2 处理策略

#### debounce

- 人脸、手势、注视、靠近类事件要求连续满足时间门槛；
- 避免单帧误判直接触发。

#### hysteresis

- 对距离、面积、注视偏移等阈值采用进入/退出不同阈值；
- 避免边界来回抖动。

#### dedup

- 相同 `cooldown_key` 的重复事件在有效窗口内合并；
- 多 detector 同时报出的同类结果按规则融合。

#### ttl

- 事件具有时效性，超时后自动失效，不进入长尾排队。

#### cooldown

- 全局冷却；
- 场景冷却；
- 用户自适应冷却。

---

## 8. 场景聚合设计

### 8.1 场景聚合目标

- 将多个弱信号合并为业务场景；
- 降低误触发；
- 把“检测到什么”转成“现在发生了什么”。

### 8.2 首批 MVP 场景

| 场景ID | 场景名 | 聚合逻辑 |
|---|---|---|
| S001 | greeting_scene | 熟人脸 + 停留 / 靠近 |
| S002 | stranger_attention_scene | 陌生人脸 + 稳定注视 |
| S003 | attention_scene | 注视 + 视野稳定 |
| S004 | safety_alert_scene | 高分贝 + 声音分类 |
| S005 | gesture_bond_scene | 手势 + 注视 |
| S006 | ambient_tracking_scene | 动态物体 + 空闲态窗口 |

### 8.3 聚合规则示例

- `familiar_face_detected + approach_or_stay` -> `greeting_scene`
- `gaze_hold_detected + no_active_dialog` -> `attention_scene`
- `loud_sound_detected + sound_type_classified(glass_breaking)` -> `safety_alert_scene`
- `gesture_detected(heart) + gaze_hold_detected` -> `gesture_bond_scene`

---

## 9. 仲裁设计

### 9.1 优先级规则

| 优先级 | 含义 | 抢占策略 |
|---|---|---|
| P0 | 安全/紧急 | 立即抢占 |
| P1 | 直接交互 | 软打断低优先级 |
| P2 | 被动感知 | 排队或条件触发 |
| P3 | 氛围维持 | 不主动抢占 |

### 9.2 仲裁输入

- `StableEvent`
- `SceneCandidate`
- 当前系统状态
- 当前执行行为
- 资源快照
- 冷却状态

### 9.3 仲裁输出

仲裁器输出以下结果之一：

- execute
- soft_interrupt
- hard_interrupt
- degrade_and_execute
- queue
- drop
- silent_record_only

### 9.4 动态评分建议

同优先级内可引入评分：

`score = urgency + user_relevance + continuity_bonus + novelty_bonus - interruption_cost - repetition_penalty - resource_cost`

MVP 可先采用规则优先，评分作为辅助字段。

---

## 10. 冷却设计

### 10.1 三层冷却

#### 全局冷却

- 任意主动交互后进入短时全局抑制；
- 冷却期间仅放行 P0，条件放行 P1。

#### 场景冷却

- 每个场景独立配置；
- 示例：
  - 熟人欢迎：30 分钟
  - 手势：10 秒
  - 注视：5 分钟
  - 动态物体：5 秒
  - 高分贝：5 秒 / 同类 30 秒

#### 用户自适应冷却

- 用户积极回应：缩短下一次冷却；
- 用户无视或拒绝：延长冷却；
- 夜间模式：整体放大冷却系数。

### 10.2 安静模式

状态属性：

- `silent_mode = true`
- `audio_suppressed = true`

行为规则：

- P2/P3 默认仅允许表情与轻动作；
- P1 可弱化；
- P0 不受影响。

---

## 11. 行为执行设计

### 11.1 为什么使用 BehaviorTree.CPP

MVP 推荐使用 `BehaviorTree.CPP`，原因如下：

- 支持 Sequence、Fallback、Reactive 组织；
- 支持异步 action；
- 支持打断和恢复；
- 有利于复杂行为快速迭代；
- 后续量产可持续复用。

### 11.2 模块边界

#### 仲裁器负责

- 选择哪个 behavior；
- 决定是否打断、排队、降级；
- 申请哪些资源。

#### 行为树负责

- 执行动作顺序；
- 管理动作最小执行单元；
- 实现表情、动作、TTS 编排；
- 响应中断和恢复。

### 11.3 行为树节点建议

基础节点分类：

- condition nodes：状态检查、资源检查、冷却检查
- action nodes：表情、头部动作、身体动作、TTS、等待
- decorator nodes：超时、重试、概率触发、衰减
- control nodes：sequence、fallback、reactive sequence

### 11.4 示例行为树

`greeting_light`

1. 检查目标是否仍在视野中
2. 检查资源授权
3. 头部转向目标
4. 轻表情变化
5. 按概率决定是否播放简短 TTS
6. 回归中性态

`safety_alert`

1. 立即中断当前低优先级行为
2. 头部快速转向声源
3. 惊讶表情
4. 按类型选择一句短反馈或静默观察
5. 短时保持警觉
6. 恢复待机

---

## 12. 资源管理设计

### 12.1 资源定义

MVP 推荐至少管理以下资源：

- `AudioOut`
- `HeadMotion`
- `BodyMotion`
- `FaceExpression`
- `AttentionTarget`
- `DialogContext`

### 12.2 资源规则

- `AudioOut` 默认互斥；
- `HeadMotion` 与 `FaceExpression` 可并发；
- `BodyMotion` 受安全约束；
- `DialogContext` 受保护窗口约束；
- 某些行为在资源不足时允许降级为“仅表情”或“仅动作”。

---

## 13. 慢思考系统设计

### 13.1 触发机制

触发源包括：

- 快思考发出 `complex_scene_candidate`
- 周期性低频触发
- 多事件冲突无法通过规则明确解释

### 13.2 输入拼装

慢思考输入建议包含：

- 最近 N 秒多模态帧摘要；
- 最近事件序列；
- 当前状态；
- 目标 Schema JSON；
- 必要的人设和行为边界提示。

### 13.3 输出使用方式

`Scene JSON` 的用途：

- 更新场景状态缓存；
- 作为云端 LLM 的系统提示组成部分；
- 供仲裁器参考，但不强制覆盖快思考结论。

### 13.4 超时与失效

- 慢思考结果超时后不得应用；
- 结果置信度低时仅记录；
- 主循环不可等待慢思考结果。

---

## 14. 状态机建议

### 14.1 主状态

- Idle
- Attention
- Interaction
- Dialog
- SilentMode
- SafetyOverride
- Recovery

### 14.2 状态切换原则

- `SafetyOverride` 优先级最高；
- `Dialog` 期间默认保护 `AudioOut` 和 `DialogContext`；
- `SilentMode` 作为全局约束层，不是独立行为；
- 任何执行结束后进入 `Recovery`，再回 `Idle` 或 `Attention`。

---

## 15. 线程与运行模型

### 15.1 MVP 运行模型

推荐 MVP 使用单进程多线程：

- `MainThread`：事件循环、仲裁、状态管理
- `VisionThread`：摄像头采集与分发
- `FaceThread`
- `GestureGazeThread`
- `MotionThread`
- `AudioThread`
- `SlowSceneThread`
- `TraceThread`

### 15.2 工程要求

- 统一 monotonic time；
- 队列长度可配置；
- 事件对象不可变或尽量只读；
- 对共享状态做最小化写入；
- 单模块失败可恢复。

---

## 16. 配置与调参

### 16.1 配置分层

- detector config：阈值、采样率、置信度
- stabilizer config：debounce、hysteresis、ttl、dedup
- scene config：聚合规则、窗口长度
- arbitration config：优先级、评分、队列、抢占策略
- cooldown config：全局、场景、用户自适应
- behavior config：概率、衰减、TTS 池、动作池

### 16.2 参数原则

- 参数全部配置化；
- 支持热更新优先；
- 关键参数必须具备版本记录；
- 每次实验需关联配置版本与 trace 数据。

---

## 17. 可观测性与测试

### 17.1 Trace 要求

每条链路至少包含：

- `trace_id`
- `event_id`
- `scene_id`
- `decision_id`
- `execution_id`

### 17.2 日志要求

- 原始检测日志
- 稳定化命中日志
- 场景聚合日志
- 仲裁日志
- 资源授权日志
- 行为执行日志
- 慢思考输入输出日志

### 17.3 MVP 测试建议

测试集应覆盖：

- 单事件稳定触发
- 多事件冲突
- 连续误触边界
- 冷却有效性
- 安静模式
- P0 抢占
- 资源不足降级
- 慢思考超时丢弃

---

## 18. MVP 技术选型建议

### 18.1 感知

- 人脸：DeepFace MVP，后续可迁移 InsightFace
- 手势 / 注视：MediaPipe
- 动态目标：YOLO + ByteTrack
- 音频：RMS + 轻量声音分类

### 18.2 慢思考

- 端侧轻量 Qwen 多模态
- 结构化 Scene JSON 输出

### 18.3 执行与编排

- `BehaviorTree.CPP` 负责行为树执行
- 业务仲裁独立实现

---

## 19. MVP 落地顺序建议

### Phase 1

- 打通统一感知模块
- 输出标准 `DetectionResult`

### Phase 2

- 完成 `Event Builder`、`Event Stabilizer`
- 建立基础冷却和去抖机制

### Phase 3

- 完成 `Scene Aggregator`、`Arbitrator`
- 跑通 P0-P3 规则

### Phase 4

- 接入 `BehaviorTree.CPP`
- 实现欢迎、注视、高分贝、手势、动态跟随五类行为树

### Phase 5

- 接入慢思考服务
- 输出 Scene JSON 并联调云端策略层

### Phase 6

- 建立 trace、回放、调参闭环
- 进行真实场景体验验证

---

## 20. 结论

该系统的关键成功点不在于继续堆叠更多检测模型，而在于建立一套稳定、克制、可仲裁、可回放的主动交互主链路。

MVP 阶段的优先级应明确为：

1. 事件稳定化
2. 场景聚合
3. 仲裁与冷却
4. 行为树执行
5. 慢思考异步接入

只有上述主链路成立，机器人才能真正呈现出“有生命感但不烦人”的体验。
