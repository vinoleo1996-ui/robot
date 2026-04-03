from __future__ import annotations

from pathlib import Path

import typer

from robot_life.behavior.decay_tracker import BehaviorDecayTracker
from robot_life.behavior.executor import BehaviorExecutor
from robot_life.behavior.resources import ResourceManager
from robot_life.behavior.safety_guard import BehaviorSafetyGuard
from robot_life.cli_shared import (
    console,
    _audit_detector_model_paths,
    _build_arbitration_runtime,
    _build_arbitrator,
    _camera_read_timeout_s,
    _default_arbitration_config_path,
    _default_config_path,
    _default_detector_config_path,
    _default_safety_config_path,
    _default_slow_scene_config_path,
    _default_stabilizer_config_path,
    _resolve_camera_device,
    _resolve_event_priorities,
)
from robot_life.common.config import (
    load_app_config,
    load_arbitration_config,
    load_safety_config,
    load_slow_scene_config,
    load_stabilizer_config,
)
from robot_life.common.logging import configure_logging
from robot_life.common.schemas import DetectionResult, EventPriority
from robot_life.common.state_machine import InteractionStateMachine
from robot_life.event_engine.arbitrator import Arbitrator
from robot_life.event_engine.builder import EventBuilder
from robot_life.event_engine.cooldown_manager import CooldownManager
from robot_life.event_engine.entity_tracker import EntityTracker
from robot_life.event_engine.scene_aggregator import SceneAggregator
from robot_life.event_engine.stabilizer import EventStabilizer
from robot_life.event_engine.temporal_event_layer import TemporalEventLayer
from robot_life.runtime import (
    LiveLoop,
    LiveLoopDependencies,
    LoggingTelemetrySink,
    NullTelemetrySink,
    SourceBundle,
    SyntheticCameraSource,
    SyntheticMicrophoneSource,
    build_live_camera_source,
    build_live_microphone_source,
    build_pipeline_registry,
    load_detector_config,
    microphone_source_options_from_detector_cfg,
)
from robot_life.runtime.ui_demo import run_ui_dashboard
from robot_life.slow_scene.service import SlowSceneService


def run(
    config: Path = typer.Option(_default_config_path(), exists=True, readable=True),
) -> None:
    """Run the scaffold in demo mode with multiple synthetic events."""
    app_config = load_app_config(config)
    configure_logging(app_config.runtime.log_level)
    arbitration_cfg = load_arbitration_config(_default_arbitration_config_path())

    builder = EventBuilder(event_priorities=_resolve_event_priorities(arbitration_cfg))
    stabilizer = EventStabilizer(
        debounce_count=2,
        debounce_window_ms=500,
        cooldown_ms=1500,
        hysteresis_threshold=0.7,
    )
    aggregator = SceneAggregator()
    arbitrator = Arbitrator()
    resource_manager = ResourceManager()
    executor = BehaviorExecutor(resource_manager)
    slow_scene = SlowSceneService()

    console.print("[bold blue]═══════════════════════════════════════════════════════[/bold blue]")
    console.print("[bold blue]     Robot Life MVP Demo - Event Processing Pipeline[/bold blue]")
    console.print("[bold blue]═══════════════════════════════════════════════════════[/bold blue]")
    console.print()

    demo_scenarios = [
        {
            "name": "Scenario 1: Greeting Recognition",
            "events": [
                {
                    "detector": "face_pipeline",
                    "event_type": "familiar_face",
                    "confidence": 0.92,
                    "payload": {"target_id": "user_dad", "face_area": 0.12},
                },
                {
                    "detector": "face_pipeline",
                    "event_type": "familiar_face",
                    "confidence": 0.94,
                    "payload": {"target_id": "user_dad", "face_area": 0.13},
                },
            ],
        },
        {
            "name": "Scenario 2: Gesture Interaction",
            "events": [
                {
                    "detector": "gesture_pipeline",
                    "event_type": "gesture",
                    "confidence": 0.82,
                    "payload": {"gesture_type": "wave", "hand_count": 1},
                },
                {
                    "detector": "gesture_pipeline",
                    "event_type": "gesture",
                    "confidence": 0.85,
                    "payload": {"gesture_type": "wave", "hand_count": 1},
                },
            ],
        },
        {
            "name": "Scenario 3: Audio Alert",
            "events": [
                {
                    "detector": "audio_pipeline",
                    "event_type": "loud_sound",
                    "confidence": 0.75,
                    "payload": {"sound_level_db": 85},
                },
                {
                    "detector": "audio_pipeline",
                    "event_type": "loud_sound",
                    "confidence": 0.78,
                    "payload": {"sound_level_db": 87},
                },
            ],
        },
    ]

    event_counter = 1
    for scenario in demo_scenarios:
        console.print(f"[bold yellow]▶ {scenario['name']}[/bold yellow]")
        console.print()

        for sub_idx, event_data in enumerate(scenario["events"], 1):
            console.print(f"  [cyan]Event {event_counter}.{sub_idx}: {event_data['event_type']}[/cyan]")
            detection = DetectionResult.synthetic(
                detector=event_data["detector"],
                event_type=event_data["event_type"],
                confidence=event_data["confidence"],
                payload=event_data["payload"],
            )
            console.print(f"    ├─ Detection: {detection.event_type:20s} (conf={detection.confidence:.2f})")

            raw_event = builder.build(detection, priority=EventPriority.P2)
            console.print(f"    ├─ Raw Event ID: {raw_event.event_id[:12]}...")

            stable_event = stabilizer.process(raw_event)
            if stable_event is None:
                console.print("    ├─ [yellow]Stabilizer:[/yellow] Pending confirmations (debounce)")
                console.print()
                continue

            console.print(
                f"    ├─ [green]Stabilizer:[/green] ✓ Passed (stabilized_by={stable_event.stabilized_by})"
            )
            scene = aggregator.aggregate(stable_event)
            console.print(f"    ├─ Scene Type: {scene.scene_type:25s} (score={scene.score_hint:.2f})")

            decision = arbitrator.decide(scene)
            console.print(
                f"    ├─ Behavior: {decision.target_behavior:20s} "
                f"(mode={decision.mode}, priority={decision.priority})"
            )

            execution = executor.execute(decision)
            exec_status = "✓ FINISHED" if execution.status == "finished" else f"⚠ {execution.status}"
            console.print(
                f"    ├─ [bold green]Execution:[/bold green] {exec_status:15s} (degraded={execution.degraded})"
            )

            scene_json = slow_scene.build_scene_json(scene)
            console.print(
                f"    └─ Scene JSON: emotion={scene_json.emotion_hint:15s} "
                f"urgency={scene_json.urgency_hint:8s} escalate={scene_json.escalate_to_cloud}"
            )
            console.print()

        event_counter += 1

    console.print("[bold green]═══════════════════════════════════════════════════════[/bold green]")
    console.print("[bold green]✓ Demo Completed Successfully[/bold green]")
    console.print()
    console.print("[bold]Final System State:[/bold]")
    console.print()

    resource_status = executor.get_resource_status()
    console.print("[italic]Resource Allocation:[/italic]")
    for res_name, status in resource_status.items():
        status_icon = "○" if "free" in status else "●"
        console.print(f"  {status_icon} {res_name:20s}: {status}")

    console.print()
    console.print("[italic]Stabilizer State:[/italic]")
    stabilizer_stats = stabilizer.snapshot_stats()
    state_sizes = stabilizer_stats.get("state_sizes", {})
    console.print(f"  • Debounce confirms pending: {state_sizes.get('debounce', 0)} event types")
    console.print(f"  • Cooldown active: {state_sizes.get('cooldown', 0)} event types")
    console.print(f"  • Hysteresis tracking: {state_sizes.get('hysteresis', 0)} event types")
    console.print()
    console.print("[bold cyan]Ready for real detector integration →[/bold cyan] See docs/ops/DEPLOYMENT_4090.md")
    console.print("[bold blue]═══════════════════════════════════════════════════════[/bold blue]")


def _build_live_dependencies(
    *,
    runtime_cfg,
    arbitration_config_path: Path,
    arbitration_cfg,
    stabilizer_cfg,
    safety_cfg,
    slow_cfg,
    enable_slow_scene: bool,
    telemetry,
) -> tuple[LiveLoopDependencies, Arbitrator, SlowSceneService]:
    arbitrator = _build_arbitrator(arbitration_config_path)
    arbitration_runtime = _build_arbitration_runtime(arbitrator, arbitration_cfg)
    slow_scene = SlowSceneService(
        use_qwen=enable_slow_scene and slow_cfg.use_qwen,
        config=slow_cfg,
    )
    dependencies = LiveLoopDependencies(
        builder=EventBuilder(event_priorities=_resolve_event_priorities(arbitration_cfg)),
        stabilizer=EventStabilizer.from_config(stabilizer_cfg),
        aggregator=SceneAggregator(),
        arbitrator=arbitrator,
        arbitration_runtime=arbitration_runtime,
        executor=BehaviorExecutor(
            ResourceManager(),
            safety_guard=BehaviorSafetyGuard.from_config(safety_cfg),
            tick_execution=bool(getattr(runtime_cfg, "behavior_tick_enabled", False)),
            tick_max_nodes=int(getattr(runtime_cfg, "behavior_tick_max_nodes", 0)),
        ),
        slow_scene=slow_scene,
        telemetry=telemetry,
        event_priorities=_resolve_event_priorities(arbitration_cfg),
        cooldown_manager=CooldownManager(),
        decay_tracker=BehaviorDecayTracker(),
        interaction_state_machine=InteractionStateMachine(),
        entity_tracker=EntityTracker(),
        temporal_event_layer=TemporalEventLayer(),
    )
    return dependencies, arbitrator, slow_scene


def _build_microphone_source(detector_cfg):
    mic_options = microphone_source_options_from_detector_cfg(detector_cfg)
    return build_live_microphone_source(**mic_options)


def run_live(
    config: Path = typer.Option(_default_config_path(), exists=True, readable=True),
    detectors: Path = typer.Option(_default_detector_config_path(), exists=True, readable=True),
    arbitration_config: Path = typer.Option(
        _default_arbitration_config_path(), exists=True, readable=True
    ),
    stabilizer_config: Path = typer.Option(
        _default_stabilizer_config_path(), exists=True, readable=True
    ),
    safety_config: Path = typer.Option(
        _default_safety_config_path(), exists=True, readable=True
    ),
    slow_scene_config: Path = typer.Option(
        _default_slow_scene_config_path(), exists=True, readable=True
    ),
    iterations: int = typer.Option(30, min=1, help="How many loop iterations to execute."),
    camera_device: int = typer.Option(0, help="Camera device index for OpenCV."),
    camera_read_timeout_ms: int = typer.Option(
        120,
        min=20,
        help="Camera read timeout in ms for real device reads.",
    ),
    enable_slow_scene: bool = typer.Option(False, help="Enable async slow-scene sidecar."),
) -> None:
    """Run the minimal live runtime loop against real camera input."""
    app_config = load_app_config(config)
    configure_logging(app_config.runtime.log_level)

    detector_cfg = load_detector_config(detectors)
    stabilizer_cfg = load_stabilizer_config(stabilizer_config)
    safety_cfg = load_safety_config(safety_config)
    slow_cfg = load_slow_scene_config(slow_scene_config)
    arbitration_cfg = load_arbitration_config(arbitration_config)
    if not app_config.runtime.mock_drivers:
        model_errors, model_warnings = _audit_detector_model_paths(
            detector_cfg,
            enabled_pipelines=app_config.runtime.enabled_pipelines,
        )
        for warning in model_warnings:
            console.print(f"[yellow]detector model audit warning: {warning}[/yellow]")
        if model_errors:
            for issue in model_errors:
                console.print(f"[bold red]detector model audit error:[/bold red] {issue}")
            raise typer.Exit(code=1)
    registry = build_pipeline_registry(
        app_config.runtime.enabled_pipelines,
        detector_cfg,
        mock_drivers=False,
    )
    dependencies, _, slow_scene = _build_live_dependencies(
        runtime_cfg=app_config.runtime,
        arbitration_config_path=arbitration_config,
        arbitration_cfg=arbitration_cfg,
        stabilizer_cfg=stabilizer_cfg,
        safety_cfg=safety_cfg,
        slow_cfg=slow_cfg,
        enable_slow_scene=enable_slow_scene,
        telemetry=LoggingTelemetrySink(),
    )
    arbitration_runtime = dependencies.arbitration_runtime
    assert arbitration_runtime is not None

    resolved_camera_device = camera_device
    if app_config.runtime.mock_drivers:
        camera_source = SyntheticCameraSource()
        microphone_source = SyntheticMicrophoneSource()
    else:
        try:
            resolved_camera_device, usable_devices = _resolve_camera_device(camera_device)
        except RuntimeError as exc:
            console.print(f"[bold red]摄像头初始化失败:[/bold red] {exc}")
            raise typer.Exit(code=1)
        if resolved_camera_device != camera_device:
            console.print(
                f"[yellow]请求摄像头索引 {camera_device} 不可用，已自动切换到 {resolved_camera_device}。"
                f" 可用索引: {usable_devices}[/yellow]"
            )
        camera_source = build_live_camera_source(
            device_index=resolved_camera_device,
            read_timeout_s=_camera_read_timeout_s(camera_read_timeout_ms),
        )
        microphone_source, mic_warning = _build_microphone_source(detector_cfg)
        if mic_warning:
            console.print(f"[yellow]{mic_warning}[/yellow]")
    source_bundle = SourceBundle(camera=camera_source, microphone=microphone_source)
    loop = LiveLoop(
        registry=registry,
        source_bundle=source_bundle,
        dependencies=dependencies,
        arbitration_batch_window_ms=arbitration_runtime.batch_window_ms,
        fast_path_budget_ms=app_config.runtime.fast_path_budget_ms,
        fast_path_pending_limit=app_config.runtime.fast_path_pending_limit,
        max_scenes_per_cycle=app_config.runtime.max_scenes_per_cycle,
        async_perception_enabled=app_config.runtime.async_perception_enabled,
        async_perception_queue_limit=app_config.runtime.async_perception_queue_limit,
        async_perception_result_max_age_ms=app_config.runtime.async_perception_result_max_age_ms,
        async_perception_result_max_frame_lag=app_config.runtime.async_perception_result_max_frame_lag,
        async_executor_enabled=app_config.runtime.async_executor_enabled,
        async_executor_queue_limit=app_config.runtime.async_executor_queue_limit,
        async_capture_enabled=app_config.runtime.async_capture_enabled,
        async_capture_queue_limit=app_config.runtime.async_capture_queue_limit,
        enable_slow_scene=enable_slow_scene,
    )

    console.print("[bold blue]Starting live runtime...[/bold blue]")
    console.print(f"  config={config}")
    console.print(f"  detectors={detectors}")
    console.print(f"  arbitration_config={arbitration_config}")
    console.print(f"  stabilizer_config={stabilizer_config}")
    console.print(f"  safety_config={safety_config}")
    console.print(f"  slow_scene_config={slow_scene_config}")
    console.print(f"  iterations={iterations}")
    console.print(f"  camera_device(requested)={camera_device}")
    console.print(f"  camera_device(actual)={resolved_camera_device}")
    console.print(f"  camera_read_timeout_ms={camera_read_timeout_ms}")
    console.print(f"  slow_scene={enable_slow_scene}")

    try:
        results = loop.run_forever(max_iterations=iterations)
    except Exception as exc:
        console.print(f"[bold red]Live runtime failed:[/bold red] {exc}")
        raise typer.Exit(code=1)
    finally:
        slow_scene.close()

    detection_count = sum(len(item.detections) for item in results)
    stable_count = sum(len(item.stable_events) for item in results)
    execution_count = sum(len(item.execution_results) for item in results)
    slow_count = sum(len(item.slow_scene_results) for item in results)

    console.print("[bold green]Live runtime finished[/bold green]")
    console.print(f"  detections={detection_count}")
    console.print(f"  stable_events={stable_count}")
    console.print(f"  executions={execution_count}")
    console.print(f"  slow_scene_results={slow_count}")


def ui_demo(
    config: Path = typer.Option(_default_config_path(), exists=True, readable=True),
    detectors: Path = typer.Option(_default_detector_config_path(), exists=True, readable=True),
    arbitration_config: Path = typer.Option(
        _default_arbitration_config_path(), exists=True, readable=True
    ),
    stabilizer_config: Path = typer.Option(
        _default_stabilizer_config_path(), exists=True, readable=True
    ),
    safety_config: Path = typer.Option(
        _default_safety_config_path(), exists=True, readable=True
    ),
    slow_scene_config: Path = typer.Option(
        _default_slow_scene_config_path(), exists=True, readable=True
    ),
    camera_device: int = typer.Option(0, help="Camera device index for OpenCV."),
    camera_read_timeout_ms: int = typer.Option(
        120,
        min=20,
        help="Camera read timeout in ms for real device reads.",
    ),
    enable_slow_scene: bool = typer.Option(False, help="Enable async slow-scene sidecar."),
    real: bool = typer.Option(False, "--real", help="Force real camera/mic (override mock_drivers)."),
    host: str = typer.Option("127.0.0.1", help="Dashboard bind host."),
    port: int = typer.Option(8765, min=1, max=65535, help="Dashboard bind port."),
    refresh_ms: int = typer.Option(500, min=120, help="Browser polling interval in ms."),
    poll_interval: float = typer.Option(1.0 / 30.0, min=0.005, help="Loop polling interval in sec."),
    duration_sec: int = typer.Option(
        0,
        min=0,
        help="Auto-stop duration in seconds. 0 means run until Ctrl+C.",
    ),
) -> None:
    """Launch a local web UI for interactive runtime experience."""
    app_config = load_app_config(config)
    if real:
        app_config.runtime.mock_drivers = False
    configure_logging(app_config.runtime.log_level)

    detector_cfg = load_detector_config(detectors)
    stabilizer_cfg = load_stabilizer_config(stabilizer_config)
    safety_cfg = load_safety_config(safety_config)
    slow_cfg = load_slow_scene_config(slow_scene_config)
    arbitration_cfg = load_arbitration_config(arbitration_config)
    if not app_config.runtime.mock_drivers:
        model_errors, model_warnings = _audit_detector_model_paths(
            detector_cfg,
            enabled_pipelines=app_config.runtime.enabled_pipelines,
        )
        for warning in model_warnings:
            console.print(f"[yellow]detector model audit warning: {warning}[/yellow]")
        if model_errors:
            for issue in model_errors:
                console.print(
                    f"[bold red]detector model audit error (bypassed for auto-download):[/bold red] {issue}"
                )
    registry = build_pipeline_registry(
        app_config.runtime.enabled_pipelines,
        detector_cfg,
        mock_drivers=False,
    )
    dependencies, _, _ = _build_live_dependencies(
        runtime_cfg=app_config.runtime,
        arbitration_config_path=arbitration_config,
        arbitration_cfg=arbitration_cfg,
        stabilizer_cfg=stabilizer_cfg,
        safety_cfg=safety_cfg,
        slow_cfg=slow_cfg,
        enable_slow_scene=enable_slow_scene,
        telemetry=NullTelemetrySink(),
    )
    arbitration_runtime = dependencies.arbitration_runtime
    assert arbitration_runtime is not None

    if app_config.runtime.mock_drivers:
        source_bundle = SourceBundle(
            camera=SyntheticCameraSource(),
            microphone=SyntheticMicrophoneSource(),
        )
        mode = "mock"
        resolved_camera_device = camera_device
    else:
        try:
            resolved_camera_device, usable_devices = _resolve_camera_device(camera_device)
        except RuntimeError as exc:
            console.print(f"[bold red]摄像头初始化失败:[/bold red] {exc}")
            raise typer.Exit(code=1)
        if resolved_camera_device != camera_device:
            console.print(
                f"[yellow]请求摄像头索引 {camera_device} 不可用，已自动切换到 {resolved_camera_device}。"
                f" 可用索引: {usable_devices}[/yellow]"
            )
        microphone_source, mic_warning = _build_microphone_source(detector_cfg)
        if mic_warning:
            console.print(f"[yellow]{mic_warning}[/yellow]")
        source_bundle = SourceBundle(
            camera=build_live_camera_source(
                device_index=resolved_camera_device,
                read_timeout_s=_camera_read_timeout_s(camera_read_timeout_ms),
            ),
            microphone=microphone_source,
        )
        mode = "live"

    loop = LiveLoop(
        registry=registry,
        source_bundle=source_bundle,
        dependencies=dependencies,
        arbitration_batch_window_ms=arbitration_runtime.batch_window_ms,
        fast_path_budget_ms=app_config.runtime.fast_path_budget_ms,
        fast_path_pending_limit=app_config.runtime.fast_path_pending_limit,
        max_scenes_per_cycle=app_config.runtime.max_scenes_per_cycle,
        async_perception_enabled=app_config.runtime.async_perception_enabled,
        async_perception_queue_limit=app_config.runtime.async_perception_queue_limit,
        async_perception_result_max_age_ms=app_config.runtime.async_perception_result_max_age_ms,
        async_perception_result_max_frame_lag=app_config.runtime.async_perception_result_max_frame_lag,
        async_executor_enabled=app_config.runtime.async_executor_enabled,
        async_executor_queue_limit=app_config.runtime.async_executor_queue_limit,
        async_capture_enabled=app_config.runtime.async_capture_enabled,
        async_capture_queue_limit=app_config.runtime.async_capture_queue_limit,
        enable_slow_scene=enable_slow_scene,
    )

    console.print("[bold blue]Launching UI demo...[/bold blue]")
    console.print(f"  url=http://{host}:{port}")
    console.print(f"  mode={mode}")
    console.print(f"  arbitration_config={arbitration_config}")
    console.print(f"  safety_config={safety_config}")
    console.print(f"  camera_device(requested)={camera_device}")
    console.print(f"  camera_device(actual)={resolved_camera_device}")
    console.print(f"  camera_read_timeout_ms={camera_read_timeout_ms}")
    console.print(f"  slow_scene={enable_slow_scene}")
    if duration_sec > 0:
        console.print(f"  auto_stop={duration_sec}s")
    console.print("  stop=Ctrl+C")

    try:
        run_ui_dashboard(
            loop=loop,
            mode=mode,
            current_profile=config.stem,
            detector_profile=detectors.stem,
            current_stabilizer=stabilizer_config.stem,
            host=host,
            port=port,
            refresh_ms=refresh_ms,
            poll_interval_s=poll_interval,
            duration_sec=duration_sec,
        )
    except OSError as exc:
        console.print(f"[bold red]UI demo failed:[/bold red] {exc}")
        raise typer.Exit(code=1)
    finally:
        if dependencies.slow_scene is not None:
            dependencies.slow_scene.close()
