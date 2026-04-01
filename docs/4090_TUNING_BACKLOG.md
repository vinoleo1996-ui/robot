# 4090 下一轮调优清单

## 1. 文档信息

- 文档名称：4090 下一轮调优清单
- 文档版本：V1.0
- 适用阶段：下一轮真机调优

---

## 2. 调优原则

- 先调体验，再调性能。
- 先收敛误触发，再压低打扰频率。
- 先保持异步慢思考不阻塞，再考虑提升理解质量。
- 先保留可回退参数，再做更激进的收敛。

---

## 3. 调优项总览

| 类别 | 优先级 | 目标 |
|---|---|---|
| sampling | P0 | 控制输入频率，避免无效高频处理 |
| cooldown | P0 | 减少重复触发和刷屏式打扰 |
| slow-trigger | P1 | 只在值得慢思考的场景触发 |
| resource | P1 | 降低资源争抢和行为降级概率 |

---

## 4. sampling 调优项

### 4.1 Face / Gaze / Gesture 采样频率

- 目标：在不损失明显体验的前提下，降低高频采样带来的 CPU/GPU 压力。
- 建议参数范围：
  - `face.sampling_fps`: `6-12`
  - `gaze.sampling_fps`: `6-12`
  - `gesture.sampling_fps`: `10-20`
- 验证方式：
  - 跑 `python3 scripts/validate/validate_4090.py --iterations 120 --camera-device-index 5`
  - 对比 `p95 latency`、`executions`、`degraded`、`camera_packets`
  - 观察是否出现感知掉帧或明显延迟上升

### 4.2 Motion 采样频率

- 目标：保留动态跟随的即时性，同时避免 motion 管线持续抢占资源。
- 建议参数范围：
  - `motion.sampling_fps`: `15-30`
  - 若资源紧张，优先尝试下调到 `15-20`
- 验证方式：
  - 检查 `motion_detected` 相关场景是否仍能及时触发
  - 观察长时运行中是否减少无效执行

---

## 5. cooldown 调优项

### 5.1 事件级 cooldown

- 目标：抑制同类事件重复唤醒，避免手势、注视、音频反复打断。
- 建议参数范围：
  - `familiar_face_detected`: `1500-3000 ms`
  - `gesture_detected`: `2000-4000 ms`
  - `gaze_hold_detected`: `1000-2500 ms`
  - `loud_sound_detected`: `1500-3000 ms`
  - `motion_detected`: `500-1500 ms`
- 验证方式：
  - 跑 `python3 scripts/validate/validate_ux.py --duration-sec 600 --camera-device-index 5`
  - 重点看 `max_repeat_streak` 和 `max_repeat_within_10s`
  - 若重复行为偏多，优先加长同类 cooldown

### 5.2 场景级 / 行为级 cooldown

- 目标：减少“刚执行完又立即再次触发”的体验问题。
- 建议参数范围：
  - `behavior_cooldowns`: `1000-5000 ms`
  - 对高打扰行为优先加大间隔
- 验证方式：
  - 对比 `executions_per_min`
  - 检查是否仍能保持必要的响应性

---

## 6. slow-trigger 调优项

### 6.1 慢思考触发阈值

- 目标：让慢思考只处理“复杂、冲突、低置信度”的场景。
- 建议参数范围：
  - `trigger_min_score`: `0.75-0.9`
  - 倾向先试 `0.8-0.85`
- 验证方式：
  - 跑 `python3 scripts/validate/validate_4090.py --enable-slow-scene --iterations 120 --camera-device-index 5`
  - 观察 `slow_scene timed_out`、`slow_scene dropped`
  - 统计慢思考是否只在不确定场景发生

### 6.2 慢思考队列和超时

- 目标：保证慢思考不拖慢主循环，也不堆积无效请求。
- 建议参数范围：
  - `queue_size`: `4-16`
  - `max_pending_per_target`: `1`
  - `request_timeout_ms`: `3000-8000`
- 验证方式：
  - 检查超时和丢弃是否可控
  - 确认主链路 `p95 latency` 不被拉高

---

## 7. resource 调优项

### 7.1 行为资源组合

- 目标：降低 `HeadMotion`、`FaceExpression`、`AudioOut` 的冲突概率。
- 建议参数范围：
  - 优先保持 `AudioOut` 作为独占资源
  - `HeadMotion`、`FaceExpression` 视场景允许共享或降级
- 验证方式：
  - 检查 `degraded` 计数是否可接受
  - 确认高优先级场景仍可抢占成功

### 7.2 降级策略

- 目标：在资源不足时仍保留“可执行、可理解、不中断”的体验。
- 建议参数范围：
  - 降级行为保持 1 个轻量版本
  - 对高频场景优先保留最小动作
- 验证方式：
  - 模拟资源占用冲突
  - 确认执行结果会进入可预期的 degraded 路径

---

## 8. 推荐执行顺序

1. 先调 `cooldown`，压低重复触发。
2. 再调 `sampling`，减少无效计算。
3. 然后调 `slow-trigger`，收紧慢思考触发面。
4. 最后调 `resource`，优化冲突和降级体验。

---

## 9. 记录模板

每轮调优建议至少记录：

- 参数修改前后的值
- 使用的命令
- 返回码
- `p95 latency`
- `executions_per_min`
- `max_repeat_streak`
- `max_repeat_within_10s`
- `slow_scene timed_out`
- `slow_scene dropped`
- 现场主观体验备注

