# Robot Life MVP - 4090 部署和运行指南

## 一、环境准备

### 1. 系统要求
- **操作系统**: Linux (Ubuntu 22.04+) 或 Windows+WSL2
- **GPU**: NVIDIA RTX 4090
- **CUDA**: 12.1+ (推荐 CUDA 12.2)
- **英伟达驱动**: 535.x 或更高版本
- **Python**: 3.10 或 3.11
- **内存**: 至少64GB
- **磁盘**: 100GB 自由空间

### 2. 检查环境

```bash
# 检查CUDA
nvidia-smi

# 检查Python
python3 --version

# 检查CUDA兼容性
python3 -c "import torch; print(torch.cuda.is_available())"
```

## 二、安装步骤

### 1. 克隆或移动项目

```bash
cd /path/to/robot_life_dev
pwd  # 确认路径
```

### 2. 创建虚拟环境

```bash
# 创建venv
python3 -m venv .venv

# 激活venv
source .venv/bin/activate

# 升级pip
pip install --upgrade pip setuptools wheel -q
```

### 3. 安装依赖

#### 方式A: 最小化安装 (仅运行框架)

```bash
pip install -e ".[dev]" -q
```

#### 方式B: 完整MVP安装 (推荐4090)

```bash
# 安装所有detector和模型
pip install -e ".[mvp,dev]" -q
```

这会安装：
- ✅ MediaPipe (gesture + gaze)
- ✅ InsightFace (face recognition)
- ✅ YOLO (motion tracking)
- ✅ PyTorch + Transformers (Qwen)
- ✅ OpenCV + 其他工具库

#### 方式C: 分步安装 (如果遇到问题)

```bash
# 基础
pip install "pydantic>=2.7,<3" "pyyaml>=6.0,<7" "rich>=13.7,<14" "typer>=0.12,<1" -q

# 感知
pip install "opencv-python>=4.10" "mediapipe>=0.10" "insightface>=0.7" -q

# 推理框架
pip install "torch>=2.0" "transformers>=4.35" "accelerate>=0.24" -q

# 测试
pip install "pytest>=8.0" "ruff>=0.5" -q
```

### 4. 验证安装

```bash
# 运行诊断
robot-life-doctor

# 或
python -m robot_life.app doctor

# 输出应该显示所有关键模块已加载
```

## 三、模型准备

### 1. MediaPipe 模型  
**自动下载**，无需手动配置

### 2. InsightFace 模型

创建模型目录并下载：

```bash
# 创建模型目录
mkdir -p ~/.insightface/models

# InsightFace会自动下载buffalo_l模型到此目录
# 首次运行时会自动下载，约700MB
```

### 3. Qwen-VL 模型

```bash
# 方式1: 自动下载 (首次运行)
# 系统会从HuggingFace自动下载约7GB模型
# 需要联网

# 方式2: 手动下载到本地 (推荐在4090上)
python3 << 'EOF'
from transformers import AutoProcessor, Qwen2VLForConditionalGeneration

# 这会下载~7GB模型到~/.cache/huggingface
model_path = "Qwen/Qwen2-VL-7B-Instruct"
processor = AutoProcessor.from_pretrained(model_path)
model = Qwen2VLForConditionalGeneration.from_pretrained(model_path)
print("✓ Qwen模型已下载")
EOF
```

## 四、运行

### 1. 快速演示 (Synthetic Data)

```bash
# 激活venv
source .venv/bin/activate

# 运行synthetic demo
robot-life run

# 或
python -m robot_life.app run
```

**预期输出**:
```
Running Robot Life MVP Demo

Event 1: familiar_face
  Detection: familiar_face (confidence=0.92)
  Raw Event: xxxx...
  Stable Event: yyyy... (stabilized_by=['debounce', 'hysteresis', 'dedup', 'cooldown'])
  Scene Candidate: familiar_face_scene (score=0.82)
  Arbitration: perform_greeting (mode=EXECUTE, resources=['HeadMotion', 'FaceExpression'])
  Execution: finished (degraded=False)
  Scene JSON: familiar_face_scene (escalate=True)

[More events...]

Demo completed

Resource Status:
  AudioOut: free
  HeadMotion: free
  ...
```

### 2. 使用真实摄像头 (可选)

创建 `demo_camera.py`:

```python
import cv2
from robot_life.app import *

cap = cv2.VideoCapture(0)  # 0 = default camera

while True:
    ret, frame = cap.read()
    if not ret:
        break
    
    # TODO: 集成真实detector
    # 这部分在Phase 2会完成
    
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
```

### 3. 运行单元测试

```bash
# 运行所有测试
pytest -v

# 或运行特定模块
pytest tests/unit/test_schemas.py -v

# 预期通过的测试:
# test_detection_to_raw_event ✓
# test_stabilizer_debounce ✓
# test_stabilizer_cooldown ✓
# test_stabilizer_hysteresis ✓
# test_stabilizer_dedup ✓
# test_resource_manager_exclusive ✓
```

## 五、性能基准 (4090)

### 预期性能指标

| 模块 | 平均延迟 | 最坏情况 | 注记 |
|------|---------|---------|------|
| **Detection** |  |  |  |
| MediaPipe Gesture | 5-8ms | 15ms | per frame |
| InsightFace | 10-15ms | 30ms | per face |
| Qwen VL | 1-2s | 5s | per image |
| **Event Pipeline** |  |  |  |
| Builder → Stabilizer | <1ms | 2ms |  |
| Scene Aggregation | <1ms | 2ms |  |
| Arbitration | <1ms | 2ms |  |
| Resource Manager | <1ms | 2ms |  |
| **E2E Latency** | ~20ms | 50ms | 5类detector并行 |

### GPU显存占用 (RTX 4090)

| 模型 | VRAM占用 | 最大峰值 |
|------|---------|---------|
| MediaPipe | <500MB | 1GB |
| InsightFace | 1-2GB | 3GB |
| Qwen2-VL-7B | 14GB | 16GB |
| **总计** | ~16GB | ~20GB |

**4090总内存**: 24GB
**可用余地**: 4GB (用于推理临时变量)

## 六、监控和调试

### 1. 启用详细日志

```bash
# 在app.py中修改log_level
LOGLEVEL=DEBUG robot-life run

# 或修改配置文件
# configs/runtime/app.default.yaml
# runtime:
#   log_level: DEBUG
```

### 2. 性能分析

```python
import cProfile
import pstats
from robot_life.app import run

profiler = cProfile.Profile()
profiler.enable()

run()  # 运行主程序

profiler.disable()
stats = pstats.Stats(profiler)
stats.sort_stats('cumulative')
stats.print_stats(20)  # 前20个最耗时函数
```

### 3. 资源监控

```bash
# 在另一个终端监控GPU
watch -n 1 nvidia-smi

# 或更详细
nvidia-smi --query-gpu=index,temperature.gpu,utilization.gpu,utilization.memory,memory.used,memory.free --format=csv,noheader -l 1
```

## 七、常见问题

### Q1: CUDA OOM (内存不足)

**症状**: `RuntimeError: CUDA out of memory`

**解决**:
```bash
# 方案1: 降低batch size
# configs/detectors/default.yaml
detectors:
  face:
    config:
      rec_batch_size: 8  # 降低从32

# 方案2: 只加载必要的detector
# configs/runtime/app.default.yaml
runtime:
  enabled_pipelines:
    - face         # 只启用face
    # - gesture    # 禁用其他
    # - audio

# 方案3: 使用fp32代替fp16 (更慢但省显存)
```

### Q2: MediaPipe下载失败

**症状**: `Failed to load MediaPipe model`

**解决**:
```bash
# 手动下载
python3 << 'EOF'
import mediapipe as mp
# 这会自动缓存模型
mp.tasks.vision.GestureRecognizer.create_from_options(options)
EOF
```

### Q3: InsightFace下载慢

**症状**: `InsightFace下载buffalo_l模型超时`

**解决**:
```bash
# 手动下载到指定目录
mkdir -p ~/.insightface/models
wget -O ~/.insightface/models/buffalo_l.zip \
  https://huggingface.co/buffalo_l/resolve/main/buffalo_l.zip
unzip ~/.insightface/models/buffalo_l.zip
```

## 八、下一步 (Phase 2+)

### 立即可做
1. ✅ 运行synthetic demo验证框架
2. ✅ 运行单元测试
3. ✅ 配置真实摄像头输入

### Phase 2 计划 (2-3天)
1. 集成真实MediaPipe detector
2. 集成真实InsightFace detector
3. 在线场景测试
4. 参数调优

### Phase 3 计划 (1周)
1. 端侧Qwen集成
2. BehaviorTree.CPP 集成
3. 云端LLM链接

## 九、性能优化建议

若在4090上遇到性能瓶颈:

### 1. 动态帧率调整
```yaml
# configs/runtime/app.default.yaml
perception:
  dynamic_sampling: true
  base_fps: 10       # 基础帧率
  boost_fps: 30      # 事件触发时提升到
  boost_duration_ms: 1000
```

### 2. 并行处理优化
```python
# 在detector中启用并行推理
import torch
torch.set_num_threads(8)  # 使用8个CPU线程辅助GPU
```

### 3. 模型量化 (后续)
```python
# 使用INT8量化降低延迟
from transformers import AutoQuantizationConfig
quantization_config = AutoQuantizationConfig.from_pretrained("Qwen2-VL-7B")
```

---

**现在可以开始MVP验证了！** 🚀

运行 `robot-life run` 看看效果如何。
