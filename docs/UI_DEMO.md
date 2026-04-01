# UI Demo Quick Start

## 1) Mock mode (fast verify)

```bash
python3 -m robot_life.app ui-demo --config configs/runtime/app.default.yaml --port 8765
```

Open browser:

```text
http://127.0.0.1:8765
```

## 2) Live camera mode (4090 machine)

```bash
python3 -m robot_life.app ui-demo \
  --config configs/runtime/desktop_4090/desktop_4090.yaml \
  --detectors configs/detectors/desktop_4090/desktop_4090.yaml \
  --camera-device 5 \
  --port 8765
```

If you also want slow scene:

```bash
python3 -m robot_life.app ui-demo \
  --config configs/runtime/desktop_4090/desktop_4090.yaml \
  --detectors configs/detectors/desktop_4090/desktop_4090.yaml \
  --camera-device 5 \
  --enable-slow-scene \
  --port 8765
```

## 3) Useful flags

- `--host`: bind host, default `127.0.0.1`
- `--refresh-ms`: browser polling interval, default `500`
- `--poll-interval`: runtime loop interval in seconds, default `1/30`
- `--duration-sec`: auto stop seconds, `0` means run until `Ctrl+C`

## 3.5) Stable long-running mode (recommended for local camera experience)

Use the built-in daemon launcher with conservative resource profile:

```bash
scripts/launch/run_ui_stable.sh start
scripts/launch/run_ui_stable.sh status
```

Open browser:

```text
http://127.0.0.1:8765
```

Stop it:

```bash
scripts/launch/run_ui_stable.sh stop
```

## 3.6) Fast-Reaction only mode (recommended while收敛快反应)

Use the dedicated fast-only launcher. This profile fixes all five fast pipelines to the current Phase 1 baseline and does not enable slow-scene sidecar.

```bash
scripts/launch/run_ui_fast_reaction.sh start
scripts/launch/run_ui_fast_reaction.sh status
```

Open browser:

```text
http://127.0.0.1:8764
```

Stop it:

```bash
scripts/launch/run_ui_fast_reaction.sh stop
```

## 4) What you can see in UI

- Realtime loop FPS and latency
- Live camera picture (`/api/camera.jpg`) with detection overlays when bbox exists
- Result console: "I see" + "I will react" + scene + decision
- Detections / stable events / executions counters
- Latest detections
- Scene + behavior decisions
- Event feed (helps check "not too quiet, not too noisy")
- Observability cards: queue pending / preemptions / slow queue depth / stabilizer pass rate
- Stabilizer + arbitration table (filter reasons and queue/drop/execute outcome counters)
- Resources + slow brain table (resource owners/ttl and slow-scene health counters)
- Slow brain IO rows: `slow_input` / `slow_output` and whether local Qwen adapter is loaded
