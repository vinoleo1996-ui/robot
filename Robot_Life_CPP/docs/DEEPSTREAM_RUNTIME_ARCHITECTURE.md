# DeepStream Runtime Architecture

## Goal

Use DeepStream as the four-vision perception base while keeping the existing event engine and behavior runtime as the decision core.

## Main Layers

1. Perception backend
   - `deepstream-backend`
   - `DeepStreamRunner`
   - `DeepStreamFourVisionGraph`
   - `DeepStreamExporter`
   - `DeepStreamAdapter`

2. Event and scene core
   - `DetectionEventInjector`
   - `EventStabilizer`
   - `SceneAggregator`
   - `Arbitrator`
   - `LiveLoop`

3. Runtime tuning and protection
   - `RuntimeTuningStore`
   - `RuntimeLoadShedder`

4. Debug bridge
   - `StateSnapshotBridge`
   - `AggregatingTelemetrySink`
   - lightweight dashboard renderer

## Data Flow

`DeepStream metadata`
-> `DeepStreamExporter`
-> `DETECTION|...` protocol lines
-> `DeepStreamAdapter`
-> `DetectionResult`
-> `DetectionEventInjector`
-> `RawEvent`
-> `EventStabilizer`
-> `StableEvent`
-> `SceneAggregator`
-> `SceneCandidate`
-> `Arbitrator`
-> `ArbitrationResult`

## Four Vision Branches

- `face`
  - canonical outputs:
    - `face_detected`
    - `face_identity_detected`
    - `face_attention_detected`
- `pose_gesture`
  - canonical outputs:
    - `pose_detected`
    - `gesture_detected`
    - `wave_detected`
- `motion`
  - canonical outputs:
    - `motion_detected`
    - `approaching_detected`
    - `leaving_detected`
- `scene_object`
  - canonical outputs:
    - `scene_context_detected`
    - `person_present_detected`
    - `object_detected`

## Single Source of Truth

- `configs/runtime_tuning.yaml`
  - scene bias
  - scene taxonomy
  - event -> scene mapping
  - scene priority
  - behavior mapping
  - stabilizer thresholds
  - event injector dedupe/cooldown
  - branch enable flags
  - branch sampling intervals
  - shared preprocess / tracker flags

## Load Shedding

- `RuntimeLoadShedder` monitors:
  - runtime pending events
  - scene candidates per tick
  - backend delivered batches / detections
- actions:
  - lower event batch caps
  - reduce preview frequency
  - reduce telemetry emission frequency
  - keep UI out of the hot path

## Debug UI

- UI is generated from telemetry, health, backend stats, tuning, and reduced-rate preview detections.
- UI does not hold runtime hot-path locks.
- current artifact outputs:
  - HTML dashboard
  - JSON snapshot

## Current Boundary

- All code-side integration and regression are complete on the development host.
- Linux + NVIDIA + DeepStream target-host validation remains a separate hardware gate.
