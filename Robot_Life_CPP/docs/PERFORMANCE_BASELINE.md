# Performance Baseline

Use the local baseline script to keep startup and mock runtime behavior measurable while the real DeepStream graph is still being integrated.

This is a regression floor for the current code state, not a final DeepStream benchmark.

Run:

```bash
./scripts/perf_baseline.sh
```

Compare against thresholds:

```bash
./scripts/perf_baseline.sh --compare
```

Refresh the threshold file from the current run:

```bash
./scripts/perf_baseline.sh --refresh-thresholds
```

Current output target:

- `docs/perf/latest_baseline.json`
- `docs/perf/latest_baseline.txt`
- `docs/perf/baseline_thresholds.json`

The baseline currently records:

- doctor command duration
- phased startup duration for `mac_debug_native`
- phased startup duration for `linux_deepstream_4vision` using the current mocked DeepStream backend
- machine-readable JSON fields for direct comparison
- fail thresholds for each case

Current measurement files:

- `docs/perf/latest_baseline.json`
- `docs/perf/latest_baseline.txt`
- `docs/perf/baseline_thresholds.json`

This is not the final production benchmark. It is the regression floor that prevents launcher, backend, and event bridge changes from silently becoming slower or less stable.
