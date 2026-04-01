# 机器人生命感系统开发目录

本目录用于桌面端 MVP 开发，围绕以下目标组织：

- 快思考感知开发
- 事件稳定化 / 场景聚合 / 仲裁开发
- 行为树执行开发
- 慢思考 Scene JSON 开发
- 日志、回放、配置与测试

建议先固定目录结构和命名规则，再逐步填充实现。

## 文档入口

- [docs 入口索引](/Users/zheliu/Desktop/robot_life_dev/docs/README.md)
- [本地验证 Todo](/Users/zheliu/Desktop/robot_life_dev/docs/LOCAL_VALIDATION_TODO.md)
- [UI Demo 快速开始](/Users/zheliu/Desktop/robot_life_dev/docs/UI_DEMO.md)
- [开源模型升级可行性报告](/Users/zheliu/Desktop/robot_life_dev/docs/reports/OPEN_SOURCE_MODEL_FEASIBILITY_2026-03-30.md)
- [Pose / Body-Intent 升级回看报告](/Users/zheliu/Desktop/robot_life_dev/docs/reports/POSE_BODY_INTENT_UPGRADE_2026-03-30.md)

## 本地快反应体验

推荐使用 `Python 3.11`。如果系统里还没有，可先执行：

```bash
uv python install 3.11
```

```bash
cd /Users/zheliu/Desktop/robot_life_dev
bash scripts/bootstrap/bootstrap_env.sh
./scripts/launch/run_ui_local_fast_reaction.sh preflight
./scripts/launch/run_ui_local_fast_reaction.sh start
```

如果你只是想用最短路径直接起网页体验，现在可以直接用两个一键脚本：

```bash
cd /Users/zheliu/Desktop/robot_life_dev
./run_demo_mac.sh
./run_demo_mac_full_gpu.sh
```

它们会分别启动 `hybrid` 和 `full-gpu` 方案，并自动尝试打开 `http://127.0.0.1:8766`。

如果你更关心本地真机画面和交互流畅度，而不是一次性把所有感知链路都开满，可以先用 lite 模式：

```bash
cd /Users/zheliu/Desktop/robot_life_dev
./scripts/launch/run_ui_local_fast_reaction.sh preflight --lite
./scripts/launch/run_ui_local_fast_reaction.sh start --lite
```

`lite` 模式当前只保留更轻量的 `face / audio / motion` 组合，优先保证本地摄像头体验顺畅。

如果你想在 Mac 上尝试“五路全开”的本地真实体验，可以用 realtime 模式：

```bash
cd /Users/zheliu/Desktop/robot_life_dev
CAMERA_DEVICE=2 ./scripts/launch/run_ui_local_fast_reaction.sh preflight --realtime
CAMERA_DEVICE=2 ./scripts/launch/run_ui_local_fast_reaction.sh start --realtime
```

如果你更想先看五路全开的吞吐，而不是起网页，也可以直接跑：

```bash
cd /Users/zheliu/Desktop/robot_life_dev
CAMERA_DEVICE=2 bash scripts/validate/benchmark_local_mac_five_route.sh
```

如果你希望严格锁定相机索引（索引不可用时直接失败，不自动切换）：

```bash
cd /Users/zheliu/Desktop/robot_life_dev
CAMERA_DEVICE=2 STRICT_CAMERA_INDEX=1 bash scripts/validate/benchmark_local_mac_five_route.sh
```

`realtime` 模式当前仍然是 Apple Silicon 上的“尽量实时”五路方案：
- `face / gesture / gaze` 当前走稳定的 CPU/XNNPACK 路线
- `audio / motion` 仍主要走 CPU
- 目标是让 UI 观感接近实时，同时保持 5 路感知都在主链里
- 如果你想继续试 MediaPipe Metal delegate，请改用实验入口 `--full-gpu`

如果当前 Mac 还没放开相机 / 麦克风权限，但你想先体验 UI 和仲裁链路：

```bash
cd /Users/zheliu/Desktop/robot_life_dev
./scripts/launch/run_ui_local_fast_reaction.sh start --mock-if-unavailable
```

如果你正在排查启动细节，且明确知道自己在做什么，也可以临时跳过 preflight：

```bash
cd /Users/zheliu/Desktop/robot_life_dev
./scripts/launch/run_ui_local_fast_reaction.sh start --skip-preflight
```

如果你在做 CI / smoke，想强制走稳定的 mock 启动链路：

```bash
cd /Users/zheliu/Desktop/robot_life_dev
./scripts/launch/run_ui_local_fast_reaction.sh start --ci-mock
```

如果只是先做 mock 回归验证：

```bash
cd /Users/zheliu/Desktop/robot_life_dev
source .venv/bin/activate
python -m robot_life.app doctor
python scripts/validate/validate_fast_reaction_experience.py --duration-sec 5 --config configs/runtime/app.default.yaml --detectors configs/detectors/local/local_mac_fast_reaction.yaml
```

如果你想单独排查麦克风链路，可以先跑：

```bash
cd /Users/zheliu/Desktop/robot_life_dev
./.venv/bin/python scripts/validate/validate_microphone_only.py
```

如果你想“一键检查 5 路感知是否都处于 enabled+ready”，可以运行：

```bash
cd /Users/zheliu/Desktop/robot_life_dev
python scripts/validate/check_full_stack_ready.py --profile realtime --mock-if-unavailable
```

如果你要做“单人互动五阶段”回归（靠近/注视/挥手/环境运动/声音）并输出覆盖率报告：

```bash
cd /Users/zheliu/Desktop/robot_life_dev
python scripts/validate/validate_single_user_interaction.py --duration-per-phase-sec 10 --report-json /tmp/single_user_interaction.report.json
```

如果你跑 60s 体验验证，且设备可能被占用或权限未放开，建议带上 fallback：

```bash
cd /Users/zheliu/Desktop/robot_life_dev
python scripts/validate/validate_fast_reaction_experience.py --duration-sec 60 --config configs/runtime/local/local_mac_fast_reaction_realtime.yaml --detectors configs/detectors/local/local_mac_fast_reaction_realtime.yaml --mock-if-unavailable
```

本地快反应链路默认使用独立 stabilizer：
`configs/stabilizer/local/local_mac_fast_reaction.yaml`

## 场景回放验证

如果你想快速验证仲裁逻辑，不依赖真人站在镜头前触发，可以直接回放预置场景包：

```bash
cd /Users/zheliu/Desktop/robot_life_dev
source .venv/bin/activate
python scripts/validate/replay_arbitration_scenarios.py --scenario data/scenarios/greeting_then_gesture.json
python scripts/validate/replay_arbitration_scenarios.py --scenario data/scenarios/safety_hard_interrupt.json --report-json /tmp/safety_hard_interrupt.report.json
```

当前已内置 8 个核心场景包，覆盖 greeting / gesture queue / attention soft-interrupt / safety hard-interrupt / motion background / debounce / starvation promotion / cooldown recovery。

当前主线快反应默认启用 5 路感知：`face / gesture / gaze / audio / motion`。
`pose` 仍保留代码与实验配置支持，但不属于当前默认本地 / 4090 主线验证链路。

## Profile Smoke

为了让 mock / 本地 Mac / 4090 三条链路都能稳定做 CLI smoke，现在提供了独立入口：

```bash
cd /Users/zheliu/Desktop/robot_life_dev
bash scripts/validate/smoke_mock_profile.sh
bash scripts/validate/smoke_local_mac_profile.sh
bash scripts/validate/smoke_local_mac_lite_profile.sh
bash scripts/validate/smoke_local_mac_realtime_profile.sh
bash scripts/validate/smoke_desktop_4090_profile.sh
bash scripts/validate/regression.sh
```

## 当前骨架包含

- `docs/`：PRD、SDD、验证方案、迁移方案、目录规范、模型选型评估
- `configs/`：detectors、stabilizer、scenes、arbitration、behavior、runtime 默认配置
- `src/robot_life/`：桌面端 MVP 初始化包
- `scripts/`：环境初始化与启动脚本
- `tests/`：基础 smoke test

## 当前范围

这是一版开发前骨架，重点是：

- 统一 schema
- 最小事件链路
- 最小行为执行入口
- 最小慢思考 Scene JSON 入口

它已经具备本地快反应验证链路，但真机体验仍依赖本机相机 / 麦克风权限和模型资产状态。
