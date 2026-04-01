#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_SRC = PROJECT_ROOT / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from robot_life.cli_shared import _resolve_camera_device
from robot_life.common.config import (
    load_app_config,
    load_arbitration_config,
    load_safety_config,
    load_stabilizer_config,
)
from robot_life.runtime import (
    build_pipeline_registry,
    load_detector_config,
    microphone_source_options_from_detector_cfg,
    probe_live_microphone_source,
)


DEFAULT_RUNTIME_CONFIG = PROJECT_ROOT / "configs" / "runtime" / "local" / "local_mac_fast_reaction.yaml"
DEFAULT_DETECTOR_CONFIG = PROJECT_ROOT / "configs" / "detectors" / "local" / "local_mac_fast_reaction.yaml"
DEFAULT_ARBITRATION_CONFIG = PROJECT_ROOT / "configs" / "arbitration" / "default.yaml"
DEFAULT_STABILIZER_CONFIG = (
    PROJECT_ROOT / "configs" / "stabilizer" / "local" / "local_mac_fast_reaction.yaml"
)
DEFAULT_SAFETY_CONFIG = PROJECT_ROOT / "configs" / "safety" / "default.yaml"


@dataclass
class PreflightIssue:
    scope: str
    code: str
    message: str
    hint: str
    mock_compatible: bool = False


def _validate_files(paths: list[Path]) -> list[PreflightIssue]:
    issues: list[PreflightIssue] = []
    for path in paths:
        if not path.exists():
            issues.append(
                PreflightIssue(
                    scope="config",
                    code="missing_file",
                    message=f"缺少文件: {path}",
                    hint="先运行 scripts/bootstrap/bootstrap_env.sh，确认配置和模型资产都已准备好。",
                    mock_compatible=False,
                )
            )
    return issues


def _camera_issue(message: str) -> PreflightIssue:
    normalized = message.lower()
    if "not authorized" in normalized or "permission" in normalized:
        return PreflightIssue(
            scope="camera",
            code="permission_denied",
            message=message,
            hint=(
                "请在 macOS 打开“系统设置 -> 隐私与安全性 -> 相机”，"
                "给当前终端应用（Terminal / iTerm / Codex）相机权限，然后完全重启终端后重试。"
            ),
            mock_compatible=True,
        )
    if "未找到可用摄像头设备" in message or "failed to open camera" in normalized:
        if sys.platform == "darwin":
            hint = (
                "在 macOS 上，这通常同时意味着相机权限未打开。请先去“系统设置 -> 隐私与安全性 -> 相机”"
                "给当前终端授权；如果仍失败，再检查是否有其它应用正在占用摄像头。"
            )
        else:
            hint = "确认本机摄像头可用、未被其它应用独占，并检查 CAMERA_DEVICE 是否设置正确。"
        return PreflightIssue(
            scope="camera",
            code="device_unavailable",
            message=message,
            hint=hint,
            mock_compatible=True,
        )
    return PreflightIssue(
        scope="camera",
        code="probe_failed",
        message=message,
        hint="先用 scripts/validate/validate_camera_only.py 单独验证摄像头，再回到完整 UI 启动链路。",
        mock_compatible=True,
    )


def _microphone_issue(message: str) -> PreflightIssue:
    normalized = message.lower()
    if "permission" in normalized or "not authorized" in normalized or "not permitted" in normalized:
        code = "permission_denied"
        hint = (
            "请在 macOS 打开“系统设置 -> 隐私与安全性 -> 麦克风”，"
            "给当前终端应用（Terminal / iTerm / Codex）麦克风权限，然后完全重启终端后重试。"
        )
    elif "import failed" in normalized:
        code = "driver_unavailable"
        hint = "当前 Python 环境缺少 sounddevice；如果只想先体验 UI，可以使用 --mock-if-unavailable。"
    elif "query failed" in normalized:
        code = "device_query_failed"
        hint = (
            "麦克风设备查询失败。请检查 macOS 的“隐私与安全性 -> 麦克风”权限，"
            "并确认当前终端应用已被授权。"
        )
    elif "no input microphone device detected" in normalized:
        code = "no_input_device"
        hint = "没有发现可用麦克风输入设备；可以先插入耳机麦克风，或使用 --mock-if-unavailable。"
    else:
        code = "unavailable"
        hint = "麦克风当前不可用；如果只是验证 UI 和仲裁链路，可以先走 mock 体验。"
    return PreflightIssue(
        scope="microphone",
        code=code,
        message=message,
        hint=hint,
        mock_compatible=True,
    )


def _pipeline_issue(pipeline_name: str, reason: str) -> PreflightIssue:
    return PreflightIssue(
        scope="pipeline",
        code="degraded",
        message=f"{pipeline_name} 初始化降级: {reason}",
        hint="检查依赖、模型文件和本机后端是否可用；如只做 UI/仲裁体验，可先接受降级。",
        mock_compatible=True,
    )


def _validate_sounddevice(detector_cfg: dict) -> list[PreflightIssue]:
    probe = probe_live_microphone_source(**microphone_source_options_from_detector_cfg(detector_cfg))
    details = [f"backend={probe.backend}", f"input_devices={probe.input_device_count}"]
    if probe.default_input_index is not None:
        details.append(f"default_input={probe.default_input_index}")
    if probe.selected_device is not None:
        details.append(f"selected={probe.selected_device}")
    if probe.selected_device_name:
        details.append(f"selected_name={probe.selected_device_name}")
    if probe.input_device_names:
        details.append(f"inputs={','.join(probe.input_device_names[:3])}")
    print(f"[info] microphone {' '.join(details)}")
    if probe.warning:
        return [_microphone_issue(probe.warning)]
    return []


def _validate_pipeline_registry(
    runtime_config: Path,
    detector_config: Path,
    arbitration_config: Path,
    stabilizer_config: Path,
    safety_config: Path,
) -> list[PreflightIssue]:
    issues: list[PreflightIssue] = []
    app_cfg = load_app_config(runtime_config)
    detector_cfg = load_detector_config(detector_config)
    load_arbitration_config(arbitration_config)
    load_stabilizer_config(stabilizer_config)
    load_safety_config(safety_config)

    if app_cfg.runtime.mock_drivers:
        issues.append(
            PreflightIssue(
                scope="runtime",
                code="mock_drivers_enabled",
                message="local runtime config unexpectedly enabled mock_drivers",
                hint="本地真机 profile 应该关闭 mock_drivers；请检查 runtime 配置是否切错。",
                mock_compatible=False,
            )
        )

    registry = build_pipeline_registry(
        app_cfg.runtime.enabled_pipelines,
        detector_cfg,
        mock_drivers=app_cfg.runtime.mock_drivers,
    )
    registry.initialize_all()
    try:
        for pipeline_name in registry.list_pipelines():
            pipeline = registry.get_pipeline(pipeline_name)
            if pipeline is None:
                issues.append(
                    PreflightIssue(
                        scope="pipeline",
                        code="missing_registration",
                        message=f"pipeline not registered: {pipeline_name}",
                        hint="pipeline registry 构建异常，请检查 build_pipeline_registry 的注册逻辑。",
                        mock_compatible=False,
                    )
                )
                continue
            if type(pipeline).__name__ == "NoOpPipeline":
                reason = getattr(pipeline, "reason", "unknown")
                issues.append(_pipeline_issue(pipeline_name, reason))
    finally:
        registry.close_all()
    return issues


def _validate_camera(camera_device_index: int) -> tuple[list[PreflightIssue], int | None]:
    try:
        resolved_camera, usable_devices = _resolve_camera_device(camera_device_index)
    except Exception as exc:
        print(f"camera_device_requested={camera_device_index}")
        print("camera_device_actual=none")
        return ([_camera_issue(f"camera probe failed: {exc}")], None)

    print(f"camera_device_requested={camera_device_index}")
    print(f"camera_device_actual={resolved_camera}")
    if resolved_camera != camera_device_index:
        print(f"[info] camera index {camera_device_index} remapped to {resolved_camera}; usable={usable_devices}")
    return ([], resolved_camera)


def _print_issues(issues: list[PreflightIssue]) -> None:
    for issue in issues:
        print(f"- [{issue.scope}:{issue.code}] {issue.message}")
        if issue.hint:
            print(f"  hint: {issue.hint}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Preflight checks for local Mac fast-reaction validation.")
    parser.add_argument("--runtime-config", type=Path, default=DEFAULT_RUNTIME_CONFIG)
    parser.add_argument("--detector-config", type=Path, default=DEFAULT_DETECTOR_CONFIG)
    parser.add_argument("--arbitration-config", type=Path, default=DEFAULT_ARBITRATION_CONFIG)
    parser.add_argument("--stabilizer-config", type=Path, default=DEFAULT_STABILIZER_CONFIG)
    parser.add_argument("--safety-config", type=Path, default=DEFAULT_SAFETY_CONFIG)
    parser.add_argument("--camera-device-index", type=int, default=0)
    args = parser.parse_args()

    issues: list[PreflightIssue] = []
    issues.extend(
        _validate_files(
            [
                args.runtime_config,
                args.detector_config,
                args.arbitration_config,
                args.stabilizer_config,
                args.safety_config,
                PROJECT_ROOT / "models" / "mediapipe" / "face_landmarker.task",
                PROJECT_ROOT / "models" / "mediapipe" / "gesture_recognizer.task",
            ]
        )
    )

    resolved_camera: int | None = None
    if not issues:
        camera_issues, resolved_camera = _validate_camera(args.camera_device_index)
        issues.extend(camera_issues)
        detector_cfg = load_detector_config(args.detector_config)
        issues.extend(_validate_sounddevice(detector_cfg))
    if not issues:
        issues.extend(
            _validate_pipeline_registry(
                args.runtime_config,
                args.detector_config,
                args.arbitration_config,
                args.stabilizer_config,
                args.safety_config,
            )
        )

    print("=== Local Fast Reaction Preflight ===")
    print(f"runtime_config={args.runtime_config}")
    print(f"detector_config={args.detector_config}")
    print(f"camera_device_index={args.camera_device_index}")
    if resolved_camera is not None:
        print(f"camera_device_actual={resolved_camera}")
    if issues:
        print("FAIL")
        _print_issues(issues)
        if all(issue.mock_compatible for issue in issues):
            print("")
            print("next_step=mock_fallback_available")
            print(
                "hint: 你可以执行 ./scripts/launch/run_ui_local_fast_reaction.sh start --mock-if-unavailable 先体验 UI 和仲裁链路。"
            )
        return 1

    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
