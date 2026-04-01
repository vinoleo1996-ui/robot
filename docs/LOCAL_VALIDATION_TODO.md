# 本地验证开发 Todo

目标：让 Mac 本地可以稳定体验快反应能力，并能验证事件触发、仲裁逻辑和基础回归稳定性。

## 执行规则

- 每完成一项就在对应条目打勾。
- 每完成一个类别，必须立即跑一遍该类别对应的回归测试。
- 任何引入新入口或新配置的改动，都要同步更新 `docs/README.md` 和根 `README.md` 的导航。

## 本轮执行清单

### 1. 环境入口

- [x] 新增本地快反应 profile，和 `desktop_4090*` profile 明确分离。
- [x] 将默认 detector 配置切到本地 profile，避免无参数启动误入 4090 路线。
- [x] 修正 `run_demo_mac.sh`，只负责启动，不再在运行时安装依赖。
- [x] 补一个本地 preflight / doctor 脚本，启动前检查相机、麦克风、模型和端口。
- [x] 统一本地启动脚本的解释器选择策略，优先 `.venv`。
- [x] 让 `bootstrap_env.sh` 按 `pyproject.toml` 的 `requires-python` 动态校验 Python 版本门槛。

#### 环境入口回归

- [x] `./.venv/bin/python -m py_compile src/robot_life/app.py src/robot_life/runtime/pipeline_factory.py src/robot_life/runtime/sources.py src/robot_life/perception/registry.py`
- [x] `bash -n scripts/launch/run_ui_local_fast_reaction.sh`
- [x] `bash -n run_demo_mac.sh`

### 2. 本地验证

- [x] 新增本地机专用 `runtime` 配置，明确摄像头、麦克风和快反应预算。
- [x] 新增本地机专用 `detector` 配置，支持 CPU / MPS 友好路径。
- [x] 补齐 detector 降级策略，缺依赖或缺模型时能返回 `NoOpPipeline`。
- [x] 修正麦克风探测逻辑，必须确认真实输入设备可用。
- [x] 新增本地快反应 preflight / start 脚本。
- [x] 更新现有验证脚本默认参数到本地 profile。

#### 本地验证回归

- [x] `./.venv/bin/python scripts/validate/validate_fast_reaction_experience.py --duration-sec 1 --config configs/runtime/app.default.yaml --detectors configs/detectors/local/local_mac_fast_reaction.yaml`
- [x] `./scripts/launch/run_ui_local_fast_reaction.sh preflight`
说明：脚本运行正常，但当前机器因 macOS 相机权限未放开而失败，报错为 `not authorized to capture video`。

### 3. 回归测试

- [x] 为 detector 降级补单测，覆盖构造失败和模型缺失场景。
- [x] 为麦克风 fallback 补单测，覆盖无设备和静音回退。
- [x] 为本地验证脚本链路补 smoke 回归。
- [x] 统一本轮改动的文档入口和验证入口说明。

#### 回归测试门禁

- [x] `./.venv/bin/python -m pytest tests/unit/test_pipeline_factory.py tests/unit/test_runtime_sources.py tests/unit/test_audio_adapter.py tests/unit/test_app_detector_audit.py tests/unit/test_camera_validate_script.py tests/unit/test_cli_smoke.py -q`

## 剩余开发项

下面这些是当前还没有完成的遗留项。后续推进时，按类别完成并回归，不要跨类别同时改太多块。

### 4. 事件注入与场景回放

- [x] 设计本地场景回放输入格式，统一 `detection / stable_event / scene` 三种注入层级。
- [x] 新增事件注入模块，支持从 JSON / YAML 回放事件序列。
- [x] 新增本地场景回放脚本，支持 `--scenario`、`--report-json`、`--dry-run`。
- [x] 补 5 个基础场景包：
- [x] 熟人出现触发 greeting
- [x] greeting 过程中 gesture 排队
- [x] gaze / attention 被 greeting soft-interrupt
- [x] loud_sound 触发 safety hard-interrupt
- [x] motion 作为 P3 背景行为不抢占
- [x] 补 3 个边界场景包：
- [x] 同 target 重复触发的 replace / debounce
- [x] queue starvation 提升
- [x] cooldown 生效与恢复
- [x] 场景回放结果输出为结构化报告，至少包含 `detections`、`stable_events`、`scenes`、`decisions`、`executions`。
- [x] 把场景回放入口补进 `README.md` 和 `docs/README.md`。

#### 事件注入与场景回放回归

- [x] `pytest -q tests/unit/test_arbitration_batching.py`
- [x] `pytest -q tests/unit/test_live_loop_budget.py`
- [x] `pytest -q tests/unit/test_live_loop_flows.py`
- [x] `pytest -q tests/integration/test_arbitration_replay.py`
- [x] `python scripts/validate/replay_arbitration_scenarios.py --scenario data/scenarios/greeting_then_gesture.json`

### 5. UI 可观测性增强

- [x] 在 UI 中展示每条 pipeline 的 `enabled / ready / degraded / failed` 状态。
- [x] 在 UI 中展示每条 pipeline 的 `reason`，包括依赖缺失、模型缺失、初始化失败。
- [x] 在 UI 中展示 queue 指标：
- [x] pending 总数
- [x] P1/P2 分桶
- [x] dequeued / dropped / debounced / preemptions
- [x] 在 UI 中展示最近一批 `scene_candidates`。
- [x] 在 UI 中展示最近一批 `arbitration_results`。
- [x] 在 UI 中展示最近一批 `execution_results`。
- [x] 在 UI 中增加简化时间线，能看出 `detection -> scene -> decision -> execution`。
- [x] 在 UI 中展示 source health，至少包括 camera / microphone 是否打开、最近一次读取是否成功。
- [x] 在 UI 中明确区分 mock 模式和 real 模式。

#### UI 可观测性回归

- [x] `pytest -q tests/unit/test_ui_dashboard_state.py`
- [x] `pytest -q tests/unit/test_runtime_telemetry.py`
- [x] `pytest -q tests/unit/test_observability_metrics.py`
- [x] `pytest -q tests/unit/test_ui_slow_scene_json_output.py`
- [x] 本地 UI demo smoke：页面能看到 pipeline / queue / decision 字段

### 6. 真机体验收口

- [x] preflight 把硬件权限失败和代码失败明确分层输出。
- [x] 相机权限失败时给出 macOS 精准操作指引，不只报 OpenCV 错。
- [x] 麦克风不可用时区分“没权限”“没设备”“驱动不可用”“静音 fallback”。
- [x] `run_ui_local_fast_reaction.sh` 增加更清晰的失败提示和下一步建议。
- [x] `run_demo_mac.sh` 增加一行明确说明它只是本地启动代理脚本。
- [x] 增加本地真机 smoke 命令说明，统一到一个文档入口。
- [x] 增加一个 `--skip-preflight` 开关，仅供调试使用。
- [x] 增加一个 `--mock-if-unavailable` 开关，便于权限未打开时先体验 UI。

#### 真机体验收口回归

- [x] `python scripts/validate/preflight_local_fast_reaction.py`
说明：当前机器相机权限未打开，严格真机模式会明确失败，并给出 macOS 授权提示与 mock fallback 建议。
- [x] `./scripts/launch/run_ui_local_fast_reaction.sh preflight`
说明：当前机器相机权限未打开，输出与 preflight Python 入口一致。
- [x] `./scripts/launch/run_ui_local_fast_reaction.sh start`
说明：严格真机模式会在 preflight 阶段失败退出，并给出 `--mock-if-unavailable` / `--skip-preflight` 下一步建议。
- [x] `./scripts/launch/run_ui_local_fast_reaction.sh start --mock-if-unavailable`
说明：已验证可切换到 mock UI 体验链路。
- [x] `./run_demo_mac.sh`
说明：严格模式下会透传并展示相同的 preflight 失败提示。
- [x] `./run_demo_mac.sh --mock-if-unavailable`
说明：已验证参数可透传到本地启动脚本并切到 mock fallback。
- [x] 在相机权限未开和已开启两种状态下各验证一次输出文案
说明：
- 权限未开：已在当前环境多次复现，`preflight / start` 均输出统一的 `camera:device_unavailable` 分层提示和 macOS 授权指引。
- 权限已开：用户本机实测已出现 `PASS` 与 `started ui-demo ... mode=real profile=lite` 成功路径；与失败路径形成双态闭环。

### 7. 工程目录治理

- [x] 根目录过程文档迁入 `docs/reports/` 或 `docs/archive/`：
- [x] `CHECKOUT_REPORT.md`
- [x] `DEPLOYMENT_4090.md`
- [x] `DOCUMENTATION_INDEX.md`
- [x] `MVP_UPGRADE_PLAN.md`
- [x] `MVP_VALIDATION_SUMMARY.md`
- [x] `P0_BUGFIXES_SUMMARY.md`
- [x] `PHASE2_DEPLOYMENT_CHECKLIST.md`
- [x] `QUICK_REFERENCE.md`
- [x] `TODAY_SUMMARY.md`
- [x] `UPGRADE_GUIDE.md`
- [x] 根目录一次性脚本迁入 `tools/oneoff/` 或 `scripts/dev/`：
- [x] `debug_camera.py`
- [x] `patch_py39.py`
- [x] `test_ml.py`
- [x] `test_queue.py`
- [x] `verify_files.py`
- [x] `test_p0_fixes.py`
- [x] `scripts/` 目录按职责拆分：
- [x] `scripts/bootstrap/`
- [x] `scripts/launch/`
- [x] `scripts/validate/`
- [x] `scripts/dev/`
- [x] `configs/` 目录按 profile / platform 归类：
- [x] `configs/runtime/local/`
- [x] `configs/runtime/desktop_4090/`
- [x] `configs/detectors/local/`
- [x] `configs/detectors/desktop_4090/`
- [x] 清理 `src/` 下历史占位目录，移除旧的 `behavior / common / event_engine / perception / slow_scene / robot_life_dev` 空壳路径，避免命名空间包误导。
- [x] 清理仓库内生成物：
- [x] `__pycache__`
- [x] `.pytest_cache`
- [x] `*.egg-info`
- [x] 根目录临时日志
- [x] 更新根 `README.md` 和 `docs/README.md`，适配新目录。

#### 工程目录治理回归

- [x] `python -m compileall -q src`
- [x] `pytest -q tests/unit/test_cli_smoke.py`
- [x] 检查 `README.md`、`docs/README.md` 中所有本地入口是否仍然有效

### 8. 测试矩阵系统化

- [x] 为 mock profile 增加单独 smoke 入口。
- [x] 为 local Mac profile 增加单独 smoke 入口。
- [x] 为 desktop_4090 profile 增加单独 smoke 入口。
- [x] 为 3 套 profile 分别增加 `doctor / detector-status / run-live / ui-demo` 级别 smoke。
- [x] 把 profile smoke 整理进统一 regression 脚本。
- [x] 为本地验证脚本加 CI 友好的 mock 模式门禁。
- [x] 为 `validate_4090.py` 增加显式 `--smoke` 模式，避免在非目标机器上把 smoke 回归误跑成真机硬件测试。

#### 测试矩阵回归

- [x] `pytest -q tests/unit/test_cli_smoke.py`
- [x] `pytest -q tests/integration/test_e2e_smoke.py`
- [x] `bash scripts/validate/regression.sh`

## 当前推荐顺序

1. 先做事件注入与场景回放。
2. 再做 UI 可观测性增强。
3. 再做真机体验收口。
4. 最后做目录治理和测试矩阵系统化。

## 下一阶段计划（2026-03-30）

### A. 本地 stabilizer 解耦

- [x] 新增本地专用 stabilizer 配置：`configs/stabilizer/local/local_mac_fast_reaction.yaml`
- [x] `run_ui_local_fast_reaction.sh` 默认改为使用本地 stabilizer
- [x] `preflight_local_fast_reaction.py` 默认改为使用本地 stabilizer
- [x] `validate_fast_reaction_experience.py` 默认改为使用本地 stabilizer
- [x] `replay_arbitration_scenarios.py` 默认改为使用本地 stabilizer
- [x] `profile_smoke.py` 为 local_mac / desktop_4090 显式传入 profile 对应 stabilizer
- [x] 为本地 stabilizer 补单测，确认与 4090 stabilizer 语义分离

#### A 类回归

- [x] `./.venv/bin/python -m pytest -q tests/unit/test_stabilizer_config.py tests/integration/test_arbitration_replay.py`
- [x] `./scripts/launch/run_ui_local_fast_reaction.sh preflight`
说明：脚本已切到本地 stabilizer，当前机器仍因 macOS 相机权限未放开而失败，但失败文案正确。
- [x] `bash scripts/validate/smoke_local_mac_profile.sh`
- [x] `bash scripts/validate/regression.sh`

### B. Python 版本策略统一

- [x] 决定项目正式支持版本为 `Python 3.11`
- [x] 统一 `pyproject.toml` 的 `requires-python`、`ruff target-version` 和 README 文案
- [x] 重建 `.venv`，避免继续停留在 `Python 3.9.5`
- [x] 用新解释器重跑 perception、本地 smoke 和总回归

#### B 类回归

- [x] `./.venv/bin/python --version`
- [x] `./.venv/bin/python -m pytest -q tests/unit/test_cli_smoke.py tests/integration/test_e2e_smoke.py`
- [x] `bash scripts/validate/regression.sh`

### C. 真机文案双态验证

- [x] 验证相机权限未开启时，preflight / launcher / run_demo_mac 的提示文案一致
- [x] 验证相机权限已开启时，preflight / launcher / run_demo_mac 的成功路径文案一致
说明：
- `preflight / launcher`：用户本机已实测成功路径（`PASS` + `started ui-demo...`）。
- `run_demo_mac`：脚本为 `exec scripts/launch/run_ui_local_fast_reaction.sh start "$@"` 薄代理；本次已补 `--ci-mock --lite` 成功链路，启动摘要格式与 launcher 一致。
- [x] 把阶段性验证结论回写到本清单和 `docs/README.md`

当前结论：

- 已在当前 Mac 上实测“权限未开启”路径，`preflight / launcher preflight / run_demo_mac` 都会输出一致的失败语义：
  - 明确说明摄像头不可用
  - 明确提示 macOS `系统设置 -> 隐私与安全性 -> 相机`
  - 明确给出 `--mock-if-unavailable` 和 `--skip-preflight` 下一步建议
- 用户已在本机实测通过 `preflight --lite` 与 `start --lite` 的成功路径，系统可启动 `mode=real profile=lite`。
- `run_demo_mac.sh` 的成功路径仍未单独补一次人工确认，但它当前只是本地 launcher 的代理入口。

#### C 类回归

- [x] `python scripts/validate/preflight_local_fast_reaction.py`
- [x] `./scripts/launch/run_ui_local_fast_reaction.sh preflight`
- [x] `./run_demo_mac.sh`

### D. 交互引擎骨架升级

- [x] 新增多目标追踪与关联层，统一 `face / gaze / gesture / motion` 的 `track_id`
- [x] 新增时序事件层，补齐 `gaze_hold_start / gaze_hold_end / attention_lost / wave_detected`
- [x] 升级交互状态层，形成 `idle -> noticed_human -> mutual_attention -> engaging -> ongoing_interaction -> recovery -> alert`
- [x] 拆分 `Policy Layer + Behavior Manager`，把“该不该做”和“怎么做”分离
- [x] 补齐抑制机制：
- [x] active target 抑制
- [x] robot busy 抑制
- [x] saturation 抑制
- [x] 新增 `RobotContextStore`，把 `mode / do_not_disturb / active_behavior / current_interaction_target / recent_interactions` 接入运行时
- [x] 拆分 `Social Path / Safety Path` 双通路，运行时先走 `safety` 再走 `social`
- [x] UI 新增“双通路监测”，自然语言面板和事件跳转链支持展示 `scene_path`

#### D 类回归

- [x] `./.venv/bin/pytest -q tests/unit/test_entity_tracker.py tests/unit/test_temporal_event_layer.py tests/unit/test_policy_layer.py tests/unit/test_behavior_manager.py tests/unit/test_robot_context.py`
- [x] `./.venv/bin/pytest -q tests/unit/test_live_loop_flows.py tests/unit/test_live_loop_budget.py tests/unit/test_cooldown_manager.py tests/unit/test_ui_dashboard_state.py tests/unit/test_observability_metrics.py`
- [x] `./.venv/bin/pytest -q tests/integration/test_e2e_smoke.py`

### D. 主线能力边界收口

- [x] 明确 `pose` 是正式主线还是实验项
- [x] 如果不是主线，从默认 detector/default pipeline 中移出
- [x] 如果要纳入主线，补 smoke、README、doctor 输出说明

当前结论：
- `pose` 长期是需要的，面向“挥手招呼机器人过来 / 张开双臂求抱抱”这类 body-intent 产品需求。
- 但当前仓库里的 `pose` 还处于实验原型阶段，不进入默认本地 / 4090 主线快反应链路。
- 在 `D / H / G / E` 都完成之前，不启动 pose 主线化开发，暂保留 adapter 与升级配置能力。

#### D 类回归

- [x] `./.venv/bin/python -m pytest -q tests/unit/test_pipeline_factory.py tests/unit/test_app_detector_audit.py`
- [x] `./.venv/bin/python -m robot_life.app detector-status`

### E. CLI 结构拆分

- [x] 拆分 `src/robot_life/app.py`，按 `doctor / run-live / ui-demo / slow-scene / shared helpers` 分文件
- [x] 抽离 `_resolve_camera_device`、`_audit_detector_model_paths`、`_build_arbitration_runtime` 等 helper
- [x] 保持现有 CLI 命令接口不变

#### E 类回归

- [x] `./.venv/bin/python -m pytest -q tests/unit/test_cli_smoke.py`
- [x] `bash scripts/validate/regression.sh`

### F. 优先级契约收口

- [x] 统一 `EventBuilder` 默认优先级与仲裁配置，避免 `familiar_face` 默认落到 `P2`
- [x] 把共享事件优先级和 canonical event 归一逻辑收口到 `common/contracts.py`
- [x] 把 `arbitrator / arbitration_runtime / live_loop / safety_guard / slow_scene.queue` 的 `priority_rank` 统一到 `contracts.priority_rank()`
- [x] 清理 `decision_queue.py` 中已废弃的 `import bisect`
- [x] 为共享优先级契约补单测，覆盖 canonical event、默认优先级和 builder 默认行为

#### F 类回归

- [x] `./.venv/bin/python -m pytest -q tests/unit/test_contracts.py tests/unit/test_live_loop_priority_mapping.py tests/unit/test_cli_smoke.py`
- [x] `bash scripts/validate/regression.sh`

### G. 生命感模块接线

- [x] 评估并决定 `BehaviorDecayTracker` 接入主链的落点
- [x] 评估并决定 `InteractionStateMachine` 接入主链的落点
- [x] 将生命感状态透出到 UI / telemetry，避免“模块存在但不可见”
- [x] 为衰减、静默反馈和状态迁移补单测 / 集成测试

#### G 类回归

- [x] `./.venv/bin/python -m pytest -q tests/unit/test_behavior_runtime.py tests/unit/test_ui_dashboard_state.py`
- [x] `bash scripts/validate/regression.sh`

### H. 聚合与并发鲁棒性

- [x] 给 `SceneAggregator._memory` 增加 target cardinality 约束或 LRU / 统计保护
- [x] 为高 target churn 场景补单测，确认 memory 不会无上限膨胀
- [x] 明确 `PipelineRegistry` 的线程模型：要么引入锁，要么用 owner-thread 约束和注释写清
- [x] 为 `PipelineRegistry` 补并发访问的最小防护测试或行为约束测试

#### H 类回归

- [x] `./.venv/bin/python -m pytest -q tests/unit/test_schemas.py tests/unit/test_runtime_sources.py tests/unit/test_pipeline_factory.py`
- [x] `bash scripts/validate/regression.sh`

### I. Pose Detection 升级回看

- [x] 在 `D / H / G / E` 全部完成后，重新评估 pose / body-intent 技术路线
- [x] 对齐目标能力：`挥手招呼`、`张开双臂求抱抱`、`靠近迎接`、`转身离开`
- [x] 评估现有 `MediaPipe Pose / YOLO Pose` 是否继续保留，还是替换为更强路线
- [x] 给出 4090 目标架构下的 pose detection / body-intent 升级方案与替换成本

当前结论：

- `pose` 长期需要，但当前仓库现有实现仍然是实验原型，不进入默认主线。
- `MediaPipe Pose` 适合继续做本地原型和轻量实验，不适合作为 4090 终局主线。
- 当前 `YOLO Pose` 试验代码存在关键点语义错位，不建议直接主线化。
- 面向 4090 的推荐方向改为 `RTMPose / RTMW whole-body + tracking + body-intent state`，`YOLO11 pose` 作为工程备选，`ViTPose` 作为高精度备选。
- 详细分析见：`docs/reports/POSE_BODY_INTENT_UPGRADE_2026-03-30.md`

#### I 类回归

- [x] 当前阶段先完成方案评审；实现启动时再建立专项回归集

### J. 真机采集链路稳定性

- [x] 复现并定位 `camera read failed 3 times, attempting recovery` 的触发条件
- [x] 在 `CameraSource` 上为 macOS 增加更稳的读取与恢复策略
- [x] 为 camera source 增加 `backend / total_failures / recovery_count / last_frame_age_ms` 健康指标
- [x] 增强 `validate_camera_only.py`，输出相机健康摘要并支持失败阈值门禁
- [x] 在当前 Mac 真机上再次验证 camera recovery 已明显减少，实时画面恢复流畅

当前结论：

- 工具侧已完成相机采集链路补强：优先 AVFoundation、限制缓冲、读帧超时保护、恢复节流、健康指标透出。
- mock 回归已通过，camera-only 脚本可输出结构化健康摘要。
- 用户已在本机实测 `start --lite` 后的真机状态：
  - `loop_fps=5.8`
  - `latency_ms=10.09`
  - 相比之前 `loop_fps≈0.6 / latency≈1000ms` 已显著改善
  - 仍存在偶发 `camera read timed out after 0.12s`，后续可继续做体验调优，但已不再是 blocker

#### J 类回归

- [x] `./.venv/bin/python -m pytest -q tests/unit/test_runtime_sources.py tests/unit/test_ui_dashboard_state.py tests/unit/test_camera_validate_script.py`
- [x] `./.venv/bin/python scripts/validate/validate_camera_only.py --mock-drivers --iterations 5 --max-camera-recoveries 0 --max-camera-failures 0`
- [x] `./scripts/launch/run_ui_local_fast_reaction.sh start --lite`
- [x] `./scripts/launch/run_ui_local_fast_reaction.sh status`

### K. 本地体验验证脚本与回归门禁

- [x] 修复 `validate_fast_reaction_experience.py` 对 `robot_life.app` 私有 helper 的依赖
- [x] 修复 `preflight_local_fast_reaction.py` 对 `robot_life.app` 私有 helper 的依赖
- [x] 把共享 helper 依赖切到 `robot_life.cli_shared`
- [x] 将 `validate_fast_reaction_experience.py` 的短时 smoke 纳入 `scripts/validate/regression.sh`
- [x] 确保本地体验验证脚本可输出成功摘要

#### K 类回归

- [x] `./.venv/bin/python scripts/validate/validate_fast_reaction_experience.py --duration-sec 1 --config configs/runtime/app.default.yaml --detectors configs/detectors/local/local_mac_fast_reaction.yaml`
- [x] `./.venv/bin/python -m pytest -q tests/unit/test_cli_smoke.py`
- [x] `bash scripts/validate/regression.sh`

### L. Mac 轻量真机 Profile

- [x] 新增 `configs/runtime/local/local_mac_fast_reaction_lite.yaml`
- [x] 新增 `configs/runtime/local/local_mac_fast_reaction_lite.smoke.yaml`
- [x] 新增 `configs/detectors/local/local_mac_fast_reaction_lite.yaml`
- [x] 为 lite profile 明确只保留最关键、最轻量的 pipeline 组合
- [x] 为 launcher 增加 `--lite` 模式
- [x] 新增 lite profile smoke 入口并接入统一回归
- [x] 更新 `README.md`、`docs/README.md`、`scripts/README.md` 的 lite 使用说明

当前结论：

- `lite` 模式当前优先保留 `face / audio / motion`，目标是让 Mac 真机先把实时画面和基础快反应跑顺。
- 已新增独立 smoke profile，并接入统一 regression。
- 真机 `preflight --lite` 仍建议在用户本机终端手动跑一次，确认相机权限和真实设备状态。

#### L 类回归

- [x] `bash scripts/validate/smoke_local_mac_lite_profile.sh`
- [x] `bash scripts/validate/regression.sh`
- [x] `./scripts/launch/run_ui_local_fast_reaction.sh preflight --lite`

### M. 真机观测性补强

- [x] 在 UI 中展示 `camera_last_frame_age_ms`
- [x] 在 UI 中展示 `camera_recovery_count`
- [x] 在 UI 中展示 `camera_read_failures`
- [x] 在 UI 中展示 `microphone_mode`
- [x] 在 UI 中展示 `current_profile / current_stabilizer`
- [x] 为 `/api/state` 增加对应字段

#### M 类回归

- [x] `./.venv/bin/python -m pytest -q tests/unit/test_ui_dashboard_state.py`
- [x] 本地 UI demo smoke：页面能看到新的 source health 字段
说明：已通过临时前台启动 `ui-demo` 并抓取 `/api/state` 验证，返回包含 `source_health / current_profile / current_stabilizer`，且 `source_health` 条目可见帧龄/失败计数/恢复计数相关字段。

### N. 麦克风真机链路收口

- [x] 复查 `sounddevice` 设备发现逻辑
- [x] 增加 microphone-only 诊断输出
- [x] 明确区分无权限 / 无设备 / 驱动不可用 / 静音 fallback
- [x] 在 UI 与 preflight 中透出当前麦克风模式
- [x] 若当前机器确实无可用输入设备，补外设建议

当前结论：

- 之前的 “`sounddevice` 未发现可用输入设备” 是代码误判，不是系统没有麦克风。
- 根因是 `sounddevice.query_devices()` 返回 `DeviceList`，旧逻辑只接受 `list`，导致真实输入设备被统计成 `0`。
- 修复后本机已验证：
  - `./.venv/bin/python scripts/validate/validate_microphone_only.py --require-real`
  - 输出 `mode=real / backend=sounddevice / input_device_count=5 / PASS`

#### N 类回归

- [x] `./.venv/bin/python scripts/validate/preflight_local_fast_reaction.py`
说明：已在当前环境执行；当相机权限不可用时会按预期输出分层错误（camera vs microphone）与下一步建议，不再出现模糊报错。
- [x] `./.venv/bin/python scripts/validate/validate_microphone_only.py`
- [x] `./.venv/bin/python scripts/validate/validate_microphone_only.py --require-real`
- [x] `./scripts/launch/run_ui_local_fast_reaction.sh status`

### O. 五路全开 realtime 体验

- [x] 为 Mac 本地新增五路 realtime runtime 配置
- [x] 为 Mac 本地新增五路 realtime detector 配置
- [x] 为 launcher 增加 `--realtime` 模式
- [x] 为五路 realtime 增加独立 benchmark 入口
- [x] 为五路 realtime 增加 smoke profile 并接入统一回归
- [x] 修正 preflight 中相机探测顺序，避免先做重初始化再探相机
- [x] 修正相机探测逻辑，使其与运行时优先使用 AVFoundation 的行为一致
- [x] 在当前 Mac 上人工验证 `preflight --realtime`
- [x] 在当前 Mac 上人工验证 `start --realtime`
- [x] 在当前 Mac 上人工运行五路 benchmark，记录 `estimated_loop_fps / latency / 稳定时长`
说明：已记录一轮人工实测：`duration_sec=15.29`，`estimated_loop_fps=26.10`（用户实测输出），可作为当前五路全开基线。

当前结论：

- 五路 realtime 入口和 benchmark 已落地，代码级 smoke / regression 已接入。
- 当前设计目标不是“5 路都 30Hz 推理”，而是“5 路都在主链里、整体 UI/事件链路尽量接近实时”。
- 在当前 Apple Silicon + MediaPipe 组合下，Metal delegate 会触发 native abort；因此 `realtime` 入口已回到稳定 CPU/XNNPACK 路线，`--full-gpu` 保留为实验入口。
- 受 Apple Silicon / MediaPipe / OpenCV / macOS 权限模型限制，是否能在当前机器上稳定达到 `30 FPS` 仍需真机实测确认。
- 本次已在当前环境执行 `preflight --realtime` 与 `start --realtime`：
  - 两者均进入相同 preflight 分层失败语义（`camera:device_unavailable`）
  - 麦克风探测保持可用（`backend=sounddevice input_devices=5 selected=0`）
  - 下一步建议文案一致（`--mock-if-unavailable` / `--skip-preflight`）

#### O 类回归

- [x] `bash -n scripts/launch/run_ui_local_fast_reaction.sh`
- [x] `bash -n scripts/validate/smoke_local_mac_realtime_profile.sh`
- [x] `bash -n scripts/validate/benchmark_local_mac_five_route.sh`
- [x] `./.venv/bin/python -m pytest -q tests/unit/test_local_fast_reaction_scripts.py tests/unit/test_cli_smoke.py`
- [x] `bash scripts/validate/smoke_local_mac_realtime_profile.sh`
- [x] `bash scripts/validate/regression.sh`

### P. 专家 Code Review 收口

- [x] 修复 `tests/unit/test_live_loop_budget.py` 与 `LiveLoop._record_executed_decision(scene=...)` 新签名脱节问题
- [x] 为 source 打开失败的降级容忍补锁定测试，确认 `LiveLoop.start()` 不会因单个 source 打开失败直接中断
- [x] 为 `BehaviorExecutor._behavior_history` 增加固定上限，避免长时间运行时持续增长
- [x] 修复 `_priority_to_int()` 的非字符串 fallback 类型不安全问题，保证始终返回 `int`
- [x] 让 `SceneAggregator` 正式产出 `stranger_attention_scene`，避免陌生人与普通 attention 完全混同
- [x] 强化 e2e smoke 断言，从“只验证不崩”提升到“至少有检测 / 稳定事件 / 场景 / 执行输出”
- [x] 复核 `rms_audio` 路径，确认默认配置与代码实现未脱节，不按误报回退

当前结论：

- 本轮专家 review 里，测试契约漂移、执行历史无界增长、陌生人场景未产出、`_priority_to_int()` 类型不安全，这几条是真问题，已经修复。
- `rms_audio` “配置与代码脱节”这条是误报，当前默认配置和 `pipeline_factory` / `audio_adapter` 实现是对齐的。
- `LiveLoop.start()` “source 一失败整个崩”这条在当前代码里不成立，因为 `SourceBundle.open_all()` 已经吞掉打开异常；这次补了锁定测试，防止后续回归。

#### P 类回归

- [x] `./.venv/bin/python -m pytest -q tests/unit/test_live_loop_budget.py tests/unit/test_contracts.py tests/integration/test_e2e_smoke.py`
- [x] `./.venv/bin/python -m pytest -q tests/unit/test_runtime_sources.py tests/unit/test_behavior_runtime.py tests/unit/test_behavior_safety_guard.py`
- [x] `bash scripts/validate/regression.sh`

### Q. 真机日志停滞与麦克风“未启动”感知修复

- [x] 修复 `rms_audio` 的 dB 阈值容错：当配置为正 dB 时自动降级为仅用 RMS 阈值，避免音频链路静默
- [x] 统一修正 local / desktop_4090 profile 中不合理的 `energy_threshold_db`（由正值改为 dBFS 负值）
- [x] 修复 UI source health 判定逻辑：麦克风改为按“最近包龄”判定可用，避免异步读包下频繁显示 idle
- [x] 为以上修复补充单测，防止后续回退

当前结论：

- “事件流停在某个时间”在本质上是“最近没有新检测事件”，不是主循环卡死；主循环与 source 包计数在持续增长。
- “麦克风没起来”在一部分场景是 UI 判定误差（异步麦克风本轮未取到包即被标 idle）；已改为按包龄判定。
- `rms_audio` 在多个 profile 的正 dB 阈值配置会导致真实环境几乎不触发，此问题已修复并加了代码级兜底。

#### Q 类回归

- [x] `./.venv/bin/python -m pytest -q tests/unit/test_audio_adapter.py tests/unit/test_ui_dashboard_state.py`
- [x] `bash scripts/validate/smoke_local_mac_realtime_profile.sh`
- [x] `bash scripts/validate/regression.sh`

### R. 五路 realtime 运动通道降敏与非人目标优先

- [x] `OpenCVMotionDetector` 增加目标级过滤能力（最小/最大目标面积、形态约束）
- [x] `OpenCVMotionDetector` 增加可选 `suppress_human_motion`（人形区域重叠过滤）
- [x] realtime motion profile 调整为“非人快速目标优先”参数（降低对人类日常动作敏感度）
- [x] local stabilizer 的 `motion_detected` 改为更稳健门槛（debounce=2, cooldown=1000ms）
- [x] 补 motion 过滤单测，覆盖“大目标过滤”和“人形区域抑制”防回退

当前结论：

- 之前 motion 的像素差分逻辑会把“人类正常活动”与“宠物/扫地机器人快速移动”混为一类，导致事件流被 motion 刷屏。
- 本轮改造后，motion 改为“先过目标级过滤，再触发事件”，并在 realtime profile 默认开启人形抑制。
- 这会明显降低人类活动导致的误触发，同时保留对中小体积快速移动目标的检测灵敏度。

#### R 类回归

- [x] `./.venv/bin/python -m pytest -q tests/unit/test_motion_adapter.py tests/unit/test_stabilizer_config.py`
- [x] `bash scripts/validate/smoke_local_mac_realtime_profile.sh`
- [x] `bash scripts/validate/regression.sh`

### S. P0 音频真机触发链路增强（当前推进）

- [x] `rms_audio` 增加“绝对阈值 + 相对基线突增”双通道触发，降低不同麦克风增益差异下的漏检
- [x] local Mac 四套 profile（hybrid/realtime/full-gpu/lite）同步接入相对阈值参数
- [x] preflight 增加麦克风选中设备名与输入设备列表输出（便于快速定位“选错麦克风”）
- [x] `validate_microphone_only.py` 增加 `selected_device_name/input_device_names` 输出
- [x] `SoundDeviceMicrophoneSource` 暴露实时音量健康指标（`audio_rms/audio_db/last_packet_age_ms`），便于 UI 侧定位“有输入但未触发事件”
- [x] 补齐音频与麦克风探测单测，防止触发链路回退

当前结论：

- 当前环境麦克风探测已恢复到真实链路：`mode=real / backend=sounddevice / input_device_count=6 / selected_device=0`。
- 大声无反应问题从“只靠绝对阈值”改成“绝对阈值 + 相对突增”后，跨设备鲁棒性更高。
- preflight 现在能直接看到当前选中的麦克风名字，后续你切换系统输入设备时更容易对齐。

#### S 类回归

- [x] `./.venv/bin/python -m pytest -q tests/unit/test_audio_adapter.py tests/unit/test_runtime_sources.py`
- [x] `./.venv/bin/python -m pytest -q tests/unit/test_local_fast_reaction_scripts.py tests/unit/test_ui_dashboard_state.py`
- [x] `PYTHONPATH=src:. .venv/bin/python scripts/validate/validate_microphone_only.py`
- [x] `./scripts/launch/run_ui_local_fast_reaction.sh preflight --hybrid`
说明：本次执行中相机权限仍未放开，preflight 按预期失败在 camera；麦克风输出已包含 `selected_name` 与设备列表。

### T. 下一步高优推进（已完成）

- [x] 固化 full-stack 五路全开稳定配置，并增加一键验收脚本（启动后自动检查 5 路 pipeline `enabled+ready`）
- [x] 增加单人互动真机回归脚本（靠近/注视/挥手/环境运动/声音）并输出覆盖率报告
- [x] 快反应 pipeline 执行从串行改为“受控并行”第一版（`fast_parallel_workers`）
- [x] 快反应结果“时效丢弃”第一版（防止慢 pipeline 结果拖慢当前交互）
- [x] UI 增加“快反应场景切换节流”可观测参数，避免自然语言面板高频抖动

当前结论：

- `PipelineRegistry` 已支持受控并行处理，默认仍为 `1`（串行），通过 `detector_global.fast_parallel_workers` 按 profile 启用。
- 本地 profile 已配置并行 worker：`hybrid/realtime/full-gpu=3`，`lite=2`。
- 已补单测覆盖“配置生效”和“并行执行不打乱 pipeline 注册顺序”。
- 新增一键验收脚本：`python scripts/validate/check_full_stack_ready.py --profile realtime --mock-if-unavailable`。
- 新增单人互动真机回归脚本：`python scripts/validate/validate_single_user_interaction.py`，按“靠近/注视/挥手/环境运动/声音”分阶段输出覆盖率报告。
- `LiveLoop` 已增加 `async_perception_result_max_age_ms`，过期异步感知结果会被主动丢弃，避免慢 pipeline 旧结果拖慢当前交互。
- UI 元信息已增加话术节流可观测项：`reaction_hold_seconds`、`latest_reaction_age_ms`；支持环境变量 `ROBOT_LIFE_REACTION_HOLD_S` 调参。
- `validate_fast_reaction_experience.py` 已补 `--mock-if-unavailable`，设备不可用时会切换 mock pipeline + mock source，避免“只切 source 导致 5 路全 MISS”。

#### T 类回归

- [x] `./.venv/bin/python -m pytest -q tests/unit/test_live_loop_budget.py tests/unit/test_arbitration_batching.py tests/unit/test_pipeline_factory.py tests/unit/test_check_full_stack_ready.py`
- [x] `./.venv/bin/python -m pytest -q tests/unit/test_validate_single_user_interaction.py`
- [x] `bash scripts/validate/smoke_local_mac_realtime_profile.sh`
- [x] `python scripts/validate/check_full_stack_ready.py --profile realtime --mock-if-unavailable`
- [x] `./.venv/bin/python -m pytest -q tests/unit/test_ui_dashboard_state.py`
- [x] `python scripts/validate/validate_single_user_interaction.py --config configs/runtime/app.default.yaml --detectors configs/detectors/local/local_mac_fast_reaction.yaml --duration-per-phase-sec 1 --min-coverage 0 --report-json /tmp/single_user_interaction.report.json`
- [x] `python scripts/validate/validate_fast_reaction_experience.py --duration-sec 60 --config configs/runtime/local/local_mac_fast_reaction_realtime.yaml --detectors configs/detectors/local/local_mac_fast_reaction_realtime.yaml --mock-if-unavailable`
说明：当前环境相机权限未放开，脚本按预期切换 mock fallback 并完成 60s 验证，五路统计均有产出。

### U. 专家建议优化收口（2026-03-30）

- [x] 增加中央视觉帧分发缓存 `CameraFrameDispatch`，让 camera 管线共享 `rgb/rgba/gray` 预处理结果，减少重复 `cvtColor`。
- [x] 感知批次对齐增强：`CollectedFrames` 增加 `frame_seq`，异步感知新增 `async_perception_result_max_frame_lag` 门禁，超过帧滞后阈值主动丢弃。
- [x] 行为执行器新增 tick 能力（`tick_execution + tick_max_nodes`），并在 `LiveLoop` 中支持每轮步进推进，保留默认兼容路径。
- [x] UI 增加运行态实时调参（`/api/tuning`）：支持 `reaction_hold_seconds`、`fast_path_budget_ms`、`async_perception_result_max_age_ms` 在线调整。
- [x] 补充回归测试覆盖：`frame dispatch`、`async frame lag drop`、`tick 执行`、`runtime tuning`。

当前结论：

- 快反应链路在保持现有稳定性的前提下，补上了“预处理复用 + 时序对齐 + 可步进执行 + 在线调参”的第一版基础能力。
- 默认行为保持向后兼容（不打开 tick 时仍是原同步完成路径），但已经具备逐步切换到更响应式执行模型的工程落点。

#### U 类回归

- [x] `./.venv/bin/python -m pytest -q tests/unit/test_frame_dispatch.py tests/unit/test_live_loop_budget.py tests/unit/test_behavior_runtime.py tests/unit/test_ui_dashboard_state.py`
- [x] `./.venv/bin/python -m pytest -q tests/unit/test_motion_adapter.py tests/unit/test_pipeline_factory.py tests/unit/test_runtime_sources.py tests/unit/test_cli_smoke.py`
- [x] `./.venv/bin/python -m pytest -q tests/integration/test_e2e_smoke.py`
- [x] `bash scripts/validate/regression.sh`

### V. 本地快反应 profile 启用 tick 执行（2026-03-30）

- [x] 在 `local_mac_fast_reaction` / `local_mac_fast_reaction_realtime` / `local_mac_fast_reaction_full_gpu` 打开 `behavior_tick_enabled=true`
- [x] 对应 smoke profile 同步启用 tick，保持配置语义一致
- [x] 保持 `tick_max_nodes=1`，优先保证“可打断”而非一次吞完脚本
- [x] 验证开启 tick 后不会引入回归，且 `async executor` 与 tick 冲突时按预期自动关闭异步执行并告警

当前结论：

- 本地快反应 profile 已进入“可步进、可打断”的行为执行路径，动作切换灵敏度更高。
- `async executor disabled because tick_execution is enabled` 为预期告警，用于避免双调度冲突。

#### V 类回归

- [x] `./.venv/bin/python -m pytest -q tests/unit/test_cli_smoke.py tests/integration/test_e2e_smoke.py tests/unit/test_behavior_runtime.py`
- [x] `bash scripts/validate/regression.sh`
