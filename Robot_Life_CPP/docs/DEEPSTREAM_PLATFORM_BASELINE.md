# DeepStream Platform Baseline

## Target

Use DeepStream only as the four-vision perception backend on `Linux + NVIDIA dGPU`.

Current code status:

- platform split is documented and enforced
- DeepStream process boundary exists
- four-branch graph is still mock/skeleton
- true DeepStream `nvinfer` branch bindings are not yet complete

## Supported Modes

- `mac_debug_native`: local development and event-engine iteration on macOS or non-NVIDIA hosts
- `linux_deepstream_4vision`: production four-vision backend on Linux with DeepStream
- `linux_cpu_fallback_safe`: safe Linux fallback when CUDA or DeepStream is unavailable

## Version Matrix

- Ubuntu `22.04` or newer
- NVIDIA Driver `>= 550`
- CUDA Toolkit `12.x`
- TensorRT aligned with the installed DeepStream release
- DeepStream `8.x`
- GStreamer version bundled or required by that DeepStream release
- CMake `>= 3.20`
- Ninja recommended
- GCC/G++ `>= 11` or Clang `>= 15`

## Model Directory Convention

- `models/native`: development and CPU-safe assets
- `models/deepstream`: DeepStream/TensorRT assets

Do not hardcode branch-specific model paths inside launchers. Profiles should reference the model root, and the backend should resolve branch assets beneath that root.

## First-Principles Constraints

- DeepStream is the perception backend only
- `event_engine`, `behavior`, and `runtime/live_loop` remain the decision core
- UI is not part of the hot path
- The backend process and the core process should be separable

## Validation

Run:

```bash
./scripts/doctor.sh
```

This validates:

- required repo config files
- profile catalog structure
- model directory convention
- host platform hints
- CUDA and DeepStream runtime hints

## Practical Rule

If the host is not Linux with NVIDIA GPU support, use `mac_debug_native` or `linux_cpu_fallback_safe`.
If the host is Linux with NVIDIA GPU support, `linux_deepstream_4vision` is the intended production profile, but the current graph path is still a skeleton until real branch bindings are completed.
