# 本地运行时深度 Code Review 与优化方案（2026-04-01）

这份报告聚焦两个目标：

1. 审查当前代码结构、资源分配和运行链路
2. 给出一份能实际落地的优化方案，重点回应“内存占用偏大、摄像头画面有点卡”

## 1. 结论摘要

当前系统不是单点故障，而是三类问题叠加：

- 结构层：`live_loop.py` 与 `ui_demo.py` 仍然过大，调优点分散，回归成本高
- 资源层：camera 帧在采集、dispatch、预览三段存在重复拷贝；UI 仍做同步 JPEG 编码
- 配置层：本地主线同时启用了五路感知和语义音频，PANNs 模型本身就很重

对当前本地体验影响最大的不是 scene 逻辑，而是“采集和预览链路”。

## 2. 核心发现

### F1. 高优先级：macOS 上 camera 读帧仍然直接卡在主循环

证据：

- `src/robot_life/runtime/sources.py:34` 在 Darwin 上把 camera read worker 数量直接设为 `0`
- `src/robot_life/runtime/sources.py:331` 到 `src/robot_life/runtime/sources.py:334`，没有 executor 时直接同步 `self._capture.read()`
- `configs/runtime/local/local_mac_fast_reaction.yaml:20` 当前 `async_capture_enabled: false`
- `src/robot_life/runtime/sources.py:821` 到 `src/robot_life/runtime/sources.py:832`，`SourceBundle.read_packets()` 仍按 source 串行读取

影响：

- 只要 AVFoundation 某次读帧慢，整个 fast loop 都会被拖慢
- 这会直接表现为摄像头预览抖动、loop latency 抬高、事件延迟波动

建议：

- 本地 Mac 增加“独立采集进程”或“预览专用采集器”，不要再把同步 `read()` 直接压在主循环上
- 如果短期不拆进程，至少让 UI 预览从感知主帧解耦，优先平滑预览

### F2. 高优先级：UI 预览链路仍然有整帧复制和同步 JPEG 编码

证据：

- `src/robot_life/perception/frame_dispatch.py:63` 到 `src/robot_life/perception/frame_dispatch.py:68`，camera frame 进入 dispatch 时会先做 `np.asarray + np.ascontiguousarray`
- `src/robot_life/runtime/ui_demo.py:502`，预览渲染先 `frame_bgr.copy()`
- `src/robot_life/runtime/ui_demo.py:546`，预览仍在请求路径里做 `cv2.imencode(".jpg", ...)`
- `src/robot_life/runtime/ui_demo.py:3275`，`camera_jpeg()` 在缓存失效时会同步调用 `_render_camera_preview()`

影响：

- 每次预览更新至少发生一次整帧 copy
- 叠加框和文字后还要做 JPEG 编码
- 在 `640x360` 下还可接受，但当 loop 高频、浏览器频繁刷新时，很容易变成明显卡顿

建议：

- 预览分辨率与推理分辨率解耦
- 预览 JPEG 改成后台低频缓存，不要在请求线程现算
- 默认首页预览刷新频率控制在 `2~3 fps`

### F3. 高优先级：本地内存压力主要来自语义音频栈，不是 MediaPipe 模型

证据：

- `models/audio/panns/Cnn14_mAP=0.431.pth` 当前文件大小 `312M`
- `models/mediapipe/face_landmarker.task` 只有 `3.6M`
- `models/mediapipe/gesture_recognizer.task` 只有 `8.0M`
- `configs/detectors/local/local_mac_fast_reaction.yaml:50` 到 `configs/detectors/local/local_mac_fast_reaction.yaml:77`，本地主线默认就会加载 `panns_whisper`

影响：

- 本地内存占用高的主因是 `PANNs + torch runtime + MPS/CPU tensor cache`
- 如果再打开 Whisper，内存和 CPU 压力会进一步上升

建议：

- 把“语义音频”与“UI 演示体验”解耦，允许单独 profile 控制
- 对本地 UI 演示 profile，优先保留 `PANNs + VAD`，Whisper 默认关闭
- 增加延迟加载或按需启用 audio semantics

### F4. 中优先级：`live_loop.py` 仍承担过多职责，难以持续调优

证据：

- `src/robot_life/runtime/live_loop.py` 当前 `1686` 行
- 同一文件里同时负责：
  - source collection
  - async capture / perception / executor worker
  - pending detection backlog
  - scene submission
  - queue drain
  - load shedding
  - decay policy
  - life state update
  - robot context sync

影响：

- 性能问题定位和行为回归排查都变慢
- 某个局部优化容易影响整条链路

建议：

- 至少拆成 4 个层次：
  - capture/perception scheduler
  - event/scene pipeline
  - arbitration/execution orchestration
  - lifecycle/telemetry

### F5. 中优先级：`ui_demo.py` 仍是一个超大“God Module”

证据：

- `src/robot_life/runtime/ui_demo.py` 当前 `3529` 行
- 同时负责：
  - HTML 模板
  - HTTP handler
  - dashboard state 聚合
  - camera preview 渲染
  - 资源采样
  - runtime tuning API

影响：

- UI、状态缓存、资源采样高度耦合
- 很难只改一层而不碰到另一层
- 不利于继续做更轻的展示端

建议：

- 拆成至少三个模块：
  - `dashboard_state.py`
  - `dashboard_http.py`
  - `preview_renderer.py`

### F6. 中优先级：scene priority 计算存在重复仲裁开销

证据：

- `src/robot_life/runtime/scene_ops.py:17` 到 `src/robot_life/runtime/scene_ops.py:22`，`scene_priority()` 为了拿 priority 直接调用一次 `arbitrator.decide(...)`
- `src/robot_life/runtime/scene_coordinator.py:188` 再次用 `scene_priority(scene, resolved_arbitrator)` 做 enrich
- `src/robot_life/runtime/live_loop.py:1291` 到 `src/robot_life/runtime/live_loop.py:1297`，真正提交 batch 时又做一次 `arbitrator.decide(...)`

影响：

- 同一个 scene 在一个 cycle 里会多次触发仲裁规则计算
- 在场景数量多时，属于不必要重复工作

建议：

- 在 `SceneCoordinator._enrich_and_filter_scenes()` 里一次性算出 priority 并写入 payload
- 后续排序和提交直接复用，不再重复 `decide()`

### F7. 中优先级：`/api/state` 仍在请求路径里做系统采样

证据：

- `src/robot_life/runtime/ui_demo.py:3253` 每次公开快照都会调 `psutil.cpu_percent()`
- `src/robot_life/runtime/ui_demo.py:3254` 每次公开快照都会调 `psutil.virtual_memory()`
- 同一个请求还会重新装配 pipeline/source 状态

影响：

- UI 轮询越勤，请求线程上的额外工作越多
- 对本地机器来说不算灾难，但完全可以进一步下沉

建议：

- 增加一个后台资源采样器，每 `500ms` 采一次 CPU / MEM / GPU
- HTTP 层只读缓存，不再主动采样

### F8. 中优先级：麦克风缓存偏保守，更利于容错，不利于低延迟

证据：

- `configs/detectors/local/local_mac_fast_reaction.yaml:103`，`microphone_blocksize: 2048`
- `configs/detectors/local/local_mac_fast_reaction.yaml:104`，`microphone_max_buffer_packets: 48`
- `src/robot_life/runtime/sources.py:565` 到 `src/robot_life/runtime/sources.py:572`，sounddevice callback 每包都构造 `FramePacket`

影响：

- 这不是主内存热点，但本地 UI 体验更看重低延迟，不需要这么深的 mic buffer

建议：

- UI 演示 profile 下调到 `16~24` packets
- 如果真机麦克风稳定，`blocksize` 也可以进一步验证更小值

### F9. 低优先级：`run_forever()` 会累计保存所有结果对象

证据：

- `src/robot_life/runtime/live_loop.py:1029` 初始化 `results: list[LiveLoopResult] = []`
- `src/robot_life/runtime/live_loop.py:1041` 每轮 `results.append(self.run_once())`

影响：

- 对有限迭代测试没问题
- 对长时无上限运行不安全

建议：

- production path 不要返回全量结果列表
- 只在测试或 debug 模式下保留有限窗口

## 3. 系统资源分配审查

### 3.1 当前 `hybrid` 的 CPU / GPU 分配

| 管线 | 设备 |
| --- | --- |
| face | GPU 优先 |
| gesture | CPU |
| gaze | CPU |
| audio / PANNs | `auto`，Mac 上优先 MPS |
| audio / Silero VAD | CPU |
| audio / Whisper | 默认关闭；开启时 CPU |
| motion | CPU |

总体判断：

- 当前 GPU 负载并不平均
- CPU 仍承担了绝大多数数据搬运、预览渲染、motion、gesture、gaze、VAD 和调度工作
- “画面卡”更像是 CPU 和内存带宽问题，不是单纯 GPU 不够

### 3.2 当前最容易浪费内存 / 带宽的位置

1. camera frame 在 dispatch 时变成 contiguous array
2. UI 渲染再 copy 一次
3. JPEG 编码再走一次压缩
4. `DashboardState` 同时缓存原帧、JPEG、事件流、监控快照
5. `PANNs` 自身模型和 runtime 常驻内存较大

## 4. 结构优化方案

### Phase 0：低风险止血，先解决体验问题

目标：

- 让本地 UI 更顺
- 降低 CPU 抖动
- 不动核心仲裁逻辑

动作：

1. 预览与推理解耦
   - 推理仍用 `640x360`
   - 预览单独降到 `480x270` 或更低
2. 预览低频缓存
   - 预览 JPEG 改成后台每 `300~500ms` 更新一次
   - HTTP 请求只返回缓存
3. 资源指标后台采样
   - `cpu/mem/gpu` 不再在 `/api/state` 实时采
4. 麦克风缓冲缩小
   - `max_buffer_packets` 从 `48` 收到 `16~24`
5. 首页只保留最关键卡片
   - 摄像头
   - 最终场景输出
   - 事件流
   - FPS / latency / CPU / GPU

预期收益：

- 摄像头预览更平滑
- UI 请求线程更轻
- CPU 峰值更低

### Phase 1：中风险性能优化

目标：

- 把“预览慢”和“感知慢”彻底分开

动作：

1. 增加 preview encoder worker
   - 单独处理缩略图、标注、JPEG 编码
2. scene priority 只计算一次
   - enrich 时写入 scene payload
   - 排序 / 提交直接复用
3. source stats 与 pipeline stats 改成增量快照
   - 不在每次 HTTP 请求重新组装重对象

预期收益：

- 进一步降低主循环 jitter
- 减少重复排序和状态拼装

### Phase 2：架构收敛

目标：

- 把当前大文件拆开，形成可维护结构

动作：

1. 拆 `live_loop.py`
   - `capture_scheduler.py`
   - `perception_scheduler.py`
   - `scene_pipeline.py`
   - `execution_orchestrator.py`
2. 拆 `ui_demo.py`
   - `dashboard_state.py`
   - `preview_renderer.py`
   - `dashboard_http.py`
3. 把 profile tuning 项单独归档
   - 预算
   - refresh rate
   - source buffer
   - preview quality

预期收益：

- 更容易针对某一层做优化和回归
- 减少 UI 改动影响 runtime 的概率

## 5. 面向“内存占用偏大”的专项建议

### 5.1 最值得先做

- 对本地 UI profile 保持 `Whisper` 默认关闭
- 对语义音频做按需启用
- 把 camera 预览和 dashboard 快照进一步轻量化

### 5.2 不建议误判的方向

- 不建议把“高内存”先归因到 MediaPipe 模型
- 不建议单纯把所有视觉全切 CPU 作为通用解法
- 不建议为了追求异步而在 macOS 上把 `cv2.VideoCapture.read()` 再塞回 Python 线程

## 6. 面向“摄像头画面卡”的专项建议

最优先顺序应当是：

1. 降 preview 分辨率
2. 降 preview refresh 频率
3. 后台缓存 JPEG
4. 让 preview 从 inference 主帧解耦
5. 再考虑更重的 capture 进程化改造

## 7. 推荐落地顺序

### 一周内可做

1. 预览缓存后台化
2. 资源采样后台化
3. 麦克风 buffer 下调
4. `scene_priority` 结果复用

### 两周内可做

1. `ui_demo.py` 模块化
2. `live_loop.py` 拆 capture/perception/execution
3. 本地 UI profile 与五路感知 profile 分离

## 8. 最终判断

当前系统已经具备完整的五路感知、scene 聚合、优先级仲裁和冷却体系，问题不在“有没有架构”，而在“运行时路径过重且耦合过深”。

如果目标是先把本地体验做顺，最该优先优化的是：

1. camera preview 链路
2. UI 快照链路
3. 本地 profile 的音频与缓冲策略

如果目标是中长期可维护，最该优先优化的是：

1. `live_loop.py` 拆层
2. `ui_demo.py` 拆层
3. scene priority / observability 的重复计算收敛
