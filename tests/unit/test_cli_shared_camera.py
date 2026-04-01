from __future__ import annotations

from types import SimpleNamespace
import sys

import robot_life.cli_shared as cli_shared


class _FakeCapture:
    def __init__(self, succeed_on_attempt: int, tracker: dict[str, int]):
        self._succeed_on_attempt = succeed_on_attempt
        self._tracker = tracker

    def isOpened(self) -> bool:
        self._tracker["opened"] += 1
        return self._tracker["attempt"] >= self._succeed_on_attempt

    def read(self) -> tuple[bool, object | None]:
        if self._tracker["attempt"] >= self._succeed_on_attempt:
            return True, object()
        return False, None

    def release(self) -> None:
        return None


def test_probe_camera_index_retries_until_success(monkeypatch) -> None:
    tracker = {"attempt": 0, "opened": 0}

    def fake_videocapture(index: int, backend: int | None = None) -> _FakeCapture:
        tracker["attempt"] += 1
        return _FakeCapture(succeed_on_attempt=2, tracker=tracker)

    fake_cv2 = SimpleNamespace(VideoCapture=fake_videocapture, CAP_AVFOUNDATION=1200)
    monkeypatch.setitem(sys.modules, "cv2", fake_cv2)
    monkeypatch.setattr(cli_shared, "sleep", lambda _seconds: None)
    monkeypatch.setattr(cli_shared, "_darwin_camera_policy", lambda: "any")

    assert cli_shared._probe_camera_index(2) is True
    assert tracker["attempt"] >= 2


def test_probe_camera_index_returns_false_after_retries(monkeypatch) -> None:
    tracker = {"attempt": 0, "opened": 0}

    def fake_videocapture(index: int, backend: int | None = None) -> _FakeCapture:
        tracker["attempt"] += 1
        return _FakeCapture(succeed_on_attempt=99, tracker=tracker)

    fake_cv2 = SimpleNamespace(VideoCapture=fake_videocapture, CAP_AVFOUNDATION=1200)
    monkeypatch.setitem(sys.modules, "cv2", fake_cv2)
    monkeypatch.setattr(cli_shared, "sleep", lambda _seconds: None)
    monkeypatch.setattr(cli_shared, "_darwin_camera_policy", lambda: "any")

    assert cli_shared._probe_camera_index(2) is False
    assert tracker["attempt"] == 9


def test_resolve_camera_device_remaps_when_allowed(monkeypatch) -> None:
    monkeypatch.setattr(cli_shared, "_darwin_camera_policy", lambda: "any")
    monkeypatch.setattr(cli_shared, "_discover_camera_candidates", lambda max_probe_index=10: [0, 1, 2])

    def fake_probe(index: int) -> bool:
        return index == 1

    monkeypatch.setattr(cli_shared, "_probe_camera_index", fake_probe)

    resolved, usable = cli_shared._resolve_camera_device(2, allow_remap=True)
    assert resolved == 1
    assert usable == [1]


def test_resolve_camera_device_fails_fast_when_strict(monkeypatch) -> None:
    monkeypatch.setattr(cli_shared, "_darwin_camera_policy", lambda: "any")
    monkeypatch.setattr(cli_shared, "_discover_camera_candidates", lambda max_probe_index=10: [0, 1, 2])
    monkeypatch.setattr(cli_shared, "_probe_camera_index", lambda _index: False)

    try:
        cli_shared._resolve_camera_device(2, allow_remap=False)
    except RuntimeError as exc:
        assert "索引 2 不可用" in str(exc)
    else:
        raise AssertionError("expected RuntimeError when strict camera index is unavailable")


def test_preferred_darwin_builtin_camera_index_uses_avfoundation_order_without_probe(monkeypatch) -> None:
    devices = [
        {
            "name": "FaceTime高清相机",
            "active_size": (1280, 720),
            "sizes": {(640, 480), (1280, 720)},
            "builtin_score": 300,
        },
        {
            "name": "“Vino Leo”的相机",
            "active_size": (640, 480),
            "sizes": {(640, 480), (1280, 720), (1920, 1080)},
            "builtin_score": -100,
        },
    ]
    monkeypatch.setattr(cli_shared, "_darwin_list_video_devices", lambda: list(devices))
    monkeypatch.setattr(
        cli_shared,
        "_probe_camera_descriptor",
        lambda _index: (_ for _ in ()).throw(AssertionError("should not probe camera candidates on darwin")),
    )

    assert cli_shared._preferred_darwin_builtin_camera_index() == 1


def test_resolve_camera_device_prefers_builtin_camera_on_darwin(monkeypatch) -> None:
    monkeypatch.setattr(cli_shared, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(cli_shared, "_darwin_camera_policy", lambda: "builtin_only")
    monkeypatch.setattr(cli_shared, "_preferred_darwin_builtin_camera_index", lambda max_probe_index=10: 1)
    monkeypatch.setattr(cli_shared, "_probe_camera_index", lambda index: index == 1)

    resolved, usable = cli_shared._resolve_camera_device(0, allow_remap=True)

    assert resolved == 1
    assert usable == [1]


def test_resolve_camera_device_refuses_phone_fallback_when_builtin_is_ambiguous(monkeypatch) -> None:
    monkeypatch.setattr(cli_shared, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(cli_shared, "_darwin_camera_policy", lambda: "builtin_only")
    monkeypatch.setattr(cli_shared, "_preferred_darwin_builtin_camera_index", lambda max_probe_index=10: None)

    try:
        cli_shared._resolve_camera_device(0, allow_remap=True)
    except RuntimeError as exc:
        assert "避免误连 iPhone" in str(exc)
    else:
        raise AssertionError("expected RuntimeError when builtin camera cannot be identified")
