#!/usr/bin/env python3
"""验证所有核心文件是否完整"""

from pathlib import Path

core_files = {
    "核心架构": [
        "src/robot_life/app.py",
        "src/robot_life/event_engine/stabilizer.py",
        "src/robot_life/event_engine/arbitrator.py",
        "src/robot_life/event_engine/scene_aggregator.py",
        "src/robot_life/behavior/executor.py",
        "src/robot_life/behavior/resources.py",
        "src/robot_life/perception/base.py",
        "src/robot_life/perception/registry.py",
        "src/robot_life/slow_scene/service.py",
    ],
    "适配器": [
        "src/robot_life/perception/adapters/mediapipe_adapter.py",
        "src/robot_life/perception/adapters/insightface_adapter.py",
        "src/robot_life/perception/adapters/qwen_adapter.py",
    ],
    "配置文件": [
        "configs/stabilizer/default.yaml",
        "configs/detectors/default.yaml",
        "configs/arbitration/default.yaml",
        "configs/scenes/default.yaml",
    ],
    "测试": [
        "tests/unit/test_schemas.py",
    ],
    "文档": [
        "MVP_VALIDATION_SUMMARY.md",
        "PHASE2_DEPLOYMENT_CHECKLIST.md",
        "QUICK_REFERENCE.md",
        "DEPLOYMENT_4090.md",
    ],
}

print("=" * 60)
print("  核心文件完整性检查")
print("=" * 60)
print()

all_ok = True
for category, files in core_files.items():
    print(f"[{category}]")
    for fpath in files:
        p = Path(fpath)
        if p.exists():
            size = p.stat().st_size
            print(f"  ✓ {fpath:50s} ({size:6d} bytes)")
        else:
            print(f"  ✗ {fpath:50s} [MISSING]")
            all_ok = False
    print()

print("=" * 60)
if all_ok:
    print("✅ 所有核心文件检查通过")
else:
    print("❌ 某些文件缺失")
print("=" * 60)
