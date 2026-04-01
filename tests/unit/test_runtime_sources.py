from __future__ import annotations

from concurrent.futures import TimeoutError as FutureTimeoutError
from multiprocessing import shared_memory as mp_shared_memory
from typer.testing import CliRunner
import numpy as np

from robot_life.app import app as robot_life_app
from robot_life.event_engine.arbitration_runtime import ArbitrationRuntime
from robot_life.event_engine.arbitrator import Arbitrator
from robot_life.event_engine.builder import EventBuilder
from robot_life.event_engine.scene_aggregator import SceneAggregator
from robot_life.event_engine.stabilizer import EventStabilizer
from robot_life.runtime import (
    ArecordMicrophoneSource,
    LiveLoop,
    LiveLoopDependencies,
    MicrophoneSource,
    build_live_microphone_source,
    probe_live_microphone_source,
)
from robot_life.runtime.sources import (
    build_live_camera_source,
    CameraSource,
    FramePacket,
    FrameSource,
    ProcessCameraSource,
    SourceBundle,
    SoundDeviceMicrophoneSource,
    SyntheticCameraSource,
    SyntheticMicrophoneSource,
    microphone_source_options_from_detector_cfg,
)


class _FailOpenSource(FrameSource):
    def open(self) -> None:
        raise RuntimeError("open failed")

    def read(self) -> FramePacket | None:
        return None

    def close(self) -> None:
        self._opened = False


class _RecoveringSource(FrameSource):
    def __init__(self, source_name: str):
        super().__init__(source_name=source_name)
        self.read_calls = 0
        self.recover_calls = 0

    def open(self) -> None:
        self._opened = True

    def read(self) -> FramePacket | None:
        self.read_calls += 1
        if self.read_calls == 1:
            raise RuntimeError("read failed once")
        return FramePacket(source=self.source_name, payload={"ok": True}, frame_index=self.read_calls)

    def close(self) -> None:
        self._opened = False

    def recover(self) -> bool:
        self.recover_calls += 1
        self._opened = True
        return True


def test_camera_source_timeout_default_and_lower_bound() -> None:
    default_source = CameraSource()
    clamped_source = CameraSource(read_timeout_s=0.01)
    low_but_valid_source = CameraSource(read_timeout_s=0.05)

    assert default_source.read_timeout_s == 0.12
    assert clamped_source.read_timeout_s == 0.02
    assert low_but_valid_source.read_timeout_s == 0.05


def test_build_live_camera_source_prefers_process_transport_on_darwin(monkeypatch) -> None:
    import robot_life.runtime.sources as sources_mod

    monkeypatch.setattr(sources_mod.sys, "platform", "darwin")
    monkeypatch.delenv("ROBOT_LIFE_CAMERA_PROCESS_CAPTURE", raising=False)

    source = build_live_camera_source(device_index=1, read_timeout_s=0.08)

    assert isinstance(source, ProcessCameraSource)
    assert source.device_index == 1


def test_build_live_camera_source_can_disable_process_transport_via_env(monkeypatch) -> None:
    import robot_life.runtime.sources as sources_mod

    monkeypatch.setattr(sources_mod.sys, "platform", "darwin")
    monkeypatch.setenv("ROBOT_LIFE_CAMERA_PROCESS_CAPTURE", "0")

    source = build_live_camera_source(device_index=2, read_timeout_s=0.08)

    assert isinstance(source, CameraSource)
    assert source.device_index == 2


def test_process_camera_source_attempts_recovery_when_worker_is_dead(monkeypatch) -> None:
    source = ProcessCameraSource(device_index=3, read_timeout_s=0.05)
    source._opened = True
    source._opened_at = 1.0

    class _DeadProcess:
        def is_alive(self) -> bool:
            return False

    class _EmptyQueue:
        def get_nowait(self):
            raise __import__("queue").Empty()

    recover_calls: list[bool] = []

    monkeypatch.setattr(source, "_process", _DeadProcess())
    monkeypatch.setattr(source, "_frame_queue", _EmptyQueue())
    monkeypatch.setattr("robot_life.runtime.sources.monotonic", lambda: 3.0)
    monkeypatch.setattr(source, "recover", lambda: recover_calls.append(True) or True)

    packet = source.read()

    assert packet is None
    assert recover_calls == [True]


def test_process_camera_source_reads_frame_from_shared_memory() -> None:
    source = ProcessCameraSource(device_index=3, read_timeout_s=0.05, width=4, height=3)
    source._opened = True
    source._shared_frame_lock = __import__("threading").Lock()
    shm = mp_shared_memory.SharedMemory(create=True, size=source._shared_frame_capacity)
    source._shared_frame = shm
    frame = np.arange(3 * 4 * 3, dtype=np.uint8).reshape(3, 4, 3)
    shm.buf[: frame.nbytes] = frame.reshape(-1)

    class _Queue:
        def __init__(self) -> None:
            self._used = False

        def get_nowait(self):
            if self._used:
                raise __import__("queue").Empty()
            self._used = True
            return {
                "frame_index": 7,
                "backend": "AVFOUNDATION",
                "shape": frame.shape,
                "frame_bytes": frame.nbytes,
            }

    source._frame_queue = _Queue()

    try:
        packet = source.read()
    finally:
        source.close()

    assert packet is not None
    assert packet.frame_index == 7
    assert packet.metadata["camera_transport"] == "process_shared_memory"
    assert np.array_equal(packet.payload, frame)


def test_camera_source_shared_executor_reference_lifecycle() -> None:
    if CameraSource._shared_executor_workers <= 0:
        try:
            CameraSource._acquire_shared_executor()
        except RuntimeError as exc:
            assert "disabled" in str(exc)
        else:
            raise AssertionError("expected executor acquisition to be disabled on this platform")
        return

    first = CameraSource._acquire_shared_executor()
    second = CameraSource._acquire_shared_executor()
    assert first is second
    assert CameraSource._shared_executor_ref_count >= 2

    CameraSource._release_shared_executor(first)
    assert CameraSource._shared_executor is not None
    CameraSource._release_shared_executor(second)
    assert CameraSource._shared_executor is None


def test_camera_source_read_timeout_reuses_single_inflight_future() -> None:
    source = CameraSource()

    class _FakeFuture:
        def __init__(self) -> None:
            self.calls = 0

        def result(self, timeout=None):
            self.calls += 1
            raise FutureTimeoutError()

        def cancel(self) -> bool:
            return True

    class _FakeExecutor:
        def __init__(self, future: _FakeFuture) -> None:
            self.future = future
            self.submit_calls = 0

        def submit(self, fn):
            self.submit_calls += 1
            return self.future

    class _FakeCapture:
        def read(self):
            return True, {"ok": True}

    future = _FakeFuture()
    executor = _FakeExecutor(future)
    source._capture = _FakeCapture()
    source._opened = True
    source._read_executor = executor  # type: ignore[assignment]

    first = source._read_once()
    second = source._read_once()

    assert first == (False, None)
    assert second == (False, None)
    assert executor.submit_calls == 1
    assert future.calls == 2


def test_run_live_accepts_camera_read_timeout_option() -> None:
    result = CliRunner().invoke(
        robot_life_app,
        ["run-live", "--iterations", "1", "--camera-read-timeout-ms", "20"],
    )

    assert result.exit_code == 0
    assert "camera_read_timeout_ms=20" in result.stdout


def test_source_bundle_open_all_tolerates_open_failures() -> None:
    bundle = SourceBundle(camera=_FailOpenSource("camera"))
    bundle.open_all()
    assert bundle.camera is not None
    assert bundle.camera.is_open is False


def test_live_loop_start_tolerates_source_open_failures() -> None:
    loop = LiveLoop(
        registry=type(
            "_EmptyRegistry",
            (),
            {
                "initialize_all": staticmethod(lambda: None),
                "close_all": staticmethod(lambda: None),
                "process_all": staticmethod(lambda _frames: []),
            },
        )(),
        source_bundle=SourceBundle(camera=_FailOpenSource("camera")),
        dependencies=LiveLoopDependencies(
            builder=EventBuilder(),
            stabilizer=EventStabilizer(
                debounce_count=1,
                cooldown_ms=0,
                hysteresis_threshold=0.0,
                dedup_window_ms=0,
            ),
            aggregator=SceneAggregator(),
            arbitrator=Arbitrator(),
            arbitration_runtime=ArbitrationRuntime(arbitrator=Arbitrator()),
        ),
    )

    loop.start()
    try:
        assert loop.is_running is True
        result = loop.run_once()
        assert result.collected_frames.frames == {}
    finally:
        loop.stop()


def test_source_bundle_recovers_after_read_exception() -> None:
    source = _RecoveringSource("camera")
    source.open()
    bundle = SourceBundle(camera=source)

    first = bundle.read_packets()
    second = bundle.read_packets()

    assert first == {}
    assert "camera" in second
    assert source.recover_calls == 1


def test_synthetic_camera_source_emits_frames() -> None:
    source = SyntheticCameraSource()
    source.open()
    packet = source.read()
    source.close()

    assert packet is not None
    assert packet.source == "camera"
    assert packet.payload["synthetic_frame"] is True


def test_synthetic_microphone_source_emits_packets() -> None:
    source = SyntheticMicrophoneSource()
    source.open()
    packet = source.read()
    source.close()

    assert packet is not None
    assert packet.source == "microphone"
    assert packet.payload["synthetic_audio"] is True


def test_sounddevice_microphone_read_before_open_returns_none() -> None:
    source = SoundDeviceMicrophoneSource()
    assert source.read() is None


def test_sounddevice_microphone_source_tracks_dropped_packets() -> None:
    source = SoundDeviceMicrophoneSource(max_buffer_packets=2)
    source._enqueue_packet(FramePacket(source="microphone", payload={"i": 1}, frame_index=1))
    source._enqueue_packet(FramePacket(source="microphone", payload={"i": 2}, frame_index=2))
    source._enqueue_packet(FramePacket(source="microphone", payload={"i": 3}, frame_index=3))

    health = source.snapshot_health()
    assert health["max_buffer_packets"] == 2
    assert health["dropped_packets"] == 1
    assert health["buffer_depth"] == 2
    assert "audio_rms" in health
    assert "audio_db" in health


def test_sounddevice_microphone_source_computes_audio_levels() -> None:
    source = SoundDeviceMicrophoneSource()

    rms, db = source._compute_level([0.5, -0.5, 0.5, -0.5])

    assert rms is not None and 0.49 < rms < 0.51
    assert db is not None and -7.0 < db < -5.0


def test_build_live_microphone_source_falls_back_to_arecord_when_sounddevice_is_unavailable(
    monkeypatch,
) -> None:
    import builtins
    import robot_life.runtime.sources as sources_mod

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "sounddevice":
            raise OSError("PortAudio library not found")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(sources_mod.shutil, "which", lambda cmd: "/usr/bin/arecord" if cmd == "arecord" else None)

    source, warning = build_live_microphone_source()

    assert isinstance(source, ArecordMicrophoneSource)
    assert warning is not None
    assert "arecord" in warning


def test_build_live_microphone_source_falls_back_to_silent_when_no_input_devices(
    monkeypatch,
) -> None:
    import builtins
    import robot_life.runtime.sources as sources_mod

    real_import = builtins.__import__

    class _FakeDefault:
        device = (-1, -1)

    class _FakeSoundDevice:
        default = _FakeDefault()

        @staticmethod
        def query_devices(index=None, kind=None):
            if index is not None:
                raise ValueError("no default input")
            return [{"name": "Output Only", "max_input_channels": 0}]

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "sounddevice":
            return _FakeSoundDevice
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(sources_mod.shutil, "which", lambda cmd: None)

    source, warning = build_live_microphone_source()

    assert isinstance(source, MicrophoneSource)
    assert warning is not None
    assert "未发现可用输入设备" in warning


def test_probe_live_microphone_source_reports_fallback_metadata(monkeypatch) -> None:
    import builtins
    import robot_life.runtime.sources as sources_mod

    real_import = builtins.__import__

    class _FakeDefault:
        device = (-1, -1)

    class _FakeSoundDevice:
        default = _FakeDefault()

        @staticmethod
        def query_devices(index=None, kind=None):
            if index is not None:
                raise ValueError("no default input")
            return [{"name": "Output Only", "max_input_channels": 0}]

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "sounddevice":
            return _FakeSoundDevice
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(sources_mod.shutil, "which", lambda cmd: None)

    probe = probe_live_microphone_source()

    assert isinstance(probe.source, MicrophoneSource)
    assert probe.mode == "fallback"
    assert probe.backend == "silent"
    assert probe.input_device_count == 0
    assert probe.warning is not None


def test_probe_live_microphone_source_accepts_sounddevice_devicelist(monkeypatch) -> None:
    import builtins

    real_import = builtins.__import__

    class _FakeDefault:
        device = [1, 2]

    class _FakeDeviceList:
        def __init__(self, items):
            self._items = items

        def __iter__(self):
            return iter(self._items)

        def __len__(self):
            return len(self._items)

    class _FakeSoundDevice:
        default = _FakeDefault()

        @staticmethod
        def query_devices(index=None, kind=None):
            if index is not None:
                return {"name": "MacBook Pro麦克风", "max_input_channels": 1}
            return _FakeDeviceList(
                [
                    {"name": "Output Only", "max_input_channels": 0},
                    {"name": "MacBook Pro麦克风", "max_input_channels": 1},
                ]
            )

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "sounddevice":
            return _FakeSoundDevice
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    probe = probe_live_microphone_source()

    assert isinstance(probe.source, SoundDeviceMicrophoneSource)
    assert probe.mode == "real"
    assert probe.backend == "sounddevice"
    assert probe.input_device_count == 1
    assert probe.selected_device == 1
    assert probe.selected_device_name == "MacBook Pro麦克风"
    assert probe.input_device_names == ["MacBook Pro麦克风"]


def test_probe_live_microphone_source_prefers_builtin_input_when_default_missing(monkeypatch) -> None:
    import builtins

    real_import = builtins.__import__

    class _FakeDefault:
        device = (-1, -1)

    class _FakeSoundDevice:
        default = _FakeDefault()

        @staticmethod
        def query_devices(index=None, kind=None):
            devices = [
                {"name": "ZoomAudioDevice", "max_input_channels": 1},
                {"name": "MacBook Pro麦克风", "max_input_channels": 1},
                {"name": "LarkAudioDevice", "max_input_channels": 1},
            ]
            if index is None:
                return devices
            return devices[int(index)]

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "sounddevice":
            return _FakeSoundDevice
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    probe = probe_live_microphone_source(prefer_builtin=True)

    assert isinstance(probe.source, SoundDeviceMicrophoneSource)
    assert probe.selected_device == 1
    assert probe.selected_device_name == "MacBook Pro麦克风"


def test_microphone_source_options_from_detector_cfg_reads_runtime_tuning() -> None:
    options = microphone_source_options_from_detector_cfg(
        {
            "detector_global": {
                "microphone_prefer_builtin": True,
                "microphone_preferred_device": "MacBook Pro麦克风",
                "microphone_sample_rate": 16000,
                "microphone_channels": 1,
                "microphone_blocksize": 2048,
                "microphone_max_buffer_packets": 48,
            }
        }
    )

    assert options["prefer_builtin"] is True
    assert options["preferred_device"] == "MacBook Pro麦克风"
    assert options["sample_rate"] == 16000
    assert options["channels"] == 1
    assert options["blocksize"] == 2048
    assert options["max_buffer_packets"] == 48


def test_build_live_microphone_source_uses_custom_blocksize(monkeypatch) -> None:
    import builtins

    real_import = builtins.__import__

    class _FakeDefault:
        device = [0, -1]

    class _FakeSoundDevice:
        default = _FakeDefault()

        @staticmethod
        def query_devices(index=None, kind=None):
            devices = [{"name": "MacBook Pro麦克风", "max_input_channels": 1}]
            if index is None:
                return devices
            return devices[int(index)]

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "sounddevice":
            return _FakeSoundDevice
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    source, warning = build_live_microphone_source(blocksize=2048, max_buffer_packets=48)

    assert isinstance(source, SoundDeviceMicrophoneSource)
    assert source.blocksize == 2048
    assert source.max_buffer_packets == 48
    assert warning is None


def test_arecord_microphone_source_decodes_raw_pcm(monkeypatch) -> None:
    import io
    import subprocess
    import time
    import numpy as np
    import robot_life.runtime.sources as sources_mod

    class _FakeProcess:
        def __init__(self) -> None:
            samples = np.array([0, 16384, -16384, 32767], dtype=np.int16).tobytes()
            self.stdout = io.BytesIO(samples)
            self.stderr = io.BytesIO()
            self.returncode = None

        def terminate(self) -> None:
            self.returncode = 0

        def wait(self, timeout: float | None = None) -> int:
            self.returncode = 0
            return 0

        def kill(self) -> None:
            self.returncode = -9

    monkeypatch.setattr(sources_mod.shutil, "which", lambda cmd: "/usr/bin/arecord" if cmd == "arecord" else None)
    monkeypatch.setattr(sources_mod.subprocess, "Popen", lambda *args, **kwargs: _FakeProcess())

    source = ArecordMicrophoneSource(chunk_frames=4, channels=1, sample_rate=16000)
    source.open()

    deadline = time.monotonic() + 1.0
    packet = None
    while time.monotonic() < deadline:
        packet = source.read()
        if packet is not None:
            break
        time.sleep(0.01)

    source.close()

    assert packet is not None
    assert packet.source == "microphone"
    assert packet.payload["source_kind"] == "arecord"
    assert packet.payload["sample_rate"] == 16000
    assert packet.payload["channels"] == 1
    assert packet.payload["audio"].shape[0] == 4
