# 4090 MVP 真机验证配置与执行清单

## P0 必做（先完成）

- [x] 确认 `configs/runtime/desktop_4090/desktop_4090.yaml` 启用真机模式（`runtime.mock_drivers: false`）。
- [x] 确认 `runtime.enabled_pipelines` 默认开启 `face/gesture/gaze/audio/motion` 五类管线。
- [x] 在 4090 主机接入 USB 摄像头并确认系统可识别（探测到 index `5` 可稳定取帧）。
- [x] 执行 `python3 scripts/validate/validate_camera_only.py --config configs/runtime/desktop_4090/desktop_4090.yaml --iterations 10 --camera-device-index 5`。
- [x] 校验脚本输出为 `PASS` 且进程返回码为 `0`。

## P1 建议（主链路联调）

- [x] 执行 `python3 scripts/validate/validate_4090.py --config configs/runtime/desktop_4090/desktop_4090.yaml --iterations 120 --camera-device-index 5` 做主链路健康检查。
- [x] 执行 `python3 scripts/validate/validate_ux.py --config configs/runtime/desktop_4090/desktop_4090.yaml --duration-sec 600 --camera-device-index 5` 做体验稳定性检查。
- [x] 若校验失败，记录失败项（摄像头打开失败、frame 不足、延迟超预算、重复触发过多）并回填到 issue/TODO。（本轮 `PASS`，无新增失败项）

## P2 收尾（回归与交付）

- [x] 在 CI/本地执行 `pytest -q tests/unit/test_camera_validate_script.py`，确认 mock smoke 稳定通过。
- [x] 汇总本轮真机验证结果（命令、参数、时间、返回码、结论）写入阶段报告（`docs/4090_STAGE_REPORT.md`）。
- [x] 输出下一轮调优清单（采样率、冷却参数、慢思考触发阈值、资源占用目标）（`docs/4090_TUNING_BACKLOG.md`）。
