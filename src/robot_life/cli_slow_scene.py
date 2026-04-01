from __future__ import annotations

from pathlib import Path
from time import monotonic

import typer
from rich.table import Table

from robot_life.cli_shared import (
    console,
    _camera_read_timeout_s,
    _decision_signature,
    _decision_signature_hash,
    _default_config_path,
    _default_slow_scene_config_path,
    _extract_json_payload_from_text,
    _resolve_camera_device,
)
from robot_life.common.config import load_app_config, load_slow_scene_config
from robot_life.common.logging import configure_logging
from robot_life.common.schemas import SceneCandidate, new_id, now_mono
from robot_life.runtime import CameraSource
from robot_life.runtime.ui_slow_scene import run_slow_scene_dashboard
from robot_life.slow_scene.service import SlowSceneService


def ui_slow(
    config: Path = typer.Option(_default_config_path(), exists=True, readable=True),
    slow_scene_config: Path = typer.Option(
        _default_slow_scene_config_path(), exists=True, readable=True
    ),
    camera_device: int = typer.Option(0, help="Camera device index for OpenCV."),
    camera_read_timeout_ms: int = typer.Option(
        120,
        min=20,
        help="Camera read timeout in ms for real device reads.",
    ),
    host: str = typer.Option("127.0.0.1", help="Dashboard bind host."),
    port: int = typer.Option(8771, min=1, max=65535, help="Dashboard bind port."),
    refresh_ms: int = typer.Option(500, min=200, help="Browser polling interval in ms."),
    duration_sec: int = typer.Option(
        0,
        min=0,
        help="Auto-stop duration in seconds. 0 means run until Ctrl+C.",
    ),
) -> None:
    """Launch slow-thinking-only dashboard (scene description + full JSON)."""
    app_config = load_app_config(config)
    configure_logging(app_config.runtime.log_level)
    slow_cfg = load_slow_scene_config(slow_scene_config)

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

    camera_source = CameraSource(
        device_index=resolved_camera_device,
        read_timeout_s=_camera_read_timeout_s(camera_read_timeout_ms),
    )
    slow_scene = SlowSceneService(use_qwen=slow_cfg.use_qwen, config=slow_cfg)

    console.print("[bold blue]Launching Slow-Scene only UI...[/bold blue]")
    console.print(f"  url=http://{host}:{port}")
    console.print("  mode=slow_scene_only")
    console.print(f"  camera_device(requested)={camera_device}")
    console.print(f"  camera_device(actual)={resolved_camera_device}")
    console.print(f"  camera_read_timeout_ms={camera_read_timeout_ms}")
    console.print(f"  sample_interval={slow_scene.sample_interval_s}s")
    if duration_sec > 0:
        console.print(f"  auto_stop={duration_sec}s")
    console.print("  stop=Ctrl+C")

    try:
        run_slow_scene_dashboard(
            camera_source=camera_source,
            slow_scene=slow_scene,
            host=host,
            port=port,
            refresh_ms=refresh_ms,
            sample_interval_s=slow_scene.sample_interval_s,
            duration_sec=duration_sec,
        )
    except OSError as exc:
        console.print(f"[bold red]Slow UI failed:[/bold red] {exc}")
        raise typer.Exit(code=1)
    finally:
        slow_scene.close()


def slow_consistency(
    config: Path = typer.Option(_default_config_path(), exists=True, readable=True),
    slow_scene_config: Path = typer.Option(
        _default_slow_scene_config_path(), exists=True, readable=True
    ),
    camera_device: int = typer.Option(0, help="Camera device index for OpenCV."),
    camera_read_timeout_ms: int = typer.Option(
        120,
        min=20,
        help="Camera read timeout in ms for real device reads.",
    ),
    runs: int = typer.Option(10, min=3, max=30, help="How many repeated runs on one static frame."),
) -> None:
    """Evaluate slow-scene consistency by repeating inference on one frozen frame."""
    app_config = load_app_config(config)
    configure_logging(app_config.runtime.log_level)
    slow_cfg = load_slow_scene_config(slow_scene_config)

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

    camera_source = CameraSource(
        device_index=resolved_camera_device,
        read_timeout_s=_camera_read_timeout_s(camera_read_timeout_ms),
    )
    slow_scene = SlowSceneService(use_qwen=slow_cfg.use_qwen, config=slow_cfg)
    try:
        camera_source.open()
        packet = camera_source.read()
        if packet is None or packet.payload is None:
            console.print("[bold red]未能读取到有效摄像头画面，无法执行一致性测试[/bold red]")
            raise typer.Exit(code=1)
        frozen_frame = packet.payload
    finally:
        camera_source.close()

    console.print("[bold blue]Running slow-scene consistency benchmark...[/bold blue]")
    console.print(f"  model_path={slow_cfg.model_path}")
    console.print(f"  camera_device={resolved_camera_device}")
    console.print(f"  camera_read_timeout_ms={camera_read_timeout_ms}")
    console.print(f"  runs={runs}")

    rows: list[dict] = []
    for index in range(1, runs + 1):
        scene = SceneCandidate(
            scene_id=new_id(),
            trace_id=new_id(),
            scene_type="ambient_tracking_scene",
            based_on_events=[],
            score_hint=0.5,
            valid_until_monotonic=now_mono() + 15.0,
            target_id=None,
            payload={"source": "slow_consistency"},
        )
        started = monotonic()
        _ = slow_scene.build_scene_json(
            scene,
            image=frozen_frame,
            context=(
                "一致性评估：这是同一静态帧的重复推理。"
                "请保持判断稳定，并严格遵守主动交互门控规则。"
            ),
        )
        elapsed_ms = (monotonic() - started) * 1000.0
        snapshot = slow_scene.debug_snapshot()
        debug = snapshot.get("adapter_debug", {}) if isinstance(snapshot, dict) else {}
        raw_output = debug.get("last_output_text") if isinstance(debug, dict) else None
        payload = _extract_json_payload_from_text(raw_output if isinstance(raw_output, str) else "")
        signature = _decision_signature(payload)
        signature_hash = _decision_signature_hash(payload)
        rows.append(
            {
                "run": index,
                "elapsed_ms": round(elapsed_ms, 2),
                "finish_reason": debug.get("last_finish_reason"),
                "signature_hash": signature_hash,
                "signature": signature,
            }
        )

    unique_signatures = len({row["signature_hash"] for row in rows})
    drift_rate = 0.0 if runs <= 1 else (unique_signatures - 1) / float(runs - 1)
    avg_latency = sum(row["elapsed_ms"] for row in rows) / len(rows) if rows else 0.0

    summary = Table(title="Slow Consistency Summary")
    summary.add_column("Metric")
    summary.add_column("Value")
    summary.add_row("Runs", str(runs))
    summary.add_row("Unique Signatures", str(unique_signatures))
    summary.add_row("Drift Rate", f"{drift_rate:.3f}")
    summary.add_row("Average Latency (ms)", f"{avg_latency:.2f}")
    console.print(summary)

    detail = Table(title="Per-Run Signatures")
    detail.add_column("Run")
    detail.add_column("Latency(ms)")
    detail.add_column("Finish")
    detail.add_column("Signature")
    for row in rows:
        detail.add_row(
            str(row["run"]),
            f"{row['elapsed_ms']:.2f}",
            str(row["finish_reason"] or "unknown"),
            str(row["signature_hash"]),
        )
    console.print(detail)
    typer.echo(
        f"[slow-consistency] runs={runs} unique={unique_signatures} drift={drift_rate:.3f} avg_ms={avg_latency:.2f}",
        err=True,
    )
    for row in rows:
        typer.echo(
            (
                "[slow-consistency-run] "
                f"run={row['run']} ms={row['elapsed_ms']:.2f} "
                f"finish={row['finish_reason'] or 'unknown'} sig={row['signature_hash']}"
            ),
            err=True,
        )

    try:
        slow_scene.close()
    except Exception as exc:
        console.print(f"[yellow]slow_scene.close failed (ignored): {exc}[/yellow]")
