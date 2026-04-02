# DeepStream Base Runtime Project

## Goal

Finish the remaining work required to make DeepStream the real four-vision runtime base for the current event-driven system.

## Rules

- Complete one item at a time
- Run regression and smoke checks after each completed item
- Mark progress here only after code and validation both pass

## Work Items

### A. Real Pipeline Runner

- [x] A1. Define a `DeepStreamRunner` abstraction and split `mock` / `real` execution paths out of the CLI
- [x] A2. Implement real runner process orchestration with explicit child lifecycle, timeout policy, and exit-state mapping
- [x] A3. Add dedicated runner-level smoke and failure-path tests

### B. Real Metadata Exporter

- [x] B1. Define the DeepStream metadata export contract for bbox, track, class, landmarks, embedding, and scene tags
- [x] B2. Implement a real exporter that turns DeepStream metadata into protocol lines consumed by the adapter
- [x] B3. Add exporter regression fixtures for empty, malformed, partial, and duplicate metadata

### C. Executable Four-Branch Config

- [x] C1. Finish executable `face` branch config and mapping
- [x] C2. Finish executable `pose-gesture` branch config and mapping
- [x] C3. Finish executable `motion` branch config and mapping
- [x] C4. Finish executable `scene-object` branch config and mapping
- [x] C5. Validate shared preprocess / tracker / interval behavior across all four branches

### D. Event Flow Validation

- [x] D1. Validate face events end-to-end from DeepStream output into `event_engine`
- [x] D2. Validate pose and gesture events end-to-end
- [x] D3. Validate motion events end-to-end
- [x] D4. Validate scene/object events end-to-end

### E. Linux + NVIDIA Runtime Validation

- [ ] E1. Pass doctor checks on Linux + NVIDIA + DeepStream host
- [ ] E2. Pass single-branch real runtime validation
- [ ] E3. Pass multi-branch real runtime validation
- [ ] E4. Pass four-branch real runtime validation
- [ ] E5. Refresh performance baseline on target hardware

## Required Validation After Each Completed Item

- [ ] `./scripts/regression.sh`
- [ ] `./scripts/perf_baseline.sh --compare`
- [ ] Item-specific smoke or integration check

## Latest Completed Validation

- [x] `./scripts/regression.sh`
- [x] `./scripts/perf_baseline.sh --compare`
- [x] `./scripts/deepstream_real_bridge_smoke.sh`
- [x] `./scripts/deepstream_real_bridge_failure_smoke.sh`

## Current Boundary

- `A` through `D` are complete in code and local regression.
- `E` remains intentionally open because Linux + NVIDIA + DeepStream hardware validation cannot be truthfully completed on this macOS development host.
