# System Architecture

## Layering

1. `perception/*`  
   adapters for face/audio/motion/pose and slow-scene sensors.
2. `event_engine/*`  
   raw-event stabilization, scene aggregation, and arbitration.
3. `runtime/*`  
   loop scheduling, queueing, load management, telemetry.
4. `behavior/*`  
   behavior-tree and execution lifecycle.
5. `bridge/*`  
   external integration (debug UI, transport, observability endpoints).

`bridge` is intentionally outside runtime core dependencies.

## Current Status

### Already Implemented

- `event_engine` remains the decision core.
- `runtime/live_loop` handles ingest, stabilization, aggregation, and arbitration.
- `DeepStreamAdapter` converts backend metadata into the shared `DetectionResult` contract.
- `DetectionEventInjector` converts `DetectionResult` into `RawEvent` with dedupe and batch caps.
- `RuntimeHealthMonitor` models phased startup and component health.
- `robot_life_cpp_main deepstream-backend` exists as a separate backend process entrypoint.
- The launcher path now runs in phases: `env -> backend -> core -> ui`.

### Skeleton Only

- `DeepStreamFourVisionGraph` currently provides four-branch structure, branch metrics, sampling, and configuration knobs.
- `linux_deepstream_4vision` currently uses the mock backend graph path, not a real NVIDIA DeepStream pipeline.
- IPC is currently a line-delimited stdout pipe, suitable for local process integration, not final production transport.

### Not Yet Implemented

- Real DeepStream branch bindings for face, pose-gesture, motion, and scene-object.
- Real `nvinfer` / tracker graph configuration.
- Production transport hardening such as socket, gRPC, or ZeroMQ.
- Real GPU benchmark numbers for the DeepStream production path.

## State machine

Global runtime state:

- `BOOTING` -> `WARMING` -> `RUNNING` -> `DEGRADED` -> `STOPPING` -> `STOPPED`

Per-scene arbitration state:

- `IDLE` -> `PENDING` -> `EXECUTING` -> `COOLDOWN` -> `IDLE`

## Event detection frequency

- Camera/frame ingestion: target 30 FPS
- Motion branch: 30 FPS, CPU fast path
- Face/Pose branch: 10-15 FPS effective sampling
- Audio branch: 20-50 ms chunking
- Arbitration tick: 20-30 Hz

## Priorities

- `P0`: safety-critical interrupt (hard interrupt)
- `P1`: interaction-critical (soft/hard interrupt by policy)
- `P2`: contextual response
- `P3`: background/idle updates

## Backend Boundaries

- `native` backend: local development path and fallback path
- `deepstream` backend: process boundary and adapter path for four-vision integration
- `event_engine`: does not know whether events came from native or DeepStream
- `behavior`: does not know whether events came from native or DeepStream

## Cooldown logic

- event-level cooldown: prevents duplicate trigger storms
- scene-level cooldown: prevents repeated behavior thrashing
- behavior-level cooldown: enforces minimum execution spacing

## Debug UI boundary

Debug UI is a bridge concern only:

- reads runtime snapshots over HTTP/IPC
- never writes into event-engine internals directly
- never owns synchronization primitives inside runtime loop

Any parameter hot-update should be applied through validated runtime config APIs,
not by direct UI-thread mutation of runtime structures.
