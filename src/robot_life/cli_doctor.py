from __future__ import annotations

from pathlib import Path

import typer
from rich.table import Table

from robot_life.cli_shared import console, _default_config_path, _default_detector_config_path
from robot_life.common.config import load_app_config
from robot_life.common.logging import configure_logging
from robot_life.runtime import build_pipeline_registry, load_detector_config


def doctor(
    config: Path = typer.Option(_default_config_path(), exists=True, readable=True),
) -> None:
    """Show the current scaffold configuration and main directories."""
    app_config = load_app_config(config)
    table = Table(title="Robot Life Desktop MVP")
    table.add_column("Item")
    table.add_column("Value")
    table.add_row("Project", "robot-life-dev")
    table.add_row("Config", str(config))
    table.add_row("Project Root", str(app_config.runtime.project_root))
    table.add_row("Trace Enabled", str(app_config.runtime.trace_enabled))
    table.add_row("Mock Drivers", str(app_config.runtime.mock_drivers))
    table.add_row("Perception Pipelines", ", ".join(app_config.runtime.enabled_pipelines))
    console.print(table)


def detector_status(
    config: Path = typer.Option(_default_config_path(), exists=True, readable=True),
    detectors: Path = typer.Option(_default_detector_config_path(), exists=True, readable=True),
) -> None:
    """Show detector pipeline availability and fallback reasons."""
    app_config = load_app_config(config)
    configure_logging(app_config.runtime.log_level)
    detector_cfg = load_detector_config(detectors)
    registry = build_pipeline_registry(
        app_config.runtime.enabled_pipelines,
        detector_cfg,
        mock_drivers=app_config.runtime.mock_drivers,
    )
    registry.initialize_all()

    table = Table(title="Detector Status")
    table.add_column("Pipeline")
    table.add_column("Enabled")
    table.add_column("Status")
    table.add_column("Implementation")
    table.add_column("Reason")
    pipeline_statuses = registry.snapshot_pipeline_statuses()

    for pipeline_name in registry.list_pipelines():
        status = pipeline_statuses.get(pipeline_name)
        if status is None:
            table.add_row(pipeline_name, "false", "missing", "none", "not_registered")
            continue
        table.add_row(
            pipeline_name,
            str(bool(status.get("enabled", False))).lower(),
            str(status.get("init_status", "pending")),
            str(status.get("implementation", "unknown")),
            str(status.get("reason", "")),
        )

    registry.close_all()
    console.print(table)
