# Robot Life MVP - Phase 2 部署检查清单

**目标**: 从合成演示过渡到实时视频处理  
**预期时间**: 2-4小时  
**难度**: 中等  

---

## 📋 前置检查

### 硬件验证
```bash
# 检查GPU
nvidia-smi

# 预期输出:
# NVIDIA RTX 4090 with 24GB VRAM
# Driver Version: 535+ ✓
```

### Python环境
```bash
# 验证Python版本
python3 --version  # 需要 >= 3.10

# 验证已安装package
pip list | grep -E "pydantic|pyyaml|rich"
# 应该看到: pydantic, pyyaml, rich ✓
```

### 项目安装确认
```bash
# 确保项目安装正确
python3 -c "from robot_life.app import app; print('✓ 项目导入成功')"

# 运行合成演示验证基础
python3 -m robot_life.app run
# 应该看到3个演示场景完整执行 ✓
```

---

## 🎯 Phase 2.1: 感知库安装 (30分钟)

### Step 1: 安装核心感知依赖

```bash
# 进入项目目录
cd /path/to/robot_life_dev

# 安装MediaPipe (手势+眼睛追踪)
pip install mediapipe --quiet --break-system-packages

# 安装InsightFace (人脸检测+识别)
pip install insightface onnxruntime-gpu --quiet --break-system-packages

# 安装OpenCV (视频处理)
pip install opencv-python --quiet --break-system-packages

# 验证安装
python3 -c "import mediapipe; import insightface; import cv2; print('✓ 所有感知库已安装')"
```

**预期时间**: 15-20分钟  
**磁盘空间**: ~2GB  
**网络**: 需要稳定连接  

### Step 2: 验证适配器导入

```bash
# 测试MediaPipe适配器
python3 << 'EOF'
from robot_life.perception.adapters.mediapipe_adapter import (
    MediaPipeGestureDetector, 
    MediaPipeGazePipeline
)
print("✓ MediaPipe适配器导入成功")
EOF

# 测试InsightFace适配器
python3 << 'EOF'
from robot_life.perception.adapters.insightface_adapter import (
    InsightFaceDetector,
    InsightFacePipeline
)
print("✓ InsightFace适配器导入成功")
EOF
```

**预期**: 两个脚本都打印成功信息 ✓

### Step 3: 下载模型文件

```bash
# MediaPipe会自动下载模型 (首次使用时)
# InsightFace会下载buffalo_l模型 (~700MB)

echo "✓ 模型将在首次使用时自动下载"

# 预测磁盘使用:
# - MediaPipe: ~360MB
# - InsightFace (buffalo_l): ~700MB  
# - ONNX Runtime: ~200MB
# 总计: ~1.3GB
```

---

## 🎥 Phase 2.2: 实时视频测试 (45分钟)

### Step 1: 创建视频测试脚本

```bash
cat > test_video_input.py << 'EOF'
#!/usr/bin/env python3
"""
测试实时视频输入和检测器集成
"""

import cv2
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

from robot_life.perception.adapters.mediapipe_adapter import (
    MediaPipeGestureDetector, 
    MediaPipeGazePipeline
)
from robot_life.perception.adapters.insightface_adapter import (
    InsightFaceDetector
)

def test_gesture_detection():
    """测试手势识别"""
    print("[1/3] 初始化手势检测器...")
    detector = MediaPipeGestureDetector()
    detector.initialize()
    
    print("[1/3] 打开摄像头...")
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    
    frame_count = 0
    print("[1/3] 读取30帧用于手势测试 (5秒@30fps)...")
    
    while frame_count < 30:
        ret, frame = cap.read()
        if not ret:
            print("❌ 无法读取摄像头")
            cap.release()
            return False
            
        results = detector.process(frame)
        if results:
            print(f"  ✓ Frame {frame_count}: 检测到 {len(results)} 个手势")
            for r in results:
                print(f"    - {r.event_type} (confidence={r.confidence:.2f})")
        
        frame_count += 1
    
    cap.release()
    detector.close()
    print("✓ 手势检测器工作正常\n")
    return True

def test_face_detection():
    """测试人脸检测"""
    print("[2/3] 初始化人脸检测器...")
    detector = InsightFaceDetector()
    detector.initialize()
    
    print("[2/3] 打开摄像头...")
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    
    frame_count = 0
    print("[2/3] 读取30帧用于人脸测试 (5秒@30fps)...")
    
    while frame_count < 30:
        ret, frame = cap.read()
        if not ret:
            print("❌ 无法读取摄像头")
            cap.release()
            return False
            
        results = detector.process(frame)
        if results:
            print(f"  ✓ Frame {frame_count}: 检测到 {len(results)} 张脸")
            for r in results:
                print(f"    - {r.event_type} (confidence={r.confidence:.2f})")
        
        frame_count += 1
    
    cap.release()
    detector.close()
    print("✓ 人脸检测器工作正常\n")
    return True

def test_gaze_detection():
    """测试眼睛追踪"""
    print("[3/3] 初始化眼睛追踪...")
    detector = MediaPipeGazePipeline()
    detector.initialize()
    
    print("[3/3] 打开摄像头...")
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    
    frame_count = 0
    print("[3/3] 读取30帧用于眼睛追踪 (5秒@30fps)...")
    
    while frame_count < 30:
        ret, frame = cap.read()
        if not ret:
            print("❌ 无法读取摄像头")
            cap.release()
            return False
            
        results = detector.process(frame)
        if results:
            print(f"  ✓ Frame {frame_count}: {len(results)} 个追踪结果")
            for r in results:
                print(f"    - {r.event_type}")
        
        frame_count += 1
    
    cap.release()
    detector.close()
    print("✓ 眼睛追踪工作正常\n")
    return True

if __name__ == "__main__":
    print("=" * 60)
    print("  Robot Life MVP - 实时视频检测测试")
    print("=" * 60)
    print()
    print("⚠️ 确保摄像头已连接并可用")
    print("按 Ctrl+C 可随时退出\n")
    
    try:
        success = True
        success = test_gesture_detection() and success
        success = test_face_detection() and success
        success = test_gaze_detection() and success
        
        if success:
            print("=" * 60)
            print("✅ 所有检测器都工作正常!")
            print("=" * 60)
            print()
            print("下一步:")
            print("  1. 参数调优: 编辑 configs/detectors/default.yaml")
            print("  2. 集成到主管道: 更新 app.py 或 event_engine/builder.py")
            print("  3. 运行完整系统: python3 -m robot_life.app run --video")
        else:
            print("=" * 60)
            print("❌ 某些检测器失败")
            print("=" * 60)
            
    except KeyboardInterrupt:
        print("\n⏹️ 测试被用户中断")
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
EOF

chmod +x test_video_input.py
```

### Step 2: 运行视频测试

```bash
# 确保在项目目录下
cd /path/to/robot_life_dev

# 运行视频检测器测试
python3 test_video_input.py

# 预期输出:
# ════════════════════════════
#   Robot Life MVP - 实时视频检测测试
# ════════════════════════════
# 
# [1/3] 初始化手势检测器...
# [1/3] 打开摄像头...
# [1/3] 读取30帧用于手势测试 (5秒@30fps)...
#   ✓ Frame 0: 检测到 1 个手势
#     - open_palm (confidence=0.85)
#   ...
# ✓ 手势检测器工作正常
# 
# [2/3] 初始化人脸检测器...
# ...
# ✓ 人脸检测器工作正常
#
# [3/3] 初始化眼睛追踪...
# ...
# ✓ 眼睛追踪工作正常
#
# ✅ 所有检测器都工作正常!
```

**可能的问题**:

| 问题 | 症状 | 解决方案 |
|-----|------|--------|
| 摄像头不可用 | "无法读取摄像头" | `ls /dev/video*` 检查设备；或使用`--camera-index 1`尝试其他摄像头 |
| 模型下载缓慢 | 长时间卡住不动 | 检查网络；使用代理或预下载模型到本地 |
| GPU内存不足 | CUDA内存错误 | 减少批处理大小；检查其他GPU进程 |
| InsightFace下载失败 | 模型加载错误 | `pip install insightface[gpu]` 重新安装 |

---

## 🔧 Phase 2.3: 配置参数调优 (20分钟)

### 编辑检测器配置

```bash
# 打开配置文件
vim configs/detectors/default.yaml
```

关键参数说明:

```yaml
mediapipe_gesture:
  enabled: true
  model_complexity: 1        # 0=轻, 1=完整 (可调整精度)
  min_detection_confidence: 0.7  # 置信度阈值
  min_tracking_confidence: 0.5
  static_image_mode: false   # false=视频模式(更快)

insightface:
  enabled: true
  model: "buffalo_l"         # 也可用 "buffalo_m" (更轻)
  use_gpu: true
  det_size: [640, 640]       # 检测图像尺寸
  det_thresh: 0.5            # 人脸检测阈值
  
mediapipe_gaze:
  enabled: true
  model_complexity: 0        # 轻量级
  refine_landmarks: true
```

### 调优建议

基于不同场景:

```yaml
# 场景1: 个人家庭环境 (单人,近距离)
mediapipe_gesture:
  min_detection_confidence: 0.6  # 可以更低
  
insightface:
  det_thresh: 0.4           # 更敏感,检测率更高

# 场景2: 公共/多人环境
mediapipe_gesture:
  min_detection_confidence: 0.8  # 或更高
  
insightface:
  det_thresh: 0.6           # 更严格,假正例更少

# 场景3: 低光/困难环境
mediapipe_gesture:
  model_complexity: 1        # 使用完整模型
  
insightface:
  det_size: [960, 960]      # 更大尺寸,更精确
```

---

## 🧪 Phase 2.4: 集成测试 (30分钟)

### Step 1: 创建综合测试脚本

```bash
cat > test_integrated_pipeline.py << 'EOF'
#!/usr/bin/env python3
"""
完整的事件管道集成测试 (使用实时视频)
"""

import cv2
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from robot_life.event_engine.builder import EventBuilder
from robot_life.event_engine.stabilizer import EventStabilizer
from robot_life.perception.adapters.mediapipe_adapter import MediaPipeGestureDetector
from robot_life.common.schemas import EventPriority

def main():
    print("=" * 60)
    print("  Robot Life MVP - 集成管道测试 (实时视频)")
    print("=" * 60)
    print()
    
    # 初始化组件
    print("[初始化] 创建事件构建器...")
    builder = EventBuilder()
    
    print("[初始化] 创建事件稳定化器...")
    stabilizer = EventStabilizer(
        debounce_count=3,           # 需要3次确认
        debounce_window_ms=1000,    # 在1秒内
        cooldown_ms=2000,
        hysteresis_threshold=0.7
    )
    
    print("[初始化] 初始化手势检测器...")
    detector = MediaPipeGestureDetector()
    detector.initialize()
    
    print("[初始化] 打开摄像头...")
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 30)
    
    print()
    print("开始实时处理 (60秒或3个完整事件)...")
    print("做出手势以触发检测\n")
    
    start_time = time.time()
    stable_events = 0
    frame_count = 0
    
    try:
        while time.time() - start_time < 60 and stable_events < 3:
            ret, frame = cap.read()
            if not ret:
                break
            
            # 检测
            detections = detector.process(frame)
            
            for detection in detections:
                # 构建原始事件
                raw_event = builder.build(detection, priority=EventPriority.P2)
                
                # 稳定化事件
                stable_event = stabilizer.process(raw_event)
                
                if stable_event:
                    elapsed = time.time() - start_time
                    print(f"[{elapsed:5.1f}s] ✓ 事件稳定化成功!")
                    print(f"        类型: {stable_event.event_type}")
                    print(f"        ID: {stable_event.stable_event_id[:12]}...")
                    print(f"        方法: {stable_event.stabilized_by}")
                    print()
                    stable_events += 1
            
            frame_count += 1
            # 显示处理进度
            if frame_count % 30 == 0:
                fps = frame_count / (time.time() - start_time)
                print(f"处理中- Frame {frame_count}, FPS: {fps:.1f}, 稳定事件: {stable_events}")
        
        print()
        print("=" * 60)
        print(f"✓ 测试完成")
        print(f"  处理帧数: {frame_count}")
        print(f"  稳定事件: {stable_events}")
        print(f"  运行时间: {time.time() - start_time:.1f} 秒")
        print("=" * 60)
        
    except KeyboardInterrupt:
        print("\n⏹️ 测试被中断")
    finally:
        cap.release()
        detector.close()
        print("✓ 资源已释放")

if __name__ == "__main__":
    main()
EOF

python3 test_integrated_pipeline.py
```

### Step 2: 验证完整端到端流程

```bash
# 现在运行完整的应用
python3 -m robot_life.app run

# 应该看到:
# ═══════════════════════════════════════════════════════
#      Robot Life MVP Demo - Event Processing Pipeline
# ═══════════════════════════════════════════════════════
# 
# ▶ Scenario 1: Greeting Recognition
#   ...
# ✓ Demo Completed Successfully
```

---

## 📊 Phase 2.5: 性能监控 (15分钟)

### 创建性能监测脚本

```bash
cat > monitor_performance.py << 'EOF'
#!/usr/bin/env python3
"""
监测系统性能指标 (GPU/内存/延迟等)
"""

import sys
import time
import subprocess
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).parent / "src"))

def get_gpu_stats():
    """获取GPU使用统计"""
    try:
        output = subprocess.check_output([
            'nvidia-smi', '--query-gpu=index,name,memory.used,memory.total,utilization.gpu',
            '--format=csv,nounits,noheader'
        ], text=True)
        
        for line in output.strip().split('\n'):
            parts = line.split(',')
            gpu_id = parts[0].strip()
            gpu_name = parts[1].strip()
            mem_used = float(parts[2].strip())
            mem_total = float(parts[3].strip())
            util = float(parts[4].strip())
            
            return {
                'gpu_id': gpu_id,
                'gpu_name': gpu_name,
                'mem_used_mb': mem_used,
                'mem_total_mb': mem_total,
                'mem_percent': (mem_used / mem_total) * 100,
                'utilization_percent': util,
            }
    except:
        return None

def monitor_demo():
    """监测演示运行"""
    print("=" * 70)
    print("  Robot Life MVP - 性能监测")
    print("=" * 70)
    print()
    
    # 初始GPU状态
    print("[初始化] 检查GPU状态...")
    initial_gpu = get_gpu_stats()
    if initial_gpu:
        print(f"  GPU: {initial_gpu['gpu_name']}")
        print(f"  初始内存: {initial_gpu['mem_used_mb']:.0f} / {initial_gpu['mem_total_mb']:.0f} MB")
        print()
    else:
        print("  ⚠️ 无法读取GPU信息")
        print()
    
    # 运行演示
    print("[运行] 启动 robot-life run...")
    start_time = time.time()
    
    try:
        subprocess.run([sys.executable, '-m', 'robot_life.app', 'run'], timeout=120)
    except subprocess.TimeoutExpired:
        print("❌ 超时")
    except KeyboardInterrupt:
        print("⏹️ 中断")
    
    elapsed = time.time() - start_time
    
    # 最终GPU状态
    print()
    print("[结束] 获取最终状态...")
    final_gpu = get_gpu_stats()
    
    if final_gpu:
        print(f"  最终内存: {final_gpu['mem_used_mb']:.0f} / {final_gpu['mem_total_mb']:.0f} MB")
        print(f"  峰值利用: {final_gpu['utilization_percent']:.1f}%")
        print()
    
    # 统计
    print("=" * 70)
    print(f"运行时间: {elapsed:.2f} 秒")
    if initial_gpu and final_gpu:
        mem_delta = final_gpu['mem_used_mb'] - initial_gpu['mem_used_mb']
        print(f"内存增长: {mem_delta:+.0f} MB")
        print(f"GPU利用:  {final_gpu['utilization_percent']:.1f}%")
    print("=" * 70)

if __name__ == "__main__":
    monitor_demo()
EOF

python3 monitor_performance.py
```

---

## ✅ Phase 2 完成检查

### 清单

- [ ] **感知库已安装**
  ```bash
  python3 -c "import mediapipe, insightface, cv2; print('✓')"
  ```

- [ ] **适配器可导入**
  ```bash
  python3 -c "
  from robot_life.perception.adapters.mediapipe_adapter import *
  from robot_life.perception.adapters.insightface_adapter import *
  print('✓')
  "
  ```

- [ ] **视频测试通过**
  ```bash
  python3 test_video_input.py
  # 应显示: ✅ 所有检测器都工作正常!
  ```

- [ ] **集成测试通过**
  ```bash
  python3 test_integrated_pipeline.py
  # 应产生至少1个稳定事件
  ```

- [ ] **配置已调优**
  ```bash
  cat configs/detectors/default.yaml | grep -E "enabled|threshold"
  # 应显示调整后的参数
  ```

- [ ] **性能监测完成**
  ```bash
  python3 monitor_performance.py
  # 应显示GPU/内存统计
  ```

---

## 🚀 phase 3: 后续优化 (如适用)

### 可选的额外改进

1. **YOLO动作检测** (如需要)
   ```bash
   pip install ultralytics  # YOLOv8
   ```

2. **Qwen VL多模态理解** (如有GPU内存充足)
   ```bash
   pip install torch transformers accelerate
   ```

3. **音频处理** (YAMNet)
   ```bash
   pip install librosa tensorflow
   ```

---

## 📝 故障排除

| 问题 | 诊断 | 解决方案 |
|-----|------|--------|
| `ImportError: No module named mediapipe` | 库未安装 | `pip install mediapipe` |
| `CUDA out of memory` | 显存不足 | 减少检测区域或使用批处理 |
| 摄像头列表为空 | 设备未连接 | `lsusb` 检查USB设备 |
| 模型下载超时 | 网络问题 | 使用代理或离线模式 |
| 低FPS (<10) | 性能瓶颈 | 降低模型复杂度或检测分辨率 |

---

## 📞 需要帮助?

1. **检查日志**:
   ```bash
   tail -f logs/*.log
   ```

2. **运行诊断**:
   ```bash
   python3 -c "
   import sys; print(f'Python: {sys.version}')
   import torch; print(f'PyTorch: {torch.__version__}')
   import cv2; print(f'OpenCV: {cv2.__version__}')
   "
   ```

3. **查看配置**:
   ```bash
   cat configs/detectors/default.yaml
   cat configs/runtime/app.default.yaml
   ```

---

**祝您部署顺利! 🎉**
