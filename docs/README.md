# docs

用于存放产品、架构、验证方案、接口设计、联调说明、开发清单等文档。

## 入口索引

### 项目总览

- [目录规范](/Users/zheliu/Desktop/robot_life_dev/docs/00_project_structure.md)
- [PRD](/Users/zheliu/Desktop/robot_life_dev/docs/01_prd.md)
- [SDD](/Users/zheliu/Desktop/robot_life_dev/docs/02_sdd.md)
- [系统运行总览（2026-04-01）](/Users/zheliu/Desktop/robot_life_dev/docs/SYSTEM_RUNTIME_REFERENCE_2026-04-01.md)
- [UI Demo 快速开始](/Users/zheliu/Desktop/robot_life_dev/docs/UI_DEMO.md)

### 本地验证

- [本地验证 Todo](/Users/zheliu/Desktop/robot_life_dev/docs/LOCAL_VALIDATION_TODO.md)
- [Mac 本地体验报告](/Users/zheliu/Desktop/robot_life_dev/docs/MAC_LOCAL_EXPERIENCE_REPORT.md)
- [本地运行时深度 Review 与优化方案（2026-04-01）](/Users/zheliu/Desktop/robot_life_dev/docs/reports/LOCAL_RUNTIME_DEEP_REVIEW_2026-04-01.md)
- [快反应基线](/Users/zheliu/Desktop/robot_life_dev/docs/FAST_REACTION_BASELINE_V1.md)
- [快反应模型可行性与升级报告（2026-03-30）](/Users/zheliu/Desktop/robot_life_dev/docs/reports/FAST_REACTION_MODEL_FEASIBILITY_2026-03-30.md)
- [Pose / Body-Intent 升级回看报告（2026-03-30）](/Users/zheliu/Desktop/robot_life_dev/docs/reports/POSE_BODY_INTENT_UPGRADE_2026-03-30.md)
- 推荐解释器版本：`Python 3.11`
- 如果系统里还没有：`uv python install 3.11`
- 本地入口脚本：`./scripts/launch/run_ui_local_fast_reaction.sh preflight|start`
- 本地 lite 入口：`./scripts/launch/run_ui_local_fast_reaction.sh preflight --lite` / `./scripts/launch/run_ui_local_fast_reaction.sh start --lite`
- 本地五路 realtime 入口：`CAMERA_DEVICE=2 ./scripts/launch/run_ui_local_fast_reaction.sh preflight --realtime` / `CAMERA_DEVICE=2 ./scripts/launch/run_ui_local_fast_reaction.sh start --realtime`
- 实验性 Metal/GPU 入口：`CAMERA_DEVICE=2 ./scripts/launch/run_ui_local_fast_reaction.sh start --full-gpu`
- 权限未开时的 fallback：`./scripts/launch/run_ui_local_fast_reaction.sh start --mock-if-unavailable`
- 调试模式：`./scripts/launch/run_ui_local_fast_reaction.sh start --skip-preflight`
- CI / smoke mock 模式：`./scripts/launch/run_ui_local_fast_reaction.sh start --ci-mock`
- 本地预检脚本：`python scripts/validate/preflight_local_fast_reaction.py`
- 麦克风单独诊断：`python scripts/validate/validate_microphone_only.py`
- 五路就绪一键验收：`python scripts/validate/check_full_stack_ready.py --profile realtime --mock-if-unavailable`
- 单人互动五阶段覆盖率回归：`python scripts/validate/validate_single_user_interaction.py --duration-per-phase-sec 10 --report-json /tmp/single_user_interaction.report.json`
- 五路实时 benchmark：`CAMERA_DEVICE=2 bash scripts/validate/benchmark_local_mac_five_route.sh`
- 五路实时 benchmark（严格锁定相机索引）：`CAMERA_DEVICE=2 STRICT_CAMERA_INDEX=1 bash scripts/validate/benchmark_local_mac_five_route.sh`
- 60s 体验验证（设备不可用自动 fallback）：`python scripts/validate/validate_fast_reaction_experience.py --duration-sec 60 --config configs/runtime/local/local_mac_fast_reaction_realtime.yaml --detectors configs/detectors/local/local_mac_fast_reaction_realtime.yaml --mock-if-unavailable`
- 当前已在本机实测：
  - “权限未开启”路径文案一致
  - `preflight --lite` 与 `start --lite` 的权限已开启成功路径可用
  - `run_demo_mac.sh` 的成功路径仍待单独补一次人工确认
- Mock 快反应回归：`python scripts/validate/validate_fast_reaction_experience.py --config configs/runtime/app.default.yaml --detectors configs/detectors/local/local_mac_fast_reaction.yaml`
- 本地 stabilizer：`configs/stabilizer/local/local_mac_fast_reaction.yaml`
- 场景回放入口：`python scripts/validate/replay_arbitration_scenarios.py --scenario data/scenarios/greeting_then_gesture.json`
- 场景回放报告：`python scripts/validate/replay_arbitration_scenarios.py --scenario data/scenarios/safety_hard_interrupt.json --report-json /tmp/safety_hard_interrupt.report.json`
- Mock profile smoke：`bash scripts/validate/smoke_mock_profile.sh`
- Local Mac profile smoke：`bash scripts/validate/smoke_local_mac_profile.sh`
- Local Mac lite profile smoke：`bash scripts/validate/smoke_local_mac_lite_profile.sh`
- Local Mac realtime profile smoke：`bash scripts/validate/smoke_local_mac_realtime_profile.sh`
- Desktop 4090 profile smoke：`bash scripts/validate/smoke_desktop_4090_profile.sh`
- 统一回归入口：`bash scripts/validate/regression.sh`
- 当前主线默认启用：`face / gesture / gaze / audio / motion`
- `pose` 为实验能力：保留 adapter 与升级配置支持，但不属于默认本地 / 4090 主线 smoke

### 4090 验证

- [4090 MVP 执行 Todo](/Users/zheliu/Desktop/robot_life_dev/docs/4090_MVP_EXECUTION_TODO.md)
- [4090 验证方案](/Users/zheliu/Desktop/robot_life_dev/docs/03_validation_4090.md)
- [4090 阶段报告](/Users/zheliu/Desktop/robot_life_dev/docs/4090_STAGE_REPORT.md)
- [4090 调优 Backlog](/Users/zheliu/Desktop/robot_life_dev/docs/4090_TUNING_BACKLOG.md)
- [4090 部署指南](/Users/zheliu/Desktop/robot_life_dev/docs/ops/DEPLOYMENT_4090.md)
- [Phase 2 部署清单](/Users/zheliu/Desktop/robot_life_dev/docs/ops/PHASE2_DEPLOYMENT_CHECKLIST.md)
- [4090 快速参考](/Users/zheliu/Desktop/robot_life_dev/docs/ops/QUICK_REFERENCE.md)
- [升级指南](/Users/zheliu/Desktop/robot_life_dev/docs/ops/UPGRADE_GUIDE.md)

### 历史报告与归档

- [开源模型升级可行性报告（2026-03-30）](/Users/zheliu/Desktop/robot_life_dev/docs/reports/OPEN_SOURCE_MODEL_FEASIBILITY_2026-03-30.md)
- [Checkout 报告](/Users/zheliu/Desktop/robot_life_dev/docs/reports/CHECKOUT_REPORT.md)
- [MVP 验证总结](/Users/zheliu/Desktop/robot_life_dev/docs/reports/MVP_VALIDATION_SUMMARY.md)
- [P0 修复总结](/Users/zheliu/Desktop/robot_life_dev/docs/reports/P0_BUGFIXES_SUMMARY.md)
- [今日总结](/Users/zheliu/Desktop/robot_life_dev/docs/reports/TODAY_SUMMARY.md)
- [旧版文档索引](/Users/zheliu/Desktop/robot_life_dev/docs/archive/DOCUMENTATION_INDEX.md)
- [MVP 升级计划](/Users/zheliu/Desktop/robot_life_dev/docs/archive/MVP_UPGRADE_PLAN.md)

### 迁移与阶段计划

- [Orin NX 迁移方案](/Users/zheliu/Desktop/robot_life_dev/docs/04_migration_orin_nx.md)
- [阶段执行 Todo](/Users/zheliu/Desktop/robot_life_dev/docs/PHASE_EXECUTION_TODO_V1.md)
- [终局目标 Todo](/Users/zheliu/Desktop/robot_life_dev/docs/TERMINAL_GOAL_TODO.md)
- [终局执行 Todo](/Users/zheliu/Desktop/robot_life_dev/docs/TERMINAL_GOAL_EXECUTION_TODO_V2.md)

### 协同规范

- [快慢协同规范](/Users/zheliu/Desktop/robot_life_dev/docs/FAST_SLOW_COORDINATION_SPEC_V1.md)
- [MVP 开发检查清单](/Users/zheliu/Desktop/robot_life_dev/docs/MVP_DEVELOPMENT_CHECKLIST.md)
- [项目交接说明](/Users/zheliu/Desktop/robot_life_dev/docs/99_4090_development_handoff.md)
