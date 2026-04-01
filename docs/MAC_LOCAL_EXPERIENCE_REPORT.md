# Mac 本地体验环境分析报告

更新时间：2026-03-29
分析对象：`/Users/zheliu/Desktop/robot_life_dev`

## 1. 结论摘要

当前这台 Mac 可以作为本地体验机，支持：

- 本地摄像头接入路径
- 本地麦克风接入路径
- UI Demo 浏览器体验
- CPU 路径下的快反应基础验证

当前这台 Mac 不适合作为项目主线定义里的“GPU 真机体验机”，原因是：

- 本机为 Apple M1，非 NVIDIA GPU
- 项目当前正式 profile 和大部分性能/验证文档以 `CUDA / RTX 4090` 为主
- 代码中的 GPU 加速判断主要围绕 `torch.cuda`、`CUDAExecutionProvider`、`onnxruntime-gpu`
- 未看到针对 Apple Silicon `Metal / MPS` 的正式运行路径

一句话判断：

- `摄像头 + 麦克风 + UI + CPU 快链体验`：有机会跑通
- `本地 GPU 体验`：当前基本不成立
- `按仓库当前正式 baseline 完整体验`：不成立

## 2. 本机配置事实

通过本机命令探测得到：

- 机型：`MacBookPro17,1`
- 芯片：`Apple M1`
- CPU：`8 cores (4P + 4E)`
- GPU：`Apple M1 8-core GPU`
- 内存：`16 GB`
- 系统：`macOS 26.4`
- 架构：`arm64`
- Metal：支持

Python 与运行时现状：

- 系统 `python3`：`/opt/homebrew/bin/python3`
- 版本：`Python 3.9.5`
- 项目声明要求：`>=3.10`

这意味着即使硬件能支持部分本地体验，当前 Python 基础环境也不满足项目声明。

## 3. 本机依赖探测结果

基于当前系统 Python 探测到：

- `cv2`: OK `4.13.0`
- `sounddevice`: OK `0.5.5`
- `mediapipe`: OK `0.10.33`
- `onnxruntime`: OK `1.19.2`
- `torch`: OK `2.8.0`
- `ultralytics`: OK `8.4.31`
- `numpy`: OK `2.0.2`
- `insightface`: FAIL `TypeError: bases must be types`
- `transformers`: FAIL `ModuleNotFoundError`

设备探测结果：

- `sounddevice.query_devices()` 返回 `device_count=0`
- 默认音频设备为 `[-1, -1]`

PyTorch 设备探测结果：

- `torch.cuda.is_available() = False`
- `torch.backends.mps.is_available() = False`

这说明两件事：

1. 当前 shell 环境下并没有一个可用的 CUDA 或 MPS 推理设备被 PyTorch 识别到。
2. 即便 `sounddevice` 包已安装，当前 Python 进程没有探测到任何可用音频设备，真实麦克风链路暂时不能视为“已就绪”。

## 4. 项目代码对 Mac 本地体验的支持情况

### 4.1 摄像头

代码层面有本地摄像头支持：

- `CameraSource` 基于 OpenCV `cv2.VideoCapture`
- UI demo 可显示实时相机画面
- `run_demo_mac.sh` 明确提示接受 macOS 摄像头权限

判断：

- 从代码设计上看，Mac 摄像头路径是存在的
- 成败主要取决于：
  - OpenCV 在本机能否打开 AVFoundation 相机
  - macOS 权限是否已授予
  - 当前 Python 环境是否可正常启动项目

结论：

- 摄像头是“代码支持，但尚未在本机完成验证”

### 4.2 麦克风

代码层面对麦克风有三层路径：

1. `SoundDeviceMicrophoneSource`
2. Linux 下的 `ArecordMicrophoneSource`
3. 最后退回 `MicrophoneSource()` 静音源

`build_live_microphone_source()` 的逻辑是：

- 优先 `sounddevice`
- 如果失败，再尝试 `arecord`
- 再失败则退成静音麦克风

对 Mac 来说：

- `arecord` 基本不适用
- 真正可用的路径只有 `sounddevice`

而当前探测里：

- `sounddevice` 虽然已安装
- 但 `query_devices()` 返回 0 个设备

这意味着当前机器上的“真实麦克风体验”风险较高，实际运行时很可能退回静音源。

结论：

- 麦克风链路代码是支持 Mac 的
- 但当前本机探测结果并不能证明麦克风可用
- 在当前状态下，不应把“可体验真实麦克风”视为已满足

### 4.3 GPU

项目当前 GPU 路线几乎全部围绕 NVIDIA/CUDA：

- `common/cuda_runtime.py` 只处理 CUDA `.so`
- `pipeline_factory.py` 默认优先 `CUDAExecutionProvider`
- `InsightFace`、`YOLOMotionDetector`、GGUF slow-scene 都优先或要求 CUDA
- `QwenVLAdapter` 只在 `cuda` 与 `cpu` 之间切换，没有正式的 `mps` 路径

同时，仓库文档中的正式基线也明确是：

- `desktop_4090_*`
- `RTX 4090`
- `CUDAExecutionProvider -> CPUExecutionProvider`

本机是 Apple M1：

- 没有 CUDA
- 当前 PyTorch 也没有报告 MPS 可用
- 项目里没有正式 Apple GPU baseline

结论：

- 本机 GPU 不能承接这个项目当前定义下的“GPU 体验”

### 4.4 慢思考 / 本地多模态

慢思考有两条实现：

- `QwenVLAdapter`：`transformers + torch`
- `GGUFQwenVLAdapter`：`llama.cpp / GGUF`

问题在于：

- 当前系统缺少 `transformers`
- `QwenVLAdapter` 设备逻辑以 `cuda/cpu` 为主，没有正式 MPS 主线
- `GGUFQwenVLAdapter` 初始化默认仍偏向 GPU offload/CUDA 语义

结论：

- Mac 上理论上可以走 CPU 慢思考或某些手工配置的 GGUF 路线
- 但它不是仓库现在的正式、低风险本地体验路径

## 5. 与仓库当前正式目标的匹配度

从文档看，项目当前的“正式可回归 baseline”是：

- `face / gesture / gaze / audio / motion`
- 4090 桌面端
- 快反应优先
- CUDA/GPU profile

因此本机和正式目标的匹配度如下：

- UI 展示与链路理解：高
- Mock 模式验证：高
- CPU 摄像头体验：中
- 真实麦克风体验：低到中
- 正式 GPU 快链验证：低
- 正式慢思考本地模型体验：低

## 6. 当前是否“可以体验”

### 可以期待体验的部分

- `mock mode` 的 UI demo
- 摄像头画面进 UI
- 基于 MediaPipe / OpenCV 的部分 CPU 快反应体验
- 事件稳定化、场景聚合、仲裁、UI 面板观察

### 不能指望的部分

- 4090 文档里的正式性能指标
- CUDA 加速的 face / motion / slow-scene 体验
- 按正式 baseline 完整复现 4090 快反应 profile
- 把本机 GPU 当成仓库当前主线 GPU

## 7. 阻塞项

当前要在这台 Mac 上做“本地真机体验”，至少有这些阻塞：

1. Python 版本不满足项目要求
   - 当前 `3.9.5`
   - 项目要求 `>=3.10`

2. 项目虚拟环境状态异常
   - `.venv` 与当前宿主 Python 不一致

3. 麦克风设备探测失败
   - `sounddevice` 无可见设备

4. `insightface` 当前导入失败
   - 面部识别主链路不可靠

5. `transformers` 未安装
   - 慢思考默认实现不可用

6. 当前 GPU 路线与 Apple Silicon 不匹配
   - 项目主线是 CUDA，不是 Metal/MPS

## 8. 最终判断

最终判断分三档：

- 是否能在这台 Mac 上做“本地项目理解与 UI 演示”：可以
- 是否能在这台 Mac 上做“摄像头为主的轻量快反应体验”：大概率可以，但需要修复 Python 环境并现场验证权限与 OpenCV 相机打开情况
- 是否能在这台 Mac 上做“本地摄像头 + 麦克风 + GPU 的完整体验”：当前不能这么判断，其中 GPU 基本不成立，麦克风也未验证通过

## 9. 建议路线

如果目标是“尽快在这台 Mac 上体验一下项目”，建议路线是：

1. 先修复 Python 环境到 `3.10/3.11`
2. 重建 `.venv`
3. 先跑 mock UI
4. 再跑摄像头-only UI
5. 单独验证 `sounddevice` 麦克风设备
6. 不把 GPU 作为这台机器的目标

如果目标是“体验仓库当前正式 baseline”，建议直接换到：

- 有 NVIDIA GPU 的 Linux/4090 机器

