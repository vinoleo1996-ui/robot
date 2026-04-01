# 快慢协同架构规范 v1

## 1. 数据边界

- 快反应链路（端侧实时闭环）：
  - 输入：camera/microphone 检测结果
  - 输出：仲裁结果 + 行为执行（表情/TTS/动作）
  - 约束：不得依赖慢反应结果才能执行
- 慢反应链路（语义 sidecar）：
  - 输入：SceneCandidate + 采样帧
  - 输出：Scene JSON（scene_type/confidence/emotion/strategy/escalate）
  - 约束：禁止回流到仲裁和执行链路；仅作为云端提示词增强

## 2. 频率策略

- 快反应：
  - 按 pipeline `sample_rate_hz` 分频调度
  - 默认目标：camera 关键 pipeline 10-30Hz；audio 20-30Hz
- 慢反应：
  - 常驻 worker + 触发式提交
  - `sample_interval_s` 建议 >= 3s
  - `force_sample` 默认 false
  - 仅在不确定/冲突条件下提升触发频率

## 3. 仲裁原则

- P0：立即抢占（安全优先）
- P1：不可简单丢弃；支持短队列、覆盖与去抖
- P2/P3：可排队，超时淘汰
- 同周期批处理：同一批次 scene 统一排序后仲裁，避免“先到先打架”
- 公平性：同优先级按到达顺序调度

## 4. 性能预算（SLO）

### 快反应预算

- 端到端延迟（感知→决策→执行）：
  - p95 <= 100ms
  - p99 <= 150ms
- 仲裁时延：
  - p95 <= 10ms
- 主循环抖动（单轮耗时 std）：
  - <= 12ms
- 丢帧率（camera）：
  - <= 2%

### 慢反应预算

- 推理延迟：
  - avg <= 2500ms
  - p95 <= 6000ms
- 队列深度：
  - steady-state <= 3
  - 峰值 <= `queue_size`
- 超时率：
  - <= 2%
- drop 率：
  - <= 1%

## 5. GPU 运行策略

- Provider 优先级：`CUDAExecutionProvider -> CPUExecutionProvider`
- 回退策略：
  - 4090 生产配置下，关键快链路默认 `require_gpu=true`
  - 禁止静默 CPU 降级，必须日志告警
- 资源预算：
  - 4090 VRAM 峰值建议 <= 18GB

## 6. 回归测试矩阵

- 单元测试：
  - 感知适配器、稳定器、仲裁器、执行器、慢反应服务
- 集成测试（并发场景）：
  - face+gesture+gaze 同时触发
  - audio+motion 安全场景
  - P1 同优先级冲突与队列公平性
- 长稳 soak test：
  - 连续运行 >= 2 小时
  - 监控延迟漂移、队列积压、内存增长

## 7. 发布门禁（Release Gates）

- 必须满足：
  - 全量单测通过
  - 集成场景通过
  - 4090 基准达标（快/慢预算）
  - 无高危安全缺陷（P0）
- 阻断发布条件：
  - 快反应 p95 > 100ms
  - 慢反应 timeout/drop 超阈值
  - 发现静默 GPU->CPU 降级
