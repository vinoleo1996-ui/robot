from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ProfileSpec:
    key: str
    runtime_config: Path
    detector_config: Path
    required_pipelines: tuple[str, ...]
    stabilizer_config: Path | None = None
    arbitration_config: Path | None = None
    safety_config: Path | None = None
    smoke_runtime_config: Path | None = None
    default_camera_timeout_ms: int = 120
    default_refresh_ms: int = 250


def _cfg(*parts: str) -> Path:
    return PROJECT_ROOT.joinpath("configs", *parts)


PROFILE_SPECS: dict[str, ProfileSpec] = {
    "mock": ProfileSpec(
        key="mock",
        runtime_config=_cfg("runtime", "app.default.yaml"),
        smoke_runtime_config=_cfg("runtime", "app.default.yaml"),
        detector_config=_cfg("detectors", "default.yaml"),
        required_pipelines=("face", "gesture", "gaze", "audio", "motion"),
        default_camera_timeout_ms=120,
        default_refresh_ms=150,
    ),
    "local_mac": ProfileSpec(
        key="local_mac",
        runtime_config=_cfg("runtime", "local", "local_mac_fast_reaction.yaml"),
        smoke_runtime_config=_cfg("runtime", "local", "local_mac_fast_reaction.smoke.yaml"),
        detector_config=_cfg("detectors", "local", "local_mac_fast_reaction.yaml"),
        stabilizer_config=_cfg("stabilizer", "local", "local_mac_fast_reaction.yaml"),
        arbitration_config=_cfg("arbitration", "default.yaml"),
        safety_config=_cfg("safety", "default.yaml"),
        required_pipelines=("face", "gesture", "gaze", "audio", "motion"),
        default_camera_timeout_ms=500,
        default_refresh_ms=320,
    ),
    "local_mac_full_gpu": ProfileSpec(
        key="local_mac_full_gpu",
        runtime_config=_cfg("runtime", "local", "local_mac_fast_reaction_full_gpu.yaml"),
        detector_config=_cfg("detectors", "local", "local_mac_fast_reaction_full_gpu.yaml"),
        stabilizer_config=_cfg("stabilizer", "local", "local_mac_fast_reaction.yaml"),
        arbitration_config=_cfg("arbitration", "default.yaml"),
        safety_config=_cfg("safety", "default.yaml"),
        required_pipelines=("face", "gesture", "gaze", "audio", "motion"),
        default_camera_timeout_ms=500,
        default_refresh_ms=360,
    ),
    "local_mac_lite": ProfileSpec(
        key="local_mac_lite",
        runtime_config=_cfg("runtime", "local", "local_mac_fast_reaction_lite.yaml"),
        smoke_runtime_config=_cfg("runtime", "local", "local_mac_fast_reaction_lite.smoke.yaml"),
        detector_config=_cfg("detectors", "local", "local_mac_fast_reaction_lite.yaml"),
        stabilizer_config=_cfg("stabilizer", "local", "local_mac_fast_reaction.yaml"),
        arbitration_config=_cfg("arbitration", "default.yaml"),
        safety_config=_cfg("safety", "default.yaml"),
        required_pipelines=("face", "audio", "motion"),
        default_camera_timeout_ms=500,
        default_refresh_ms=300,
    ),
    "local_mac_realtime": ProfileSpec(
        key="local_mac_realtime",
        runtime_config=_cfg("runtime", "local", "local_mac_fast_reaction_realtime.yaml"),
        smoke_runtime_config=_cfg("runtime", "local", "local_mac_fast_reaction_realtime.smoke.yaml"),
        detector_config=_cfg("detectors", "local", "local_mac_fast_reaction_realtime.yaml"),
        stabilizer_config=_cfg("stabilizer", "local", "local_mac_fast_reaction.yaml"),
        arbitration_config=_cfg("arbitration", "default.yaml"),
        safety_config=_cfg("safety", "default.yaml"),
        required_pipelines=("face", "gesture", "gaze", "audio", "motion"),
        default_camera_timeout_ms=500,
        default_refresh_ms=260,
    ),
    "desktop_4090": ProfileSpec(
        key="desktop_4090",
        runtime_config=_cfg("runtime", "desktop_4090", "desktop_4090.yaml"),
        smoke_runtime_config=_cfg("runtime", "desktop_4090", "desktop_4090.smoke.yaml"),
        detector_config=_cfg("detectors", "desktop_4090", "desktop_4090.yaml"),
        stabilizer_config=_cfg("stabilizer", "desktop_4090_stable.yaml"),
        arbitration_config=_cfg("arbitration", "default.yaml"),
        safety_config=_cfg("safety", "default.yaml"),
        required_pipelines=("face", "gesture", "gaze", "audio", "motion"),
        default_camera_timeout_ms=120,
        default_refresh_ms=150,
    ),
}


PROFILE_ALIASES: dict[str, str] = {
    "full": "local_mac",
    "hybrid": "local_mac",
    "local_mac": "local_mac",
    "full-gpu": "local_mac_full_gpu",
    "local_mac_full_gpu": "local_mac_full_gpu",
    "lite": "local_mac_lite",
    "local_mac_lite": "local_mac_lite",
    "realtime": "local_mac_realtime",
    "local_mac_realtime": "local_mac_realtime",
    "mock": "mock",
    "desktop_4090": "desktop_4090",
}


def canonical_profile_key(name: str) -> str:
    normalized = str(name).strip()
    if not normalized:
        raise KeyError("profile name is empty")
    resolved = PROFILE_ALIASES.get(normalized, normalized)
    if resolved not in PROFILE_SPECS:
        raise KeyError(f"unknown profile: {name}")
    return resolved


def get_profile_spec(name: str) -> ProfileSpec:
    return PROFILE_SPECS[canonical_profile_key(name)]


def smoke_profile_choices() -> tuple[str, ...]:
    return ("mock", "local_mac", "local_mac_lite", "local_mac_realtime", "desktop_4090")


def launcher_profile_choices() -> tuple[str, ...]:
    return ("hybrid", "full-gpu", "lite", "realtime")
