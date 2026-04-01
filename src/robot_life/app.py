from __future__ import annotations

import typer

from robot_life.cli_doctor import detector_status, doctor
from robot_life.cli_live import run, run_live, ui_demo
from robot_life.cli_shared import (
    _audit_detector_model_paths,
    _build_arbitration_runtime,
    _default_arbitration_config_path,
    _default_config_path,
    _default_detector_config_path,
    _default_safety_config_path,
    _default_slow_scene_config_path,
    _default_stabilizer_config_path,
    _resolve_camera_device,
)
from robot_life.cli_slow_scene import slow_consistency, ui_slow


app = typer.Typer(no_args_is_help=False, add_completion=False)

app.command()(doctor)
app.command("detector-status")(detector_status)
app.command()(run)
app.command("run-live")(run_live)
app.command("ui-demo")(ui_demo)
app.command("ui-slow")(ui_slow)
app.command("slow-consistency")(slow_consistency)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
