from pathlib import Path

from robot_life.common.config import (
    load_app_config,
    load_arbitration_config,
    load_safety_config,
    load_slow_scene_config,
    load_stabilizer_config,
)


def test_default_config_files_exist() -> None:
    root = Path(__file__).resolve().parents[2]
    expected = [
        root / "configs" / "runtime" / "app.default.yaml",
        root / "configs" / "detectors" / "local" / "local_mac_fast_reaction.yaml",
        root / "configs" / "slow_scene" / "default.yaml",
        root / "configs" / "stabilizer" / "default.yaml",
        root / "configs" / "arbitration" / "default.yaml",
        root / "configs" / "safety" / "default.yaml",
    ]
    missing = [str(path) for path in expected if not path.exists()]
    assert not missing, f"missing default configs: {missing}"


def test_default_configs_load() -> None:
    root = Path(__file__).resolve().parents[2]
    app = load_app_config(root / "configs" / "runtime" / "app.default.yaml")
    arbitration = load_arbitration_config(root / "configs" / "arbitration" / "default.yaml")
    stabilizer = load_stabilizer_config(root / "configs" / "stabilizer" / "default.yaml")
    slow_scene = load_slow_scene_config(root / "configs" / "slow_scene" / "default.yaml")
    safety = load_safety_config(root / "configs" / "safety" / "default.yaml")

    assert app.runtime.enabled_pipelines
    assert arbitration.queue['max_size'] >= 1
    assert stabilizer.default_ttl_ms > 0
    assert slow_scene.request_timeout_ms > 0
    assert safety.enabled is True
