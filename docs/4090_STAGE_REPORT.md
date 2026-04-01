# 4090 阶段报告

## 1. 文档信息

- 文档名称：4090 阶段报告
- 文档版本：V1.0
- 适用阶段：4090 真机联调阶段
- 记录日期：2026-03-27

---

## 2. 本阶段已完成项目

本节只记录仓库中已经落地、可以直接复用的事实，不写未验证结论。

### 2.1 已完成的工程项

| 项目 | 当前状态 | 依据 |
|---|---|---|
| 4090 真机验证主脚本 | 已完成 | `scripts/validate/validate_4090.py` |
| 4090 体验稳定性脚本 | 已完成 | `scripts/validate/validate_ux.py` |
| 摄像头单项验证脚本 | 已完成 | `scripts/validate/validate_camera_only.py` |
| 五类 detector 默认配置 | 已完成 | `configs/detectors/default.yaml` |
| 稳定化参数配置 | 已完成 | `configs/stabilizer/default.yaml` |
| 慢思考配置 | 已完成 | `configs/slow_scene/default.yaml` |
| 资源与仲裁配置 | 已完成 | `configs/behavior/default.yaml`、`configs/arbitration/default.yaml` |
| 端到端主链路脚手架 | 已完成 | `src/robot_life/app.py`、`src/robot_life/runtime/` |
| 关键单测 | 已完成 | `tests/unit/` |

### 2.2 已确认的运行入口

- 主链路健康检查：`python3 scripts/validate/validate_4090.py --config configs/runtime/desktop_4090/desktop_4090.yaml --iterations 120 --camera-device-index 5`
- 体验稳定性检查：`python3 scripts/validate/validate_ux.py --config configs/runtime/desktop_4090/desktop_4090.yaml --duration-sec 600 --camera-device-index 5`
- 摄像头可用性检查：`python3 scripts/validate/validate_camera_only.py --config configs/runtime/desktop_4090/desktop_4090.yaml --iterations 10 --camera-device-index 5`

### 2.3 已确认的默认事实

- `configs/runtime/desktop_4090/desktop_4090.yaml` 默认启用 `face/gesture/gaze/audio/motion` 五类 pipeline。
- `runtime.mock_drivers: false` 时走真机源，`camera-device-index` 可显式指定。
- `scripts/validate/validate_4090.py` 会输出 `latency_ms p50/p95/p99`、`executions`、`degraded`、`camera_packets`、`slow_scene timed_out/dropped`、`vram_max_mb`。
- `scripts/validate/validate_ux.py` 会输出 `duration_sec`、`iterations`、`executions`、`camera_packets`、`executions_per_min`、`silence_ratio`、`max_repeat_streak`、`max_repeat_within_10s`。
- 当前稳定化默认含 `debounce`、`hysteresis`、`dedup`、`cooldown`、`TTL`。
- 当前慢思考默认是异步侧路，`trigger_min_score: 0.8`，队列上限 `queue_size: 8`，单目标挂起上限 `max_pending_per_target: 1`。
- 当前资源配置默认包含 `HeadMotion`、`FaceExpression`、`AudioOut`。

---

## 3. 指标字段模板

### 3.1 主链路健康检查字段

| 字段 | 含义 |
|---|---|
| `iterations` | 实际循环次数 |
| `latency_ms p50` | 主循环中位延迟 |
| `latency_ms p95` | 主循环 95 分位延迟 |
| `latency_ms p99` | 主循环 99 分位延迟 |
| `executions` | 本轮行为执行总数 |
| `degraded` | 降级执行次数 |
| `camera_packets` | 采集到 camera packet 的次数 |
| `slow_scene timed_out` | 慢思考超时请求数 |
| `slow_scene dropped` | 慢思考丢弃请求数 |
| `vram_max_mb` | 运行期间显存峰值 |

### 3.2 体验稳定性检查字段

| 字段 | 含义 |
|---|---|
| `duration_sec` | 实际 soak 时长 |
| `iterations` | 主循环次数 |
| `executions` | 行为执行总数 |
| `camera_packets` | 采集到 camera packet 的次数 |
| `executions_per_min` | 每分钟执行次数 |
| `silence_ratio` | 空循环占比 |
| `max_repeat_streak` | 连续重复同一行为的最长串长 |
| `max_repeat_within_10s` | 10 秒窗口内重复行为上限 |

---

## 4. 当前结论模板

### 4.1 主链路结论模板

- 结论：`PASS` / `FAIL`
- 依据：命令、参数、时间、返回码、关键指标
- 备注：是否开启慢思考、是否为真机模式、是否存在降级

示例模板：

```text
结论：PASS
命令：python3 scripts/validate/validate_4090.py ...
时间：2026-03-27
返回码：0
关键指标：p95=...ms, camera_packets=..., vram_max_mb=...
备注：...
```

### 4.2 体验稳定性结论模板

- 结论：`PASS` / `FAIL`
- 依据：`max_repeat_streak`、`max_repeat_within_10s`、`camera_packets`
- 备注：是否出现刷屏式打扰、明显横跳、重复唤醒

示例模板：

```text
结论：PASS
命令：python3 scripts/validate/validate_ux.py ...
时间：2026-03-27
返回码：0
关键指标：max_repeat_streak=..., max_repeat_within_10s=..., executions_per_min=...
备注：...
```

---

## 5. 本轮实测结果（2026-03-27）

### 5.1 主链路健康检查

- 结论：PASS
- 命令：`python3 scripts/validate/validate_4090.py --config configs/runtime/desktop_4090/desktop_4090.yaml --iterations 120 --camera-device-index 5`
- 返回码：`0`
- 指标：
  - `iterations=120`
  - `latency_ms p50=31.43 p95=35.25 p99=62.91`
  - `executions=1 degraded=0`
  - `camera_packets=120`
  - `slow_scene timed_out=0 dropped=0`
  - `vram_max_mb=0.0`
- 关键结论：主链路可运行，camera packet 可持续采集，主循环延迟显著低于 500ms 预算。

### 5.2 体验稳定性检查（600s soak）

- 结论：PASS
- 命令：`python3 scripts/validate/validate_ux.py --config configs/runtime/desktop_4090/desktop_4090.yaml --duration-sec 600 --camera-device-index 5 --min-camera-packets 1`
- 返回码：`0`
- 指标：
  - `duration_sec=600.03`
  - `iterations=17434`
  - `executions=1`
  - `camera_packets=17434`
  - `executions_per_min=0.10`
  - `silence_ratio=1.00`
  - `max_repeat_streak=1`
  - `max_repeat_within_10s=1`
- 失败项回填：无（本轮 `UX VALIDATION PASSED`）。

---

## 6. 本阶段待补事实

- 长时多场景混合压测（包含多人、噪声、复杂光照）结果：待补。
- 体验主观评价（连续交互 30-60 分钟）结果：待补。
- 调参前后对比（sampling/cooldown/slow-trigger/resource）结果：待补。

---

## 7. 结论

当前阶段可确认：4090 真机验证链路与 600 秒 UX 稳定性检查均已通过，且摄像头输入在真机环境可持续采集，重复触发控制达到预期（无刷屏式重复行为）。

下一阶段应转入参数调优与复杂场景压力验证，重点关注慢思考触发策略和资源冲突下的退化体验。
