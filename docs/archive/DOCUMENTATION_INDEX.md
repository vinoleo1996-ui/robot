# 📚 Robot Life MVP - 文档和资源索引

> **快速导航** - 根据您的需求选择相应的文档

---

## 🎯 快速开始 (新用户必读)

| 文档 | 用途 | 阅读时间 |
|-----|------|--------|
| [QUICK_REFERENCE.md](QUICK_REFERENCE.md) | 常用命令、快速诊断、核心概念 | 5分钟 |
| [TODAY_SUMMARY.md](TODAY_SUMMARY.md) | 今天完成了什么、当前状态 | 10分钟 |

**建议**: 从 QUICK_REFERENCE.md 开始

---

## 📋 详细文档

### 核心理解 (如果你想深入了解系统)

| 文档 | 内容 | 目标读者 |
|-----|------|--------|
| [MVP_VALIDATION_SUMMARY.md](MVP_VALIDATION_SUMMARY.md) | 完整的验证报告、架构设计决策、性能指标 | 架构师、技术主管 |
| [docs/00_project_structure.md](docs/00_project_structure.md) | 项目结构详解 | 开发者 |
| [docs/02_sdd.md](docs/02_sdd.md) | 系统设计文档 | 开发者 |

### 操作指南 (如果你要做实际工作)

| 文档 | 内容 | 何时阅读 |
|-----|------|--------|
| [PHASE2_DEPLOYMENT_CHECKLIST.md](PHASE2_DEPLOYMENT_CHECKLIST.md) | Phase 2 实时视频集成完整指南 | 准备实现真实检测时 |
| [DEPLOYMENT_4090.md](DEPLOYMENT_4090.md) | 4090部署、故障排除、性能优化 | 部署到生产时 |

### 原始项目文档 (参考)

| 文档 | 用途 |
|-----|------|
| [docs/01_prd.md](docs/01_prd.md) | 产品需求文档 (原始) |
| [docs/03_validation_4090.md](docs/03_validation_4090.md) | 4090验证清单(原始) |
| [docs/04_migration_orin_nx.md](docs/04_migration_orin_nx.md) | 迁移指南 (参考) |
| [docs/05_model_selection_4090.md](docs/05_model_selection_4090.md) | 模型选择 (参考) |

---

## 🔧 如何使用本项目

### 方式 1: 使用快速启动脚本 (推荐)
```bash
./run.sh

# 菜单选项:
# 1 - 运行演示
# 2 - 验证系统
# 3 - 运行测试
# 7 - 完整检查
```

### 方式 2: 手动命令
```bash
# 运行演示
python3 -m robot_life.app run

# 运行测试
python3 -m pytest tests/unit/test_schemas.py -v

# 查看配置
cat configs/*/default.yaml
```

### 方式 3: Python交互式
```bash
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / "src"))

from robot_life.event_engine.stabilizer import EventStabilizer
from robot_life.common.schemas import DetectionResult

# 创建演示事件
stabilizer = EventStabilizer()
# ... 测试代码
```

---

## 📂 核心代码位置速记

```
Fast Thinking (事件处理):
  ├─ src/robot_life/event_engine/stabilizer.py    ← 5层稳定化
  ├─ src/robot_life/event_engine/arbitrator.py    ← 仲裁决策
  └─ src/robot_life/event_engine/scene_aggregator.py ← 场景聚合

Resources (资源管理):
  └─ src/robot_life/behavior/resources.py         ← 优先级竞争

Perception (感知):
  ├─ src/robot_life/perception/base.py            ← 抽象接口
  ├─ src/robot_life/perception/adapters/
  │  ├─ mediapipe_adapter.py                      ← 手势+注视
  │  ├─ insightface_adapter.py                    ← 人脸+识别
  │  └─ qwen_adapter.py                           ← 多模态理解
  └─ src/robot_life/perception/registry.py        ← 动态注册

Slow Thinking (多模态理解):
  └─ src/robot_life/slow_scene/service.py         ← Qwen集成

Config (配置):
  └─ configs/{detector|stabilizer|arbitration|scenes}/default.yaml
```

---

## ⏱️ 阅读路线图

### 第一次接触项目 (20分钟)
1. 读 QUICK_REFERENCE.md✓
2. 看 TODAY_SUMMARY.md (本日工作)
3. 运行 `python3 -m robot_life.app run`

### 想理解架构 (1小时)
1. 读 MVP_VALIDATION_SUMMARY.md (完整验证)
2. 读 docs/02_sdd.md (系统设计)
3. 浏览 event_engine/stabilizer.py 代码注释

### 准备Phase 2 (2小时)
1. 读 PHASE2_DEPLOYMENT_CHECKLIST.md (完整)
2. 按步骤安装感知库
3. 运行 test_video_input.py

### 生产部署 (1小时)
1. 读 DEPLOYMENT_4090.md
2. 调整 configs/detectors/default.yaml 参数
3. 运行性能监控脚本

---

## 🎬 演示怎样工作

```
python3 -m robot_life.app run

输出:
  ▶ Scenario 1: Greeting Recognition
    Event 1.1: familiar_face → Pending (debounce)
    Event 1.2: familiar_face → ✓ Passed
      ├─ Stabilizer: ✓ Passed
      ├─ Scene: familiar_face_scene
      ├─ Behavior: perform_familiar_face_scene
      ├─ Resource: ✓ Granted
      └─ Execution: ✓ FINISHED
  
  ▶ Scenario 2: Gesture Interaction
    ... (演示资源冲突处理)
  
  ▶ Scenario 3: Audio Alert
    ... (同上)
  
  Resource Status:
    • AudioOut: owned_by_perform_familiar_face_scene
    • HeadMotion: owned_by_perform_familiar_face_scene
    • BodyMotion: free
    ...
```

---

## 📊 项目统计

| 指标 | 数值 |
|-----|------|
| 总代码 | ~1600 行 |
| Python 文件 | 25 个 |
| 配置参数 | 40+ |
| 单位测试 | 8 |
| 文档 | 4 主要 + 4 原始 |
| 适配器 | 3 个 |
| 演示场景 | 3 |

---

## ❓ 常见问题

### "EventStabilizer 值得我的时间吗?"
**是的**。这是系统的核心。它通过5层防护（debounce/hysteresis/dedup/cooldown/TTL）减少假正例。

### "为什么演示中事件被过滤?"
**这是正常的**。EventStabilizer 需要 2 次确认，演示发送 2 次，所以：
- 第1次 → Pending (等待确认)
- 第2次 → ✓ Passed (确认通过)

### "如何修改 debounce 参数?"
编辑 `configs/stabilizer/default.yaml`:
```yaml
debounce_count: 2        # 改为 1 让演示更灵敏
debounce_window_ms: 300  # 改为 500 给更多时间
```

### "Resource Grant 是什么意思?"
这是资源管理系统。每个行为需要请求资源（如 AudioOut、HeadMotion），系统根据优先级分配。

### "如何集成真实摄像头?"
见 PHASE2_DEPLOYMENT_CHECKLIST.md 中的 2.2 节。

### "能在 Jetson Orin NX 上运行吗?"
见 docs/04_migration_orin_nx.md

---

## 🆘 获取帮助

### 诊断问题

```bash
# 检查导入
python3 -c "from robot_life.app import app; print('✓')"

# 验证配置
python3 << 'EOF'
import yaml
with open('configs/stabilizer/default.yaml') as f:
    print(yaml.safe_load(f))
EOF

# 查看日志文件
tail -f logs/*.log
```

### 查看相关代码

- **Stabilizer 逻辑**: `src/robot_life/event_engine/stabilizer.py` (可直接搜索 `debounce` / `cooldown`)
- **资源竞争**: `src/robot_life/behavior/resources.py` (可搜索 `ResourceGrant`)
- **适配器模板**: `src/robot_life/perception/adapters/*.py`

---

## 🎓 学习资源

### 核心概念

- **Event Pipeline**: Detection → Raw Event → Stable Event → Scene → Behavior → Execution
- **Debounce**: 需要 N 次确认才能接受事件
- **Cooldown**: 同类事件之间的最小间隔
- **Hysteresis**: 防止信号在阈值附近抖动
- **Resource Arbitration**: 优先级基的资源分配

### 性能基准

**在 RTX 4090 上**:
- 事件处理: 50ms
- 总端到端: 80ms
- GPU 内存: ~16GB

---

## 📞 项目信息

| 项目 | Robot Life MVP |
|-----|---|
| **状态** | ✅ 核心完成 |
| **版本** | 1.0 MVP |
| **最后更新** | 2026-03-27 |
| **下一阶段** | Phase 2: 实时视频集成 |
| **联系** | 见项目 README |

---

**提示**: 本索引是您快速找到任何信息的入口。祝您编码愉快！ 🚀

