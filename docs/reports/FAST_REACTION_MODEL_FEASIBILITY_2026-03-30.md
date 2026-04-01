# 快反应模型可行性与升级报告（2026-03-30）

## 结论摘要

基于当前仓库的模型组合，系统已经具备“基础快反应原型”的能力，但**还不能完整覆盖图中 4 类产品需求**。

当前组合大致是：

- 本地 Mac 基线：
  - 人脸 / 注视：MediaPipe Face + Iris
  - 手势：MediaPipe Gesture
  - 音频：RMS loud sound heuristic
  - 移动物体：OpenCV motion
- 4090 主线：
  - 人脸识别：InsightFace `buffalo_l_legacy`
  - 手势 / 注视：MediaPipe
  - 音频：RMS loud sound heuristic
  - 移动物体：YOLO

核心判断：

1. 主动识人打招呼：`4090 路线部分具备，本地路线不具备完整识人`
2. 噪音识别引起注意力：`当前明显不具备`
3. 移动物体抢占注意力：`对人/猫/狗部分具备，对扫地机器人不具备`
4. 目光注视触发主动交互：`近距离粗略可做，产品级持续注视判断还不够`

如果终局瞄准 4090，我建议采用：

- 识人：`InsightFace / InspireFace`
- 目标检测：`YOLO11 + YOLO-Worldv2 + tracking`
- 注视与注意力：`6DRepNet + MediaPipe / L2CS-Net`
- 声音事件：`PANNs 或 AST`
- 声源方向：`ODAS + 麦克风阵列`
- 稀疏多模态复核：`Qwen2-Audio / Qwen2.5-Omni`

## 一、按需求看当前模型组合是否够用

### 1. 主动识人打招呼

需求拆解：

- 判断是不是“认识的人”
- 不认识时引导绑定名字
- 打招呼配合表情和上肢动作

当前能力判断：

- 4090 路线里，InsightFace 可以承担“已知人脸识别”的核心能力，这一项**基本可做**
- 本地 Mac 路线默认是 MediaPipe face，不做身份识别，所以**本地真机体验只能验证有人脸，不足以验证熟人 greeting**
- “未识别用户 -> 主动询问名字 -> 用户信息绑定”本质上不是模型问题，而是**身份库、绑定流程、UI/语音交互流程**问题，当前仓库没有形成完整闭环
- “表情和上肢动作”主要取决于行为树 / 执行器，不是感知模型瓶颈

结论：

- `4090 原型：可做`
- `本地验证：只能部分验证`
- `量产：还缺身份绑定与 face gallery 管理`

### 2. 噪音识别引起注意力

需求拆解：

- 识别玻璃破碎、尖叫、爆炸声
- 识别开关门、孩子哭声、门铃、闹铃、手机铃声
- 某些场景要“朝声源方向转向 3s”

当前能力判断：

- 当前仓库音频链路默认是 `RMS loud sound`，只能感知“声音大了”，**不能识别声音类别**
- 因此“玻璃碎裂 / 门铃 / 哭声 / 手机铃声”这类事件，现在都**做不到可靠区分**
- 更关键的是，“朝声源方向转向”不是分类问题，而是**声源定位问题**
- 如果仍使用单麦克风或笔记本麦克风，基本不可能稳定实现方向定位；这需要**麦克风阵列 + 声源定位**

结论：

- `当前：不具备`
- `需要新模型 + 新硬件形态`

### 3. 移动物体抢占注意力

需求拆解：

- 当无交互任务时，识别人 / 猫 / 狗的移动并做目光跟随
- 扫地机器人需要作为特殊注意力抢占对象

当前能力判断：

- 4090 路线的 YOLO 对 `person / cat / dog` 是可做的，这部分**基本够用**
- 本地 Mac 路线的 OpenCV motion 只能检测“有运动”，不能区分是人、猫、狗还是其它物体
- “扫地机器人”不是当前默认主线里的稳定类别，单靠 COCO 通用类检测并不可靠

结论：

- `人/猫/狗：4090 路线可做`
- `扫地机器人：当前不够`
- `本地 Mac：只能验证 motion，不足以验证语义抢占`

### 4. 目光注视触发主动交互

需求拆解：

- 识别 2m-1.5m 范围内有人持续看自己
- 持续 1 分钟触发一次主动询问
- 持续 3 分钟且没有语言互动，触发腼腆动作

当前能力判断：

- 现有 MediaPipe Iris / Face Landmarker 可以支持近距离粗略 gaze / face orientation 判断
- 但产品需求是**中距离、长时序、持续注视**，这对单帧 gaze 不够，必须叠加：
  - face tracking
  - head pose
  - gaze / eye-contact 估计
  - 长时序计时与身份关联
- 所以现在仓库可以做“粗略有人看过来”的原型，不足以做“1 分钟 / 3 分钟”这种稳定产品逻辑

结论：

- `当前：部分具备，但不够产品级`

## 二、最关键的差距

### 差距 1：音频链路只有“响度”，没有“声音语义”

这是最大短板。图里的第二栏基本都依赖**声音事件识别**，而当前只有 RMS。

### 差距 2：没有声源方向定位能力

如果产品真的需要“朝声源方向转头”，那么单麦克风路线不够，需要麦克风阵列和 DOA / SSL。

### 差距 3：注视是产品逻辑，不只是单模型

1 分钟、3 分钟这种规则要求：

- 稳定 tracking
- 身份一致性
- gaze / head pose 连续估计
- 对话状态感知

不是换一个 gaze 模型就能自动解决。

### 差距 4：扫地机器人属于自定义语义目标

对这种类目，最稳的终局一般不是“盲信通用模型”，而是：

- 先用 open-vocabulary 模型快速验证
- 再用自有数据做一个稳定微调类

## 三、候选升级模型与可行性

### A. 人脸识别：保留 InsightFace 路线，或评估 InspireFace

#### 方案 A1：继续使用 InsightFace

- 适合用途：熟人识别、identity embedding、face gallery
- 优点：
  - 现有仓库已经接入
  - 能力成熟
  - 改造成本最低
- 风险：
  - 上游对开源识别模型的商业授权有额外说明，量产前必须确认许可
- 替换成本：`低`

建议：

- 4090 原型期继续沿用
- 商业化前优先解决 license 和模型版本收敛

#### 方案 A2：评估 InspireFace

- 适合用途：跨平台 face SDK、检测 / 对齐 / 跟踪 / 识别统一化
- 优点：
  - C/C++ SDK，后续更适合产品化和多端部署
  - 支持 CPU / GPU / NPU 后端
  - 近两年持续有 release
- 风险：
  - 其开源模型许可要求与 InsightFace 同源，商业约束仍需确认
  - 需要重新适配 Python / runtime 接口
- 替换成本：`中`

建议：

- 如果目标是长期量产工程，InspireFace 值得做 PoC
- 但它不是当前最紧迫瓶颈，优先级低于音频和 attention

### B. 音频事件识别：从 RMS 升级到语义分类

#### 方案 B1：YAMNet

- 适合用途：轻量级 always-on 声音分类 baseline
- 优点：
  - 521 类 AudioSet 标签
  - 轻量、易部署
  - 非常适合先把“玻璃碎裂 / 哭声 / 门铃 / 铃声”等事件做出第一版
- 风险：
  - 类别颗粒度和边界不一定完全贴产品
  - 对复杂家庭环境误报仍可能较高
- 替换成本：`低`

建议：

- 可以作为从 RMS 升级到“可分类”的第一步
- 但不建议作为 4090 终局方案

#### 方案 B2：PANNs

- 适合用途：AudioSet 音频标签分类 / SED baseline
- 优点：
  - 明确支持 audio tagging 和 sound event detection
  - 在 AudioSet 上显著强于 Google baseline
  - 比 YAMNet 更适合做“声音事件识别主干”
- 风险：
  - 工程侧需要自己做窗口化、阈值、事件后处理
  - 维护热度不如 Ultralytics / Qwen 这类项目
- 替换成本：`中`

建议：

- 作为 4090 快反应音频主干是可行的
- 若只做固定类别事件，比 Qwen2-Audio 更合适

#### 方案 B3：AST

- 适合用途：更强的音频分类 backbone
- 优点：
  - Transformer 路线，能力上限更高
  - Hugging Face 生态接入方便
- 风险：
  - 推理成本高于 YAMNet / 轻量 CNN
  - 更适合作为 4090 路线，而不是边缘低算力常驻
- 替换成本：`中`

建议：

- 可作为 4090 上的高质量音频分类主模型
- 如果追求更稳的玻璃破碎 / 尖叫 / 门铃识别，优先级高于 YAMNet

#### 方案 B4：CLAP

- 适合用途：零样本 / 开集音频检索与重排序
- 优点：
  - 音频和文本共享表示
  - 适合“我想快速测 doorbell / phone ringtone / vacuum cleaner 是否可被 prompt 命中”
- 风险：
  - 更像检索 / zero-shot 表征，不是直接拿来就稳定做实时事件分类
  - 产品落地通常仍要配固定类别校准
- 替换成本：`中`

建议：

- 适合做探索层或 teacher / reranker
- 不建议独立承担 fast-path 主分类器

#### 方案 B5：Qwen2-Audio / Qwen2.5-Omni

- 适合用途：复杂、模糊、低频音频事件的二级复核与自然语言解释
- 优点：
  - 明确支持 audio analysis
  - 模型能理解更复杂的音频语义
  - 对“这是什么声音 / 发生了什么”非常适合
- 风险：
  - 7B 级别不适合常驻 fast-path
  - 时延和显存明显高于纯分类模型
- 替换成本：`高`

建议：

- 不要直接替代 fast-path
- 更适合做 4090 上的 second-stage verifier / narrator

### C. 声源方向：ODAS + 麦克风阵列

#### 方案 C1：ODAS

- 适合用途：声源定位、跟踪、分离、后滤波
- 优点：
  - 就是为 robot audition / mic array 做的
  - 开源、成熟
  - 适合“朝声源方向转头”这类能力
- 风险：
  - 必须配麦克风阵列
  - 与当前单麦克风链路不是一个改造量级
- 替换成本：`高`

建议：

- 如果“转向声源”是正式需求，ODAS 方向几乎是必做项
- 但这属于“音频硬件 + 软件协同升级”，不是单纯换模型

### D. 移动物体 / 抢占：YOLO 系继续升级

#### 方案 D1：YOLO11

- 适合用途：人 / 猫 / 狗等封闭类别目标检测与 tracking
- 优点：
  - 速度和精度比旧 YOLOv8 更好
  - 生态成熟
  - 4090 上非常友好
- 风险：
  - 对扫地机器人这类非标准类目，仍需要自定义数据或 open-vocab 补足
- 替换成本：`低到中`

建议：

- 作为封闭集主检测器，推荐直接替换当前 YOLOv8n baseline

#### 方案 D2：YOLO-Worldv2

- 适合用途：开放词汇检测，例如“robot vacuum”
- 优点：
  - real-time open-vocabulary
  - 支持 tracking
  - 比 GroundingDINO 更适合在线阶段
- 风险：
  - 对长尾目标稳定性仍不如自定义微调
  - prompt 设计需要调试
- 替换成本：`中`

建议：

- 非常适合作为“扫地机器人”这类类目的验证工具
- 终局可作为 open-vocab 入口，后续再蒸馏成封闭类检测器

#### 方案 D3：GroundingDINO

- 适合用途：更强的 open-set / phrase grounding
- 优点：
  - 开放集能力强
  - 对复杂文本目标更灵活
- 风险：
  - 推理更重
  - 更适合慢路径或稀疏验证，不适合一直常驻 fast-path
- 替换成本：`中到高`

建议：

- 用作离线评估、数据自动标注或 teacher 模型
- 不建议直接拿来做 30FPS 的主快反应链路

### E. 注视 / 注意力：6DRepNet + MediaPipe，L2CS-Net 作为增强项

#### 方案 E1：6DRepNet

- 适合用途：head pose estimation
- 优点：
  - 对“是否在朝向我”这类注意力判断非常实用
  - 计算成本相对可控
  - 比单纯 eye gaze 在 1.5m-2m 更稳
- 风险：
  - 它解决的是 head pose，不是精确 eye contact
- 替换成本：`中`

建议：

- 这是当前最值得先加的 attention 模块
- 先做“朝向 + face track + time window”，比直接追纯 gaze 更稳

#### 方案 E2：L2CS-Net

- 适合用途：细粒度 gaze estimation
- 优点：
  - 专注 gaze estimation and tracking
  - 可作为 close-range gaze 增强
- 风险：
  - 上游维护节奏相对一般
  - 远距离场景仍会受限
- 替换成本：`中到高`

建议：

- 不建议一开始就把它作为唯一 attention 主干
- 更适合叠加在 `6DRepNet + MediaPipe` 之上做增强

## 四、推荐路线

### 路线 1：最小可落地升级

目标：在现有架构上尽快满足大部分产品需求。

- 识人：继续用 InsightFace
- 音频：RMS -> YAMNet 或 PANNs
- 物体：YOLOv8n -> YOLO11m
- 注视：MediaPipe + 6DRepNet
- 方向：暂不做精确 DOA，只做“有大声音先看向前方或上一次可能目标方向”

优点：

- 工程改造量最小
- 最快形成 4090 可演示版

缺点：

- “朝声源方向”仍然不是真正完成
- “扫地机器人”仍可能不稳

### 路线 2：推荐的 4090 主线

目标：把产品图中的四类能力都推到可用水平。

- Face：
  - 继续 InsightFace，或评估 InspireFace SDK
- Attention：
  - face track + 6DRepNet head pose
  - 近距离可叠加 L2CS-Net / MediaPipe iris
- Object：
  - YOLO11m 负责人 / 猫 / 狗
  - YOLO-Worldv2 验证开放类 `robot vacuum`
  - 稳定后再做自定义 fine-tune
- Audio：
  - PANNs 或 AST 作为 fast-path 音频语义分类
  - Qwen2-Audio / Qwen2.5-Omni 作为稀疏复核
- Sound Direction：
  - 麦克风阵列 + ODAS

优点：

- 最符合产品需求
- 4090 能吃下这条链路

缺点：

- 集成复杂度明显上升
- 音频硬件要升级

### 路线 3：量产终局

推荐终局不是“所有能力都塞进一个大模型”，而是：

- 快路径：
  - Face / Head Pose / Object / Audio Event 小模型常驻
- 慢路径：
  - Qwen2.5-Omni 或 Qwen2-Audio 做复核、解释、话术生成
- 设备侧：
  - 麦克风阵列做 DOA
  - 目标跟踪和身份状态机做分钟级持续判断

这样才能兼顾：

- 低时延
- 可解释
- 工程可维护
- 4090 算力利用率

## 五、替换成本与潜在问题

### 低成本

- InsightFace 继续沿用
- YOLOv8n -> YOLO11m
- RMS -> YAMNet

### 中成本

- RMS -> PANNs / AST
- MediaPipe attention -> 6DRepNet + tracking
- YOLO -> YOLO-Worldv2
- InsightFace -> InspireFace

### 高成本

- 增加声源定位：ODAS + 麦克风阵列
- 引入 Qwen2-Audio / Qwen2.5-Omni 做在线复核
- 把“未知用户绑定 + 长时注视 + 对话状态”做成真正产品闭环

### 关键风险

1. `音频方向` 不是单模型问题，必须有阵列硬件。
2. `注视 1 分钟 / 3 分钟` 不是单帧模型问题，必须有时序状态机。
3. `扫地机器人` 这种类目，通用检测不一定稳定，最好最终做自有类微调。
4. `InsightFace / InspireFace` 量产前必须确认 license。

## 六、最终建议

如果你们的终局明确瞄准 4090，我建议下一阶段优先级这样排：

1. 先把音频从 RMS 升级到 `PANNs 或 AST`
2. 给 attention 链路补 `6DRepNet`
3. 给物体链路补 `YOLO11m`，并用 `YOLO-Worldv2` 验证扫地机器人
4. 如果“朝声源方向”是强需求，立刻立项 `ODAS + 麦克风阵列`
5. 最后再把 `Qwen2-Audio / Qwen2.5-Omni` 接成二级复核器，而不是 fast-path 主模型

## 参考来源

- [InsightFace](https://github.com/deepinsight/insightface/wiki/Model-Zoo)
- [InspireFace](https://github.com/HyperInspire/InspireFace)
- [YAMNet](https://www.tensorflow.org/hub/tutorials/yamnet)
- [PANNs / audioset_tagging_cnn](https://github.com/qiuqiangkong/audioset_tagging_cnn)
- [AST on Hugging Face](https://huggingface.co/MIT/ast-finetuned-audioset-10-10-0.4593)
- [LAION CLAP](https://github.com/LAION-AI/CLAP)
- [ODAS](https://github.com/introlab/odas)
- [YOLO11 Docs](https://docs.ultralytics.com/models/yolo11/)
- [YOLO-World Docs](https://docs.ultralytics.com/models/yolo-world/)
- [GroundingDINO](https://github.com/IDEA-Research/GroundingDINO)
- [6DRepNet](https://github.com/thohemp/6DRepNet)
- [L2CS-Net](https://github.com/Ahmednull/L2CS-Net)
- [Qwen2-Audio-7B-Instruct](https://huggingface.co/Qwen/Qwen2-Audio-7B-Instruct)
- [Qwen2.5-Omni-7B](https://huggingface.co/Qwen/Qwen2.5-Omni-7B)
