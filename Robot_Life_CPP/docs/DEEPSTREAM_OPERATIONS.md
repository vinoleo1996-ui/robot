# DeepStream Operations

## Main Commands

- doctor
  - `./scripts/doctor.sh`
  - `./build/robot_life_cpp_main doctor`
- regression
  - `./scripts/regression.sh`
- performance baseline
  - `./scripts/perf_baseline.sh --compare`
- DeepStream backend smoke
  - `./scripts/deepstream_real_bridge_smoke.sh`
  - `./scripts/deepstream_real_bridge_failure_smoke.sh`
- UI smoke
  - `./scripts/ui_dashboard_smoke.sh`

## Runtime Tuning

- config file:
  - `configs/runtime_tuning.yaml`
- safe reload:
  - `run-live --reload-tuning true`
- if the new config is invalid:
  - launcher marks tuning unhealthy
  - previous valid runtime state remains active

## Dashboard Outputs

- `ui-demo` writes:
  - HTML dashboard
  - JSON snapshot
- default paths:
  - `/tmp/robot_life_cpp_dashboard.html`
  - `/tmp/robot_life_cpp_dashboard.json`

## Rollback

1. revert `configs/runtime_tuning.yaml` to the last known-good values
2. switch profile to:
   - `cpu_debug`
   - or `fallback_safe`
3. rerun:
   - `./scripts/regression.sh`

## Troubleshooting

- `doctor` fails on config file
  - verify `configs/runtime_tuning.yaml` exists and is readable
- DeepStream plan invalid
  - check model config paths in `configs/deepstream_4vision.yaml`
  - verify required branch properties in `models/deepstream/*`
- dashboard not generated
  - run `./scripts/ui_dashboard_smoke.sh`
  - verify output paths are writable
- launcher says tuning failed
  - check hysteresis bounds and numeric values in `runtime_tuning.yaml`
- backend ready but no scene output
  - inspect exporter/adaptor fixtures via `ctest --output-on-failure -R test_core`

## Remaining Hardware Gate

- Linux + NVIDIA + DeepStream validation is still required for:
  - target-host doctor
  - single-branch runtime
  - multi-branch runtime
  - four-branch runtime
  - final target-hardware baseline
