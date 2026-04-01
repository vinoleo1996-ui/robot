# scripts

用于存放环境初始化、验证脚本、启动脚本和开发辅助脚本。

本地 Mac 快反应验证入口：
- `scripts/validate/preflight_local_fast_reaction.py`
- `scripts/launch/run_ui_local_fast_reaction.sh`
- `run_demo_mac.sh`（hybrid 一键入口，自动打开本地网页）
- `run_demo_mac_full_gpu.sh`（full-gpu 一键入口，自动打开本地网页）
- `scripts/validate/validate_fast_reaction_experience.py`
- `scripts/validate/validate_single_user_interaction.py`
- `scripts/validate/validate_camera_only.py`
- `scripts/validate/validate_microphone_only.py`
- `scripts/launch/run_ui_local_fast_reaction.sh start --hybrid`（五路全开 + GPU/CPU 混跑的一键入口）
- `scripts/launch/run_ui_local_fast_reaction.sh start --lite`
- `scripts/launch/run_ui_local_fast_reaction.sh start --realtime`
- `scripts/validate/benchmark_local_mac_five_route.sh`
- `scripts/validate/validate_fast_reaction_experience.py --mock-if-unavailable`（设备不可用时自动切 mock pipeline + source）
- `scripts/validate/validate_single_user_interaction.py --report-json /tmp/single_user_interaction.report.json`（单人互动五阶段覆盖率报告）
- `STRICT_CAMERA_INDEX=1 bash scripts/validate/benchmark_local_mac_five_route.sh`（锁定请求相机索引，不自动 remap）

Profile smoke 入口：
- `scripts/validate/smoke_mock_profile.sh`
- `scripts/validate/smoke_local_mac_profile.sh`
- `scripts/validate/smoke_local_mac_lite_profile.sh`
- `scripts/validate/smoke_local_mac_realtime_profile.sh`
- `scripts/validate/smoke_desktop_4090_profile.sh`

目录约定：
- `scripts/bootstrap/`：环境初始化、模型准备
- `scripts/launch/`：长驻 UI / benchmark / demo 启动入口
- `scripts/validate/`：doctor、preflight、smoke、回放、回归
- `scripts/dev/`：升级迁移和一次性开发辅助脚本
