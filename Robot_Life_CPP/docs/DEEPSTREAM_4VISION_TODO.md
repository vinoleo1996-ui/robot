# DeepStream 4-Vision Integration TODO

## Goal

Replace the current four-vision perception base with DeepStream while keeping the existing `event_engine`, `behavior`, and `runtime/live_loop` as the decision core.

## Scope

- In scope: `face`, `pose-gesture`, `motion`, `scene-object`
- Out of scope for the first phase: audio migration into DeepStream
- Keep UI as a debug bridge, not part of the hot path

## Engineering Principles

- [x] Single perception contract: all visual backends emit the same `DetectionResult`
- [x] DeepStream is only the perception backend, not the scene/behavior brain
- [ ] UI reads telemetry only and must not hold runtime hot-path locks
- [x] Heavy inference stays outside the core event loop
- [x] Prefer simple process boundaries over deep in-process coupling
- [x] Every completed task must have regression coverage or a clear smoke test

## P0 Must Ship

### P0-1 Platform Baseline

- [x] Lock the target platform matrix: `Ubuntu + NVIDIA Driver + CUDA + TensorRT + DeepStream + GStreamer`
- [x] Add/update a doctor script for runtime dependency validation
- [x] Separate `mac dev` and `linux deepstream prod` profiles clearly
- [x] Document deployment prerequisites and model directory conventions

Deliverables:
- working environment checklist
- one-command doctor validation

Exit criteria:
- official DeepStream sample runs on the target machine
- project doctor script reports pass/fail with actionable errors

### P0-2 Unified Visual Contract

- [x] Finalize the visual payload schema on top of `common::DetectionResult`
- [x] Standardize required fields: `camera_id`, `frame_id`, `track_id`, `timestamp`, `confidence`, `bbox`
- [x] Standardize optional fields: `landmarks`, `class_name`, `embedding_ref`, `motion_score`, `scene_tags`
- [x] Define canonical atomic event names for all four visual branches
- [x] Add unit tests for schema serialization, defaults, and invalid payload handling

Deliverables:
- stable schema definition
- event naming table

Exit criteria:
- all four branches can map to the same contract without lossy conversion

### P0-3 Perception Backend Interface

- [x] Implement the missing perception backend abstraction in `src/perception/*`
- [x] Implement backend lifecycle interface: `start`, `stop`, `poll`, `health`, `stats`
- [x] Implement backend registry for `native` and `deepstream`
- [x] Implement pipeline factory selection via profile/config
- [x] Add tests for backend selection, lifecycle errors, and fallback behavior

Deliverables:
- clean backend boundary
- backend registry and factory

Exit criteria:
- upper layers switch backend without code changes

### P0-4 DeepStream Backend Process

- [x] Create a standalone DeepStream backend process
- [x] Define IPC transport between DeepStream and core runtime
- [x] Define message schema for exported metadata
- [x] Add heartbeat, backpressure, and reconnect handling
- [x] Add backend health reporting and startup state transitions

Deliverables:
- `deepstream_backend` process
- IPC protocol and health model

Exit criteria:
- backend can run independently and stream metadata reliably to the core process

### P0-5 DeepStream Adapter

- [x] Implement metadata parser for DeepStream outputs
- [x] Convert parsed metadata into unified `DetectionResult`
- [x] Fill `trace_id`, `source`, `detector`, `event_type`, and monotonic timestamps consistently
- [x] Handle empty frames, invalid metadata, repeated frames, and missing tracker ids
- [x] Add integration tests with mocked DeepStream metadata fixtures

Deliverables:
- `DeepStreamAdapter`
- metadata fixture set

Exit criteria:
- adapter output can flow into `event_engine` without custom branching

### P0-6 Four-Branch Visual Graph

- [x] Build the `face` branch: detect, track, attribute/embed
- [x] Build the `pose-gesture` branch: person detect, keypoints, gesture classifier/rules
- [x] Build the `motion` branch: frame-delta/flow based motion signal
- [x] Build the `scene-object` branch: object detect and scene tagging
- [x] Share decode, preprocess, and tracker stages wherever possible
- [x] Make each branch independently switchable by config

Current status:
- [x] Graph config drives four branches, execution planning, and app-config rendering
- [x] `real/mock/auto` launch path exists, with metadata bridge and real-bridge smoke coverage
- [x] Branch-specific config templates, event mapping, and end-to-end event-flow regression are in place
- [ ] Real `nvinfer`/tracker-backed branch execution still needs Linux + NVIDIA runtime validation

Deliverables:
- first runnable four-branch DeepStream graph
- branch-level metrics

Exit criteria:
- all four branches produce stable outputs with independent enable/disable controls

### P0-7 Event Engine Bridge

- [x] Map `DetectionResult` to `RawEvent` using canonical event rules
- [x] Preserve `track_id` and entity continuity for `entity_tracker`
- [x] Add debounce, dedupe, and rate-limit policies for high-frequency visual events
- [x] Verify compatibility with stabilizer, temporal layer, aggregator, and arbitrator
- [x] Add regression coverage for event flood and partial branch failure

Deliverables:
- event bridge rules
- end-to-end event mapping tests

Exit criteria:
- DeepStream visual output can drive the existing `live_loop` end-to-end

### P0-8 Launcher and Runtime State

- [x] Refactor launcher into phased startup: `env -> backend -> core -> ui`
- [x] Add explicit runtime states: `starting`, `warming`, `ready`, `degraded`, `failed`, `stopping`
- [x] Replace fragile process probing with structured health checks
- [x] Ensure graceful stop and restart for backend/core/UI process tree
- [x] Add smoke tests for start, stop, restart, and degraded startup

Deliverables:
- stable launcher behavior
- runtime state model

Exit criteria:
- startup is not falsely killed during model warmup

### P0-9 Regression and Performance Baseline

- [x] Add unit tests for schema, backend registry, pipeline factory, and adapter
- [x] Add integration tests for mocked DeepStream metadata into `event_engine`
- [x] Add smoke script for backend + core + UI minimal run
- [x] Add performance baseline script: FPS, end-to-end latency, CPU, GPU, VRAM
- [x] Record baseline numbers and failure thresholds

Deliverables:
- one-command regression
- baseline performance report

Exit criteria:
- each major change can be validated with the same regression suite

## P1 Strongly Recommended

### P1-1 Single Source of Truth Config

- [x] Move branch enable flags, thresholds, sampling rates, intervals, and priorities into one config source
- [x] Add profiles such as `cpu_debug`, `deepstream_prod`, `fallback_safe`
- [x] Support validated hot reload for safe runtime tuning

### P1-2 Lightweight Debug UI

- [x] Restrict UI to telemetry, preview, and final scene results
- [x] Keep video preview on a reduced-rate side channel
- [x] Show branch status, FPS, latency, CPU/GPU, VRAM, and final scene output
- [x] Keep parameter tuning behind validated runtime config APIs

### P1-3 Load Shedding and Resource Control

- [x] Add branch-level sampling and batch controls
- [x] Add overload policies for reduced-rate inference and branch shedding
- [x] Ensure logs, preview, and metrics cannot stall the perception path

### P1-4 Documentation and Operations

- [x] Update system architecture for DeepStream integration
- [x] Document IPC protocol and event mapping rules
- [x] Write deployment, rollback, and troubleshooting guides
- [x] Keep this file as the execution checklist and mark progress here only

## Recommended Execution Order

- [x] Step 1: finish `P0-1`, `P0-2`, `P0-3`
- [x] Step 2: finish `P0-4`, `P0-5`
- [ ] Step 3: finish `P0-6`
- [x] Step 4: finish `P0-7`, `P0-8`
- [x] Step 5: finish `P0-9`
- [x] Step 6: finish all `P1`

## Definition of Done

- [ ] Four visual branches run on DeepStream
- [x] Existing event engine and behavior chain remain the single decision core
- [x] UI stays outside the hot path
- [x] Startup and stop behavior are stable
- [x] Regression suite passes
- [x] Baseline performance numbers are recorded
- [x] Code remains modular, testable, and backend-swappable

## Remaining Work

- `E1-E5` target-host validation remains open.
- these items require Linux + NVIDIA + DeepStream hardware and cannot be truthfully closed on the macOS development host.
