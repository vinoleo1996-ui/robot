#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MODULE_LIST = ROOT / "configs" / "python_modules.list"


def infer_layer(path: str) -> str:
    parts = path.split("/")
    if len(parts) < 2:
        return "root"
    if len(parts) == 2:
        return "root"
    return parts[1]


def infer_cpp_target(path: str) -> str:
    parts = path.split("/")
    layer = infer_layer(path)
    if layer == "root":
        leaf = parts[-1][:-3] if parts[-1].endswith(".py") else parts[-1]
        return f"src/root/{leaf}.cpp"
    rel = Path(*parts[2:]) if len(parts) > 2 else Path(parts[-1])
    rel_cpp = rel.with_suffix(".cpp").as_posix()
    if layer == "event_engine":
        return f"src/event_engine/{rel_cpp}"
    if layer == "runtime":
        return f"src/runtime/{rel_cpp}"
    if layer == "common":
        return f"src/common/{rel_cpp}"
    if layer == "perception":
        return f"src/perception/{rel_cpp}"
    if layer == "behavior":
        return f"src/behavior/{rel_cpp}"
    if layer == "slow_scene":
        return f"src/slow_scene/{rel_cpp}"
    leaf = parts[-1][:-3] if parts[-1].endswith(".py") else parts[-1]
    return f"src/stubs/{leaf}.cpp"


def is_implemented(target: str) -> bool:
    if target.startswith("src/stubs/"):
        return False
    return (ROOT / target).exists()


def main() -> int:
    modules = [x.strip() for x in MODULE_LIST.read_text(encoding="utf-8").splitlines() if x.strip()]
    implemented = []
    missing = []
    for mod in modules:
        target = infer_cpp_target(mod)
        if is_implemented(target):
            implemented.append((mod, target))
        else:
            missing.append((mod, target))

    print(f"full_migration_check: implemented={len(implemented)} total={len(modules)}")
    if missing:
        print("missing_modules:")
        for mod, target in missing[:30]:
            print(f"  - {mod} -> {target}")
        if len(missing) > 30:
            print(f"  ... and {len(missing)-30} more")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
