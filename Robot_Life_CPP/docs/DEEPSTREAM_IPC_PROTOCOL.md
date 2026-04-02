# DeepStream IPC Protocol

## Goal

Provide a minimal process boundary between the DeepStream backend process and the core runtime process.

## Transport

- Current transport: child process `stdout` pipe
- Current framing: one line per message
- Intended upgrade path: local socket, ZeroMQ, or gRPC without changing the upper event contract

## Message Types

### Health

```text
HEALTH|<state>|<detail>
```

States currently used:

- `starting`
- `warming`
- `ready`
- `stopping`
- `restarting`
- `failed`

### Detection

```text
DETECTION|<trace_id>|<source>|<detector>|<event_type>|<timestamp>|<confidence>|<payload>
```

Payload is encoded as:

```text
key=value;key=value
```

Escaping is handled in the protocol layer for reserved separators.

### Detection Payload Contract

Required exported payload keys:

- `camera_id`
- `frame_id`
- `track_id`
- `bbox`
- `branch_id`
- `branch_name`
- `plugin`
- `binding_stage`
- `device`
- `track_kind`
- `exporter_version`

Optional exported payload keys:

- `class_id`
- `class_name`
- `tracker_source`
- `confidence`
- `landmarks`
- `embedding_ref`
- `motion_score`
- `scene_tags`

Contract notes:

- `bbox` stays in the compact string form currently consumed by `DetectionResult`
- `track_id` and `track_kind` are required to preserve upper-layer entity continuity
- `branch_id`, `branch_name`, `plugin`, and `binding_stage` are required so exporter output remains debuggable after transport
- `exporter_version` is required so exporter changes can be observed without changing the line protocol

## Current Runtime Behavior

- The core process spawns `robot_life_cpp_main deepstream-backend`
- The backend emits health state transitions and mock detections from the current four-branch skeleton
- The core `DeepStreamProcessBackend` parses lines into health updates and `DetectionResult`
- The exporter layer now has a dedicated component that maps raw frame/object metadata into protocol lines before the adapter consumes them
- Detection buffering is bounded to protect against unbounded backlog
- If the child process exits unexpectedly, the backend marks state as `restarting` and reconnects on the next poll
- This is a development transport, not the final production transport

## What This Is For

- Local process integration while the real DeepStream graph is still being wired
- Stable boundary between backend output and the current `DetectionResult` / `RawEvent` contract
- Testing launcher, health, dedupe, and ingest behavior without requiring final GPU graph completion

## Boundaries

- This protocol is only for backend-to-core transport
- It does not replace `DetectionResult` or `RawEvent`
- It is intentionally small so the transport can change later without rewriting `event_engine`
