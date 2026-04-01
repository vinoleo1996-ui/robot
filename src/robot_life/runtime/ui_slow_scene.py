from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from hashlib import md5
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Lock, Thread
from time import monotonic
from typing import Any
from urllib.parse import urlparse

from robot_life.common.schemas import SceneCandidate, new_id, now_mono
from robot_life.runtime.sources import CameraSource
from robot_life.slow_scene.service import SlowSceneService

try:  # pragma: no cover - optional visualization dependency
    import cv2 as _cv2
except Exception:  # pragma: no cover - optional dependency
    _cv2 = None

logger = logging.getLogger(__name__)


def _round(value: float) -> float:
    return round(float(value), 2)


def _render_jpeg(frame: Any) -> bytes | None:
    if _cv2 is None:
        return None
    if frame is None or not hasattr(frame, "shape"):
        return None
    try:
        ok, encoded = _cv2.imencode(".jpg", frame, [_cv2.IMWRITE_JPEG_QUALITY, 78])
    except Exception:
        return None
    if not ok:
        return None
    return encoded.tobytes()


def _extract_json_text(raw_text: str) -> str:
    raw = str(raw_text or "").strip()
    if not raw:
        return "{}"
    try:
        parsed = json.loads(raw)
        return json.dumps(parsed, ensure_ascii=False, indent=2)
    except Exception:
        pass
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        candidate = match.group(0)
        try:
            parsed = json.loads(candidate)
            return json.dumps(parsed, ensure_ascii=False, indent=2)
        except Exception:
            return candidate
    return raw


def _frame_digest(frame: Any) -> str:
    if frame is None or not hasattr(frame, "shape"):
        return "no-frame"
    try:
        data = frame.tobytes()
        return md5(data).hexdigest()[:12]
    except Exception:
        return "digest-failed"


def _frame_observation(frame: Any) -> str:
    if frame is None or not hasattr(frame, "shape"):
        return "frame=missing"
    try:
        h, w = frame.shape[:2]
        mean_val = float(frame.mean())
        return f"frame={w}x{h},mean={mean_val:.2f}"
    except Exception:
        return "frame=unknown"


def _natural_scene_summary(scene_json: Any, *, raw_json_text: str | None = None) -> str:
    if raw_json_text:
        try:
            payload = json.loads(raw_json_text)
            if isinstance(payload, dict) and "场景信息" in payload:
                scene_info = payload.get("场景信息", {})
                event_info = payload.get("事件信息", {})
                context_info = payload.get("交互上下文", {})
                decision = payload.get("决策信息", {})
                action = payload.get("执行动作", {})
                room = str(scene_info.get("房间类型", "未知"))
                density = str(scene_info.get("人员活动密度", "未知"))
                risk = str(event_info.get("风险等级", "未知"))
                intent = str(context_info.get("用户可能意图", "未知"))
                speak = str(decision.get("是否说话", "未知"))
                behavior = str(decision.get("交互行为类型", "继续观察"))
                speech = str(action.get("话术模板", ""))
                if speech:
                    return (
                        f"场景在{room}，活动密度={density}，风险={risk}。"
                        f"推测用户意图={intent}；决策={behavior}（是否说话：{speak}）；建议话术：{speech}"
                    )
                return (
                    f"场景在{room}，活动密度={density}，风险={risk}。"
                    f"推测用户意图={intent}；决策={behavior}（是否说话：{speak}）"
                )
        except Exception:
            pass

    if scene_json is None:
        return "暂无场景结论"
    try:
        scene_type = str(getattr(scene_json, "scene_type", "未知场景"))
        confidence = float(getattr(scene_json, "confidence", 0.0))
        emotion = str(getattr(scene_json, "emotion_hint", "未知"))
        urgency = str(getattr(scene_json, "urgency_hint", "低"))
        strategy = str(getattr(scene_json, "recommended_strategy", "继续观察"))
        return (
            f"当前场景={scene_type}，置信度={confidence:.2f}，"
            f"情绪线索={emotion}，紧急度={urgency}，建议={strategy}"
        )
    except Exception:
        return "场景结论解析失败"


def _infer_once(
    *,
    slow_scene: SlowSceneService,
    frame: Any,
    sample_interval_s: float,
) -> tuple[float, str, str]:
    now = monotonic()
    sampled_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    frame_id = _frame_digest(frame)
    frame_obs = _frame_observation(frame)
    scene = SceneCandidate(
        scene_id=new_id(),
        trace_id=new_id(),
        scene_type="ambient_tracking_scene",
        based_on_events=[],
        score_hint=0.5,
        valid_until_monotonic=now_mono() + max(5.0, sample_interval_s * 2.0),
        target_id=None,
        payload={"source": "slow_scene_only"},
    )

    started = monotonic()
    context = (
        "任务前提：家庭机器人主动交互。"
        "请仅基于当前帧填写完整JSON模板，所有字段都要填写自然语言，不能留空，"
        "其中话术模板可短可长、自然口语化。"
        f" 当前采样时间={sampled_at}，当前帧指纹={frame_id}，当前帧观测={frame_obs}。"
        " 必须把“元信息.时间戳”填写为当前采样时间，"
        "并把“元信息.事件ID”填写为包含当前帧指纹的值（例如 EVT-帧指纹）。"
        " 不允许复用历史示例时间或固定事件ID。"
    )
    scene_json = slow_scene.build_scene_json(
        scene,
        image=frame,
        context=context,
    )
    elapsed_ms = (monotonic() - started) * 1000.0
    snapshot = slow_scene.debug_snapshot()
    adapter_debug = snapshot.get("adapter_debug", {}) if isinstance(snapshot, dict) else {}
    raw_output = adapter_debug.get("last_output_text") if isinstance(adapter_debug, dict) else None
    json_text = _extract_json_text(str(raw_output)) if raw_output else "{}"
    summary = _natural_scene_summary(scene_json, raw_json_text=json_text)
    return elapsed_ms, json_text, summary


def build_slow_scene_html(*, refresh_ms: int) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>慢思考单体验证台</title>
  <style>
    :root {{
      --bg: #f6f8ff;
      --card: #ffffff;
      --line: #dbe4f4;
      --ink: #1f2a44;
      --muted: #65708a;
      --accent: #2e8bff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;
      color: var(--ink);
      background: linear-gradient(155deg, #f7f9ff, #fff6ee);
    }}
    .wrap {{
      width: min(1280px, calc(100vw - 20px));
      margin: 14px auto 18px;
    }}
    .hero {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      margin-bottom: 10px;
      gap: 12px;
    }}
    .hero h1 {{
      margin: 0;
      font-size: clamp(20px, 2.2vw, 30px);
      font-weight: 760;
    }}
    .meta {{
      color: var(--muted);
      font-size: 13px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: 1.1fr 1fr;
      gap: 10px;
    }}
    .card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 14px;
      overflow: hidden;
      box-shadow: 0 8px 24px rgba(28, 55, 102, 0.08);
    }}
    .card h3 {{
      margin: 0;
      padding: 10px 12px;
      font-size: 14px;
      border-bottom: 1px solid var(--line);
      background: linear-gradient(180deg, #fff, #f8fbff);
    }}
    .video-box {{
      min-height: 340px;
      display: flex;
      align-items: center;
      justify-content: center;
      background: #f8fbff;
    }}
    .video-box img {{
      width: 100%;
      height: auto;
      display: block;
    }}
    .panel {{
      padding: 10px 12px;
      font-size: 13px;
      line-height: 1.5;
      border-bottom: 1px solid var(--line);
    }}
    .label {{
      color: var(--muted);
    }}
    .value {{
      color: var(--accent);
      font-weight: 650;
    }}
    pre {{
      margin: 0;
      padding: 12px;
      font-size: 12px;
      line-height: 1.45;
      white-space: pre-wrap;
      word-break: break-word;
      max-height: 560px;
      overflow: auto;
      background: #fcfdff;
    }}
    @media (max-width: 980px) {{
      .grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <h1>慢思考单体验证台（仅场景描述）</h1>
      <div class="meta" id="meta">启动中...</div>
    </div>
    <div class="grid">
      <section class="card">
        <h3>摄像头实时画面</h3>
        <div class="video-box">
          <img id="camera-view" alt="camera stream" />
        </div>
      </section>
      <section class="card">
        <h3>慢思考输出（全量 JSON）</h3>
        <div class="panel">
          <div><span class="label">推理周期：</span><span class="value" id="interval">-</span></div>
          <div><span class="label">最近耗时：</span><span class="value" id="latency">-</span></div>
          <div><span class="label">场景描述：</span><span id="summary">暂无结果</span></div>
        </div>
        <pre id="json-text">{{}}</pre>
      </section>
    </div>
  </div>
  <script>
    const REFRESH_MS = {refresh_ms};
    async function refresh() {{
      try {{
        const res = await fetch("/api/state", {{ cache: "no-store" }});
        if (!res.ok) return;
        const state = await res.json();
        document.getElementById("meta").textContent =
          `状态=${{state.error ? "异常" : "运行中"}} | 采样次数=${{state.infer_count}} | 摄像头帧=${{state.camera_frames}}`;
        document.getElementById("interval").textContent = `${{state.sample_interval_s}} 秒`;
        document.getElementById("latency").textContent = state.last_infer_latency_ms > 0
          ? `${{state.last_infer_latency_ms.toFixed(1)}} ms`
          : "-";
        document.getElementById("summary").textContent = state.scene_summary || "暂无结果";
        document.getElementById("json-text").textContent = state.last_json_text || "{{}}";

        const camera = document.getElementById("camera-view");
        if (state.has_camera_frame) {{
          camera.src = `/api/camera.jpg?ts=${{Date.now()}}`;
        }} else {{
          camera.removeAttribute("src");
        }}
      }} catch (_err) {{
      }}
    }}
    refresh();
    setInterval(refresh, REFRESH_MS);
  </script>
</body>
</html>
"""


@dataclass
class SlowSceneState:
    sample_interval_s: float
    _lock: Lock = field(default_factory=Lock, init=False)
    last_error: str | None = field(default=None, init=False)
    camera_frames: int = field(default=0, init=False)
    infer_count: int = field(default=0, init=False)
    last_infer_latency_ms: float = field(default=0.0, init=False)
    _latest_camera_jpeg: bytes | None = field(default=None, init=False)
    last_json_text: str = field(default="{}", init=False)
    scene_summary: str = field(default="暂无场景结论", init=False)

    def set_error(self, message: str) -> None:
        with self._lock:
            self.last_error = message

    def update_frame(self, frame: Any) -> None:
        payload = _render_jpeg(frame)
        if payload is None:
            return
        with self._lock:
            self.camera_frames += 1
            self._latest_camera_jpeg = payload

    def update_infer(
        self,
        *,
        latency_ms: float,
        raw_json_text: str,
        scene_summary: str,
    ) -> None:
        with self._lock:
            self.infer_count += 1
            self.last_infer_latency_ms = _round(latency_ms)
            self.last_json_text = raw_json_text
            self.scene_summary = scene_summary
            self.last_error = None

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "sample_interval_s": self.sample_interval_s,
                "camera_frames": self.camera_frames,
                "infer_count": self.infer_count,
                "last_infer_latency_ms": self.last_infer_latency_ms,
                "last_json_text": self.last_json_text,
                "scene_summary": self.scene_summary,
                "has_camera_frame": self._latest_camera_jpeg is not None,
                "error": self.last_error,
            }

    def camera_jpeg(self) -> bytes | None:
        with self._lock:
            return self._latest_camera_jpeg


def _make_handler(state: SlowSceneState, *, html: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/":
                payload = html.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if parsed.path == "/api/state":
                payload = json.dumps(state.snapshot(), ensure_ascii=False).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if parsed.path == "/api/camera.jpg":
                payload = state.camera_jpeg()
                if payload is None:
                    self.send_response(HTTPStatus.NO_CONTENT)
                    self.end_headers()
                    return
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            self.send_response(HTTPStatus.NOT_FOUND)
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            logger.debug("slow_scene_http: " + format, *args)

    return Handler


def _runtime_worker(
    *,
    camera_source: CameraSource,
    slow_scene: SlowSceneService,
    state: SlowSceneState,
    stop_event: Event,
    sample_interval_s: float,
    read_interval_s: float = 0.03,
) -> None:
    last_submit_at = 0.0
    latest_frame: Any = None
    pending_infer: Future[tuple[float, str, str]] | None = None

    try:
        camera_source.open()
    except Exception as exc:
        state.set_error(f"摄像头打开失败：{exc}")
        return

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="slow-scene-infer")
    try:
        while not stop_event.is_set():
            packet = camera_source.read()
            if packet is not None:
                latest_frame = packet.payload
                state.update_frame(latest_frame)

            now = monotonic()
            if pending_infer is not None and pending_infer.done():
                try:
                    elapsed_ms, json_text, summary = pending_infer.result()
                    state.update_infer(
                        latency_ms=elapsed_ms,
                        raw_json_text=json_text,
                        scene_summary=summary,
                    )
                except Exception as exc:
                    logger.exception("slow-scene inference failed")
                    state.set_error(f"慢思考推理失败：{exc}")
                finally:
                    pending_infer = None

            if latest_frame is not None and pending_infer is None and (now - last_submit_at) >= sample_interval_s:
                frame_for_infer = latest_frame.copy() if hasattr(latest_frame, "copy") else latest_frame
                pending_infer = executor.submit(
                    _infer_once,
                    slow_scene=slow_scene,
                    frame=frame_for_infer,
                    sample_interval_s=sample_interval_s,
                )
                last_submit_at = now

            stop_event.wait(max(0.01, read_interval_s))
    except Exception as exc:
        logger.exception("slow-scene runtime worker failed")
        state.set_error(f"慢思考运行失败：{exc}")
    finally:
        if pending_infer is not None:
            pending_infer.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        camera_source.close()


def run_slow_scene_dashboard(
    *,
    camera_source: CameraSource,
    slow_scene: SlowSceneService,
    host: str = "127.0.0.1",
    port: int = 8771,
    refresh_ms: int = 500,
    sample_interval_s: float = 5.0,
    duration_sec: int = 0,
) -> None:
    state = SlowSceneState(sample_interval_s=max(0.5, float(sample_interval_s)))
    stop_event = Event()
    worker = Thread(
        target=_runtime_worker,
        kwargs={
            "camera_source": camera_source,
            "slow_scene": slow_scene,
            "state": state,
            "stop_event": stop_event,
            "sample_interval_s": max(0.5, float(sample_interval_s)),
        },
        daemon=True,
        name="robot-life-slow-scene-worker",
    )
    worker.start()

    html = build_slow_scene_html(refresh_ms=max(200, int(refresh_ms)))
    handler = _make_handler(state, html=html)
    server = ThreadingHTTPServer((host, int(port)), handler)
    server.timeout = 0.5

    logger.info("slow-scene dashboard serving at http://%s:%s", host, port)
    deadline = monotonic() + duration_sec if duration_sec > 0 else None
    try:
        while not stop_event.is_set():
            server.handle_request()
            if deadline is not None and monotonic() >= deadline:
                break
    finally:
        stop_event.set()
        server.server_close()
        worker.join(timeout=3.0)
