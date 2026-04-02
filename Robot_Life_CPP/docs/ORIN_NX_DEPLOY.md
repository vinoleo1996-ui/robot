# Orin NX Deploy And Debug

## Official Support Boundary

DeepStream officially supports Jetson platforms, including Orin-class devices, but deployment still depends on a matching JetPack, CUDA, TensorRT, and DeepStream combination.

## Script

- Main script:
  - `scripts/orin_nx_deploy_debug.sh`

## Common Commands

- Environment check:
  - `scripts/orin_nx_deploy_debug.sh doctor`
- Build:
  - `scripts/orin_nx_deploy_debug.sh build`
- Real DeepStream backend smoke:
  - `scripts/orin_nx_deploy_debug.sh smoke`
- Run full live loop without UI:
  - `scripts/orin_nx_deploy_debug.sh run`
- Run full live loop with debug UI:
  - `scripts/orin_nx_deploy_debug.sh ui`

## Useful Environment Overrides

- `PROFILE=deepstream_prod`
- `GRAPH_CONFIG=/abs/path/deepstream_4vision.yaml`
- `RUNTIME_TUNING=/abs/path/runtime_tuning.yaml`
- `ROBOT_LIFE_CPP_DEEPSTREAM_MODE=real`
- `RUN_TICKS=16`
- `RUN_UI=true`
- `ORIN_SET_PERF=1`

## Notes

- `ORIN_SET_PERF=1` attempts `nvpmodel -m 0` and `jetson_clocks` when available.
- `tegrastats` is started automatically for `run` and `ui` if installed.
- The script uses the existing `deepstream_prod` profile and does not create a parallel launch path.
