# Robot Life C++ (Full Migration Workspace)

This workspace is the full-scope C++ migration target for `src/robot_life`.

## Current status

- Full module inventory tracked: `79` Python modules
- Single source of profile definitions: `configs/profile_catalog.yaml`
- Migration matrix auto-generated: `docs/MODULE_MIGRATION_MATRIX.md`
- Core runtime implemented:
  - `common/schemas`
  - `event_engine/stabilizer`
  - `event_engine/scene_aggregator`
  - `event_engine/arbitrator`
  - `runtime/live_loop`

## Key commands

```bash
cd Robot_Life_CPP
python3 scripts/generate_module_catalog.py
./scripts/regression.sh
./scripts/run_4090_full.sh
```

## Design constraints

- Debug UI is isolated in bridge layer, never embedded in runtime critical path.
- Event engine and runtime remain independent from UI transport.
- Migration progress and module coverage are tracked from one generated catalog.
