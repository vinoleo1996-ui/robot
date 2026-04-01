#!/bin/bash

# Robot Life MVP - 快速启动脚本
# 一键验证和运行演示

set -e  # 遇到错误立即退出

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

PYTHON_BIN="${PROJECT_DIR}/.venv/bin/python"
if [[ ! -x "${PYTHON_BIN}" ]]; then
    PYTHON_BIN="$(command -v python3)"
fi

export PYTHONPATH="${PROJECT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"

# 让 llama-cpp / onnxruntime-gpu 在用户态安装下也能找到 CUDA 共享库
if [[ -n "${PYTHON_BIN}" ]]; then
    CUDA_LIB_PATHS="$("${PYTHON_BIN}" - <<'PY'
import site
import sys
from pathlib import Path

paths = []
seen = set()
for entry in sys.path:
    if not entry:
        continue
    root = Path(entry).expanduser() / "nvidia"
    if not root.is_dir():
        continue
    for lib_dir in sorted(root.glob("*/lib")):
        value = str(lib_dir.resolve())
        if value not in seen:
            seen.add(value)
            paths.append(value)
print(":".join(paths))
PY
)"
    if [ -n "$CUDA_LIB_PATHS" ]; then
        export LD_LIBRARY_PATH="${CUDA_LIB_PATHS}:${LD_LIBRARY_PATH}"
    fi
fi

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_header() {
    echo -e "\n${BLUE}════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}════════════════════════════════════════════════════════${NC}\n"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

# 主菜单
show_menu() {
    print_header "Robot Life MVP - 快速启动菜单"
    echo "选择要执行的操作:"
    echo ""
    echo "  1. 运行合成演示 (verify core logic)"
    echo "  2. 验证系统完整性 (check all files)"
    echo "  3. 运行单元测试 (run unit tests)"
    echo "  4. 查看快速参考 (open docs/ops/QUICK_REFERENCE.md)"
    echo "  5. 查看今日总结 (open docs/reports/TODAY_SUMMARY.md)"
    echo "  6. 查看验证报告 (open docs/reports/MVP_VALIDATION_SUMMARY.md)"
    echo "  7. 完整系统检查 (all of above)"
    echo "  8. 清理缓存 (clean cache)"
    echo "  9. 退出 (exit)"
    echo ""
}

run_demo() {
    print_header "运行 Robot Life MVP 演示"
    print_info "执行: ${PYTHON_BIN} -m robot_life.app run"
    echo ""
    "${PYTHON_BIN}" -m robot_life.app run
}

verify_system() {
    print_header "系统完整性验证"
    
    # 创建验证脚本
    "${PYTHON_BIN}" - << 'EOF'
from pathlib import Path

files_to_check = [
    "src/robot_life/app.py",
    "src/robot_life/event_engine/stabilizer.py",
    "src/robot_life/behavior/resources.py",
    "src/robot_life/perception/adapters/mediapipe_adapter.py",
    "src/robot_life/perception/adapters/insightface_adapter.py",
    "configs/stabilizer/default.yaml",
    "configs/detectors/default.yaml",
    "tests/unit/test_schemas.py",
    "docs/reports/MVP_VALIDATION_SUMMARY.md",
    "docs/reports/TODAY_SUMMARY.md",
]

missing = []
for fpath in files_to_check:
    if Path(fpath).exists():
        print(f"  ✓ {fpath}")
    else:
        print(f"  ✗ {fpath} [MISSING]")
        missing.append(fpath)

print()
if not missing:
    print("✅ 所有核心文件检查通过")
else:
    print(f"❌ {len(missing)} 个文件缺失")
EOF
}

run_tests() {
    print_header "运行单元测试"
    print_info "执行: ${PYTHON_BIN} -m pytest tests/unit/test_schemas.py -v"
    echo ""

    if "${PYTHON_BIN}" -m pytest --version >/dev/null 2>&1; then
        "${PYTHON_BIN}" -m pytest tests/unit/test_schemas.py -v
    else
        print_warning "pytest 未安装,尝试用unittest运行..."
        "${PYTHON_BIN}" -m unittest discover tests/unit -v 2>/dev/null || print_warning "无法运行测试"
    fi
}

view_file() {
    local file=$1
    local desc=$2
    
    if [ -f "$file" ]; then
        print_header "查看: $desc"
        less "$file"
    else
        print_error "文件不存在: $file"
    fi
}

clean_cache() {
    print_header "清理缓存"
    
    print_info "删除 __pycache__ 目录..."
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    
    print_info "删除 .pyc 文件..."
    find . -name "*.pyc" -delete 2>/dev/null || true
    
    print_info "删除 .pytest_cache..."
    find . -name ".pytest_cache" -type d -exec rm -rf {} + 2>/dev/null || true
    
    print_success "缓存已清理"
}

run_all() {
    run_demo
    echo ""
    verify_system
    echo ""
    run_tests
}

# 主循环
main() {
    if [ "$1" == "--demo" ]; then
        run_demo
    elif [ "$1" == "--verify" ]; then
        verify_system
    elif [ "$1" == "--test" ]; then
        run_tests
    elif [ "$1" == "--all" ]; then
        run_all
    elif [ "$1" == "--clean" ]; then
        clean_cache
    else
        while true; do
            show_menu
            read -p "请选择 (1-9): " choice
            
            case $choice in
                1) run_demo ;;
                2) verify_system ;;
                3) run_tests ;;
                4) view_file "docs/ops/QUICK_REFERENCE.md" "快速参考卡" ;;
                5) view_file "docs/reports/TODAY_SUMMARY.md" "今日完成总结" ;;
                6) view_file "docs/reports/MVP_VALIDATION_SUMMARY.md" "MVP验证报告" ;;
                7) run_all ;;
                8) clean_cache ;;
                9) 
                    print_header "再见!"
                    exit 0
                    ;;
                *)
                    print_error "无效选择,请重试"
                    ;;
            esac
            
            read -p "按 Enter 继续..."
        done
    fi
}

main "$@"
