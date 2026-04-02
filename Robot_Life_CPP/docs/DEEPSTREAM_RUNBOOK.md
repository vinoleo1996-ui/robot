# DeepStream Runbook

## Scope

This runbook covers the current development-state DeepStream integration:

- backend process boundary
- adapter and event bridge
- phased startup
- regression and baseline checks
- rollback and failure handling

It does not claim that the final DeepStream branch bindings are complete.

## What Works Now

- `robot_life_cpp_main doctor`
- `robot_life_cpp_main run-live --profile mac_debug_native --ticks 4 --ui false`
- `robot_life_cpp_main run-live --profile linux_deepstream_4vision --ticks 4 --ui false`
- `./scripts/regression.sh`
- `./scripts/perf_baseline.sh --compare`

## Deployment Flow

1. Run `./scripts/doctor.sh`.
2. Run `./scripts/regression.sh`.
3. If you are validating performance gatekeeping, run `./scripts/perf_baseline.sh --compare`.
4. On Linux + NVIDIA hosts, validate `./scripts/run_4090_full.sh`.
5. For CPU or local development, use `./scripts/run_cpu_full.sh`.

## Rollback Flow

If the new path regresses, roll back in this order:

1. Disable `linux_deepstream_4vision` in the active profile and switch to `mac_debug_native` or `linux_cpu_fallback_safe`.
2. Keep the process boundary, but use the native backend path.
3. If the launcher behavior regressed, use the phased startup entrypoint only after the health checks pass.
4. If performance regressed, compare against `docs/perf/baseline_thresholds.json` before shipping.

## Failure Modes

- `doctor.sh` fails: environment or required files are missing.
- `run-live` stays in `starting` or `warming`: backend warmup or transport path is not healthy.
- `run-live` returns `degraded`: backend did not become fully ready in the warmup window.
- `perf_baseline.sh --compare` fails: current code exceeded the stored thresholds.

## Troubleshooting

1. Check `./scripts/doctor.sh` first.
2. Check `./scripts/regression.sh`.
3. Inspect `docs/perf/latest_baseline.txt` for the exact command output.
4. Verify the active profile in `configs/profile_catalog.yaml`.
5. On Linux, confirm `CUDA available: yes` before validating the DeepStream profile.
6. Remember that the current four-branch graph is still a skeleton until the real DeepStream branch bindings are added.

## Operational Boundary

- Do not let UI own runtime synchronization primitives.
- Do not let `event_engine` depend on backend implementation details.
- Do not treat the stdout pipe transport as the final production transport.
- Do not confuse the current four-branch skeleton with a completed DeepStream deployment.
