#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MODULE_LIST = ROOT / "configs" / "python_modules.list"
CATALOG_CPP = ROOT / "src" / "migration" / "module_catalog.cpp"
MATRIX_MD = ROOT / "docs" / "MODULE_MIGRATION_MATRIX.md"


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


def is_implemented_target(target: str) -> bool:
    if target.startswith("src/stubs/"):
        return False
    target_path = ROOT / target
    if not target_path.exists():
        return False
    return not looks_like_placeholder_only(target_path)


def looks_like_placeholder_only(path: Path) -> bool:
    body: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("//", 1)[0].strip()
        if not line:
            continue
        if line.startswith("#include"):
            continue
        if line.startswith("namespace "):
            continue
        if line == "}":
            continue
        if raw.strip().startswith("}  // namespace"):
            continue
        body.append(line)
    return len(body) == 1 and "constexpr std::string_view kModule" in body[0]


def read_modules() -> list[str]:
    lines = []
    for raw in MODULE_LIST.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        lines.append(line)
    return lines


def write_catalog_cpp(modules: list[str]) -> None:
    rows: list[str] = []
    for path in modules:
        target = infer_cpp_target(path)
        layer = infer_layer(path)
        implemented = "true" if is_implemented_target(target) else "false"
        rows.append(
            '      ModuleMapping{"%s", "%s", "%s", %s},'
            % (path, target, layer, implemented)
        )

    content = [
        '#include "robot_life_cpp/migration/module_catalog.hpp"',
        "",
        "namespace robot_life_cpp::migration {",
        "",
        "const std::vector<ModuleMapping>& module_catalog() {",
        "  static const std::vector<ModuleMapping> kCatalog = {",
        *rows,
        "  };",
        "  return kCatalog;",
        "}",
        "",
        "std::size_t implemented_module_count() {",
        "  std::size_t count = 0;",
        "  for (const auto& item : module_catalog()) {",
        "    if (item.implemented) {",
        "      count += 1;",
        "    }",
        "  }",
        "  return count;",
        "}",
        "",
        "std::size_t total_module_count() { return module_catalog().size(); }",
        "",
        "}  // namespace robot_life_cpp::migration",
        "",
    ]
    CATALOG_CPP.write_text("\n".join(content), encoding="utf-8")


def write_matrix_md(modules: list[str]) -> None:
    header = [
        "# Robot Life Python -> C++ Migration Matrix",
        "",
        "This matrix is generated from `configs/python_modules.list` and is the single source",
        "for full-scope migration tracking.",
        "",
        "| Python Module | C++ Target | Layer | Status |",
        "| --- | --- | --- | --- |",
    ]
    rows = []
    for path in modules:
        target = infer_cpp_target(path)
        layer = infer_layer(path)
        status = "Implemented" if is_implemented_target(target) else "Pending"
        rows.append(f"| `{path}` | `{target}` | `{layer}` | `{status}` |")
    MATRIX_MD.write_text("\n".join(header + rows) + "\n", encoding="utf-8")


def validate() -> None:
    if not MODULE_LIST.exists():
        raise SystemExit(f"missing module list: {MODULE_LIST}")


def main() -> None:
    validate()
    modules = read_modules()
    if len(modules) == 0:
        raise SystemExit("python module list is empty")
    write_catalog_cpp(modules)
    write_matrix_md(modules)
    print(f"generated {CATALOG_CPP}")
    print(f"generated {MATRIX_MD}")
    print(f"module count={len(modules)}")


if __name__ == "__main__":
    main()
