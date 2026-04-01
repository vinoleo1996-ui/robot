#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from time import monotonic, sleep

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_SRC = PROJECT_ROOT / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

DEFAULT_RUNTIME_CONFIG = PROJECT_ROOT / "configs" / "runtime" / "desktop_4090" / "desktop_4090.yaml"
SMOKE_RUNTIME_CONFIG = (
    PROJECT_ROOT / "configs" / "runtime" / "desktop_4090" / "desktop_4090.smoke.yaml"
)
DEFAULT_DETECTOR_CONFIG = (
    PROJECT_ROOT / "configs" / "detectors" / "desktop_4090" / "desktop_4090.yaml"
)
DEFAULT_ARBITRATION_CONFIG = PROJECT_ROOT / "configs" / "arbitration" / "default.yaml"
DEFAULT_STABILIZER_CONFIG = PROJECT_ROOT / "configs" / "stabilizer" / "default.yaml"
DEFAULT_SLOW_SCENE_CONFIG = PROJECT_ROOT / "configs" / "slow_scene" / "default.yaml"

from robot_life.behavior.executor import BehaviorExecutor
from robot_life.behavior.resources import ResourceManager
from robot_life.common.cuda_runtime import ensure_cuda_runtime_loaded
from robot_life.common.config import (
    load_app_config,
    load_arbitration_config,
    load_slow_scene_config,
    load_stabilizer_config,
)
from robot_life.common.schemas import EventPriority
from robot_life.event_engine.arbitration_runtime import ArbitrationRuntime
from robot_life.event_engine.arbitrator import Arbitrator
from robot_life.event_engine.builder import EventBuilder
from robot_life.event_engine.scene_aggregator import SceneAggregator
from robot_life.event_engine.stabilizer import EventStabilizer
from robot_life.runtime import (
    build_live_microphone_source,
    CameraSource,
    InMemoryTelemetrySink,
    LiveLoop,
    LiveLoopDependencies,
    SourceBundle,
    SyntheticCameraSource,
    SyntheticMicrophoneSource,
    build_pipeline_registry,
    load_detector_config,
    microphone_source_options_from_detector_cfg,
)
from robot_life.slow_scene.service import SlowSceneService


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int((len(ordered) - 1) * pct)
    return ordered[index]


def _default_path(*parts: str) -> Path:
    return PROJECT_ROOT.joinpath(*parts)


def _camera_read_timeout_s(timeout_ms: int) -> float:
    return max(20, int(timeout_ms)) / 1000.0


def _probe_camera_index(index: int) -> bool:
    try:
        import cv2
    except Exception:
        return False

    capture = cv2.VideoCapture(index)
    try:
        if not capture.isOpened():
            return False
        ok, frame = capture.read()
        return bool(ok and frame is not None)
    finally:
        capture.release()


def _discover_camera_candidates(max_probe_index: int = 10) -> list[int]:
    detected: list[int] = []
    for device in sorted(Path("/dev").glob("video*"), reverse=True):
        match = re.search(r"(\d+)$", device.name)
        if not match:
            continue
        detected.append(int(match.group(1)))

    if detected:
        seen: set[int] = set()
        ordered: list[int] = []
        for index in detected:
            if index in seen:
                continue
            seen.add(index)
            ordered.append(index)
        return ordered

    return list(range(max_probe_index, -1, -1))


def _resolve_camera_device(requested_index: int, *, max_probe_index: int = 10) -> tuple[int, list[int]]:
    probe_order: list[int] = []
    seen: set[int] = set()

    if requested_index >= 0:
        probe_order.append(requested_index)
        seen.add(requested_index)

    for index in _discover_camera_candidates(max_probe_index=max_probe_index):
        if index not in seen:
            probe_order.append(index)
            seen.add(index)

    usable: list[int] = []
    for index in probe_order:
        if _probe_camera_index(index):
            usable.append(index)
            if index == requested_index:
                return index, usable
            return index, usable

    raise RuntimeError("未找到可用摄像头设备，无法执行真机 4090 验证。")


def _build_arbitrator(arbitration_config: Path | None = None) -> Arbitrator:
    config_path = arbitration_config or _default_path("configs", "arbitration", "default.yaml")
    return Arbitrator(config=load_arbitration_config(config_path))


def _resolve_event_priorities(priority_map: dict[str, str]) -> dict[str, EventPriority]:
    resolved: dict[str, EventPriority] = {}
    for event_type, priority_name in priority_map.items():
        try:
            resolved[str(event_type)] = EventPriority(str(priority_name))
        except ValueError:
            continue
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate runtime latency and resource metrics on 4090.")
    parser.add_argument("--iterations", type=int, default=120)
    parser.add_argument("--duration-sec", type=int, default=0)
    parser.add_argument("--warmup-iterations", type=int, default=0)
    parser.add_argument("--poll-interval", type=float, default=1.0 / 30.0)
    parser.add_argument("--latency-budget-ms", type=float, default=500.0)
    parser.add_argument("--vram-budget-mb", type=float, default=18000.0)
    parser.add_argument("--min-camera-packets", type=int, default=1)
    parser.add_argument("--min-microphone-packets", type=int, default=0)
    parser.add_argument("--camera-device-index", type=int, default=0)
    parser.add_argument("--camera-read-timeout-ms", type=int, default=120)
    parser.add_argument("--require-gpu", action="store_true")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="使用 smoke runtime 配置运行快速回归，不探测真机摄像头。",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_RUNTIME_CONFIG,
    )
    parser.add_argument(
        "--detectors",
        type=Path,
        default=DEFAULT_DETECTOR_CONFIG,
    )
    parser.add_argument(
        "--arbitration-config",
        type=Path,
        default=DEFAULT_ARBITRATION_CONFIG,
    )
    parser.add_argument(
        "--stabilizer",
        type=Path,
        default=DEFAULT_STABILIZER_CONFIG,
    )
    parser.add_argument(
        "--slow-scene-config",
        type=Path,
        default=DEFAULT_SLOW_SCENE_CONFIG,
    )
    parser.add_argument("--enable-slow-scene", action="store_true")
    parser.add_argument("--report-json", type=Path, default=None)
    args = parser.parse_args()

    if args.smoke and args.config == DEFAULT_RUNTIME_CONFIG:
        args.config = SMOKE_RUNTIME_CONFIG

    app_cfg = load_app_config(args.config)
    detector_cfg = load_detector_config(args.detectors)
    stabilizer_cfg = load_stabilizer_config(args.stabilizer)
    slow_cfg = load_slow_scene_config(args.slow_scene_config)
    arbitration_cfg = load_arbitration_config(args.arbitration_config)
    ensure_cuda_runtime_loaded()

    registry = build_pipeline_registry(
        app_cfg.runtime.enabled_pipelines,
        detector_cfg,
        mock_drivers=app_cfg.runtime.mock_drivers,
    )
    telemetry = InMemoryTelemetrySink()
    slow_scene = SlowSceneService(
        use_qwen=args.enable_slow_scene and slow_cfg.use_qwen,
        config=slow_cfg,
    )
    arbitrator = Arbitrator(config=arbitration_cfg)
    dependencies = LiveLoopDependencies(
        builder=EventBuilder(),
        stabilizer=EventStabilizer.from_config(stabilizer_cfg),
        aggregator=SceneAggregator(),
        arbitrator=arbitrator,
        arbitration_runtime=ArbitrationRuntime(arbitrator=arbitrator),
        executor=BehaviorExecutor(ResourceManager()),
        slow_scene=slow_scene,
        telemetry=telemetry,
        event_priorities=_resolve_event_priorities(dict(arbitration_cfg.event_priorities)),
    )

    if app_cfg.runtime.mock_drivers:
        source_bundle = SourceBundle(
            camera=SyntheticCameraSource(),
            microphone=SyntheticMicrophoneSource(),
        )
        resolved_camera_device = None
    else:
        resolved_camera_device, usable_devices = _resolve_camera_device(args.camera_device_index)
        if resolved_camera_device != args.camera_device_index:
            print(
                f"[warn] 请求摄像头索引 {args.camera_device_index} 不可用，已自动切换到 {resolved_camera_device}。"
                f" 可用索引: {usable_devices}"
            )
        microphone_source, mic_warning = build_live_microphone_source(
            **microphone_source_options_from_detector_cfg(detector_cfg)
        )
        if mic_warning:
            print(f"[warn] {mic_warning}")
        source_bundle = SourceBundle(
            camera=CameraSource(
                device_index=resolved_camera_device,
                read_timeout_s=_camera_read_timeout_s(args.camera_read_timeout_ms),
            ),
            microphone=microphone_source,
        )

    loop = LiveLoop(
        registry=registry,
        source_bundle=source_bundle,
        dependencies=dependencies,
        telemetry=telemetry,
        fast_path_budget_ms=app_cfg.runtime.fast_path_budget_ms,
        fast_path_pending_limit=app_cfg.runtime.fast_path_pending_limit,
        max_scenes_per_cycle=app_cfg.runtime.max_scenes_per_cycle,
        async_perception_enabled=app_cfg.runtime.async_perception_enabled,
        async_perception_queue_limit=app_cfg.runtime.async_perception_queue_limit,
        async_executor_enabled=app_cfg.runtime.async_executor_enabled,
        async_executor_queue_limit=app_cfg.runtime.async_executor_queue_limit,
        async_capture_enabled=app_cfg.runtime.async_capture_enabled,
        async_capture_queue_limit=app_cfg.runtime.async_capture_queue_limit,
        enable_slow_scene=args.enable_slow_scene,
    )

    iteration_latencies: list[float] = []
    warmup_latencies: list[float] = []
    all_results = []
    measured_results = []
    benchmark_started_at = monotonic()
    try:
        loop.start()
        deadline = monotonic() + max(0, args.duration_sec) if args.duration_sec > 0 else None
        iteration_budget = max(1, args.iterations) if args.duration_sec <= 0 else None
        while True:
            if iteration_budget is not None and len(iteration_latencies) >= iteration_budget:
                break
            if deadline is not None and monotonic() >= deadline:
                break
            started = monotonic()
            loop_result = loop.run_once()
            elapsed = monotonic() - started
            if len(warmup_latencies) < max(0, args.warmup_iterations):
                warmup_latencies.append(elapsed * 1000.0)
            else:
                measured_results.append(loop_result)
                iteration_latencies.append(elapsed * 1000.0)
            all_results.append(loop_result)
            sleep(max(0.0, args.poll_interval - elapsed))
    finally:
        loop.stop()
        slow_scene.close()
    benchmark_duration_s = max(0.0, monotonic() - benchmark_started_at)

    p50 = _percentile(iteration_latencies, 0.50)
    p95 = _percentile(iteration_latencies, 0.95)
    p99 = _percentile(iteration_latencies, 0.99)
    measured_payload = measured_results if measured_results else all_results
    execution_count = sum(len(item.execution_results) for item in measured_payload)
    camera_packet_count = sum(
        1 for item in measured_payload if "camera" in item.collected_frames.packets
    )
    microphone_packet_count = sum(
        1 for item in measured_payload if "microphone" in item.collected_frames.packets
    )
    degraded_count = sum(
        1 for item in measured_payload for execution in item.execution_results if execution.degraded
    )
    slow_health = slow_scene.health()

    max_vram_mb = None
    ort_providers: list[str] = []
    gguf_gpu_offload = None
    try:
        import torch

        if torch.cuda.is_available():
            max_vram_mb = torch.cuda.max_memory_allocated() / (1024 * 1024)
    except Exception:
        max_vram_mb = None
    try:
        import onnxruntime as ort

        ort_providers = list(ort.get_available_providers())
    except Exception:
        ort_providers = []
    try:
        import llama_cpp

        gguf_gpu_offload = bool(llama_cpp.llama_supports_gpu_offload())
    except Exception:
        gguf_gpu_offload = None

    print("=== 4090 Validation Summary ===")
    print(f"iterations={len(iteration_latencies)}")
    print(f"warmup_iterations={len(warmup_latencies)}")
    print(f"duration_sec={benchmark_duration_s:.2f}")
    print(f"latency_ms p50={p50:.2f} p95={p95:.2f} p99={p99:.2f}")
    print(f"executions={execution_count} degraded={degraded_count}")
    print(f"camera_packets={camera_packet_count}")
    print(f"microphone_packets={microphone_packet_count}")
    print(f"camera_device(requested)={args.camera_device_index}")
    print(f"camera_device(actual)={resolved_camera_device if resolved_camera_device is not None else 'mock'}")
    print(f"camera_read_timeout_ms={args.camera_read_timeout_ms}")
    print(f"slow_scene timed_out={slow_health.timed_out_requests} dropped={slow_health.dropped_requests}")
    print(f"vram_max_mb={max_vram_mb if max_vram_mb is not None else 'n/a'}")
    print(f"onnx_providers={ort_providers if ort_providers else 'n/a'}")
    print(f"gguf_gpu_offload={gguf_gpu_offload if gguf_gpu_offload is not None else 'n/a'}")

    failures: list[str] = []
    if p95 > args.latency_budget_ms:
        failures.append(f"p95 latency {p95:.2f}ms exceeded budget {args.latency_budget_ms:.2f}ms")
    if not app_cfg.runtime.mock_drivers and camera_packet_count < args.min_camera_packets:
        failures.append(
            f"camera packets {camera_packet_count} below minimum {args.min_camera_packets}"
        )
    if not app_cfg.runtime.mock_drivers and microphone_packet_count < args.min_microphone_packets:
        failures.append(
            f"microphone packets {microphone_packet_count} below minimum {args.min_microphone_packets}"
        )
    if args.require_gpu and max_vram_mb is None:
        failures.append("GPU metrics unavailable but --require-gpu was set")
    if args.require_gpu and "CUDAExecutionProvider" not in ort_providers:
        failures.append("ONNX Runtime CUDAExecutionProvider unavailable")
    if args.require_gpu and args.enable_slow_scene and gguf_gpu_offload is False:
        failures.append("llama-cpp GPU offload unavailable for GGUF slow scene")
    if max_vram_mb is not None and max_vram_mb > args.vram_budget_mb:
        failures.append(f"VRAM {max_vram_mb:.2f}MB exceeded budget {args.vram_budget_mb:.2f}MB")

    if failures:
        print("VALIDATION FAILED")
        for failure in failures:
            print(f"- {failure}")
        exit_code = 1
    else:
        print("VALIDATION PASSED")
        exit_code = 0

    if args.report_json is not None:
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        args.report_json.write_text(
            json.dumps(
                {
                    "iterations": len(iteration_latencies),
                    "warmup_iterations": len(warmup_latencies),
                    "duration_sec": round(benchmark_duration_s, 3),
                    "latency_ms": {"p50": round(p50, 3), "p95": round(p95, 3), "p99": round(p99, 3)},
                    "executions": execution_count,
                    "degraded": degraded_count,
                    "camera_packets": camera_packet_count,
                    "microphone_packets": microphone_packet_count,
                    "camera_device": {
                        "requested": args.camera_device_index,
                        "actual": resolved_camera_device,
                    },
                    "camera_read_timeout_ms": args.camera_read_timeout_ms,
                    "slow_scene": {
                        "timed_out": slow_health.timed_out_requests,
                        "dropped": slow_health.dropped_requests,
                    },
                    "vram_max_mb": max_vram_mb,
                    "onnx_providers": ort_providers,
                    "gguf_gpu_offload": gguf_gpu_offload,
                    "failures": failures,
                    "passed": exit_code == 0,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
