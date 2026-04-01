# 开源模型升级可行性报告（2026-03-30）

目标：评估当前仓库模型组合是否足以覆盖“生命感交互行为”需求，并给出面向 4090 算力的可落地升级方案。

## 执行摘要

结论先行：当前仓库已经能支撑“快反应原型”，但还不足以完整覆盖产品图中的 4 类生命感交互行为。最大短板不是 face / gesture，而是：

- 音频事件语义识别几乎没有真正开始
- 声源方向定位缺失
- 长尾目标语义不足，尤其是扫地机器人
- 持续注视缺 tracking + head pose + gaze + dwell state 闭环

如果终局明确瞄准 4090，推荐路线不是“单一大模型”，而是：

- `Fast-path`：InsightFace / YOLO11 / PANNs / 6DRepNet / MediaPipe Gesture
- `Second-stage`：L2CS-Net / YOLO-Worldv2 或 GroundingDINO / CLAP / Qwen2-Audio 或 Qwen2.5-Omni
- `硬件升级`：麦克风阵列 + ODAS

## 需求-能力缺口矩阵

| 需求 | 当前能力 | 是否够用 | 核心缺口 |
| --- | --- | --- | --- |
| 主动识人打招呼 | 4090 侧可用 InsightFace；本地仅 MediaPipe face | 部分够用 | 未知用户绑定缺 ASR + identity registry |
| 噪音识别引起注意力 | 只有 `rms_audio` | 不够 | 缺声音事件分类，缺声源方向 |
| 移动物体抢占注意力 | 4090 对 person 基本可做，本地只有 motion | 不够 | 猫/狗/扫地机器人语义覆盖不足 |
| 目光注视触发主动交互 | 仅粗 gaze heuristic | 不够 | 缺 head pose + tracking + dwell state |

## 1. 需求拆解

根据产品图，核心能力可拆成 4 组：

1. 主动识人打招呼
   已认识的人要触发 greeting；未认识的人要引导绑定姓名。
2. 噪音识别引起注意力
   需要区分玻璃破碎、尖叫、爆炸、开关门、哭声、门铃、闹铃、手机铃声等，并在部分场景里朝声源转向。
3. 移动物体抢占注意力
   在无人机交互任务时，对人、猫、狗、扫地机器人等进入视野的目标进行注意力抢占。
4. 目光注视触发主动交互
   需要做持续注视检测，并支持 2m-1.5m、1 分钟、3 分钟这类分层触发。

## 2. 当前仓库模型组合

当前主线模型组合来自这些配置：

- 本地 Mac profile：[local_mac_fast_reaction.yaml](/Users/zheliu/Desktop/robot_life_dev/configs/detectors/local/local_mac_fast_reaction.yaml)
- 4090 profile：[desktop_4090.yaml](/Users/zheliu/Desktop/robot_life_dev/configs/detectors/desktop_4090/desktop_4090.yaml)
- 默认 detector 配置：[default.yaml](/Users/zheliu/Desktop/robot_life_dev/configs/detectors/default.yaml)

实际主线组合是：

- 人脸：
  - 本地：MediaPipe Face Landmarker
  - 4090：InsightFace `buffalo_l_legacy`，失败时回退 MediaPipe
- 手势：MediaPipe Gesture Recognizer
- 注视：MediaPipe face/iris 路线
- 音频：`rms_audio`，本质是响度阈值
- 运动/目标：
  - 本地：OpenCV motion
  - 4090：YOLOv8n（当前 4090 profile 只配了 `classes: [0]`，即 person）

## 3. 当前组合对需求的匹配度

| 需求 | 当前匹配度 | 结论 |
| --- | --- | --- |
| 主动识人打招呼 | 中 | 4090 profile 的 InsightFace 可以支持“已认识/未认识”分流，但本地主线不具备真正的人脸识别 embedding；“未认识用户询问姓名并绑定”还缺语音识别与身份注册链路。 |
| 噪音识别引起注意力 | 低 | 当前 `rms_audio` 只能做“声音变大了”，不能稳定区分玻璃破碎、哭声、门铃、手机铃声等类别；也不具备声源定位能力。 |
| 移动物体抢占注意力 | 低到中 | 本地 OpenCV motion 只有运动，无语义；4090 当前 YOLOv8n 只看 person，不覆盖猫、狗、扫地机器人。 |
| 目光注视触发主动交互 | 中偏低 | MediaPipe iris 可做粗粒度 eye contact / gaze heuristic，但对 2m-1.5m、长时持续注视、多目标稳定跟踪不够稳。 |

结论：当前组合只能覆盖“生命感快反应”的一部分骨架，离图片里的产品需求还有明显差距。最大的短板是：

- 音频事件分类几乎没有真正开始
- 目标语义覆盖不足
- 长时 gaze/attention 还不够可靠
- “未认识的人 -> 询问姓名 -> 绑定身份”缺语音入口
- “朝声源方向转向”缺麦克风阵列或定位算法

## 4.0 候选项目总览

| 方向 | 推荐项目 | 适合位置 | 集成难度 | 主要风险 |
| --- | --- | --- | --- | --- |
| Face ID | [InsightFace](https://github.com/deepinsight/insightface) | Fast-path | 低 | 商业许可需单独确认 |
| Face SDK | [InspireFace](https://github.com/HyperInspire/InspireFace) | Fast-path / SDK层 | 中 | 许可边界与 InsightFace 同源 |
| Audio event | [PANNs](https://github.com/qiuqiangkong/audioset_tagging_cnn) | Fast-path | 中 | 需要类目映射与阈值校准 |
| Audio bootstrap | [YAMNet](https://github.com/tensorflow/models/tree/master/research/audioset/yamnet) | Fast-path | 低 | 依赖旧 Keras 生态，家庭场景仍需校准 |
| Audio second-stage | [AST](https://huggingface.co/MIT/ast-finetuned-audioset-10-10-0.4593) | Second-stage | 中 | 时延更高，偏 clip-level |
| Audio zero-shot | [CLAP](https://github.com/LAION-AI/CLAP) | Second-stage | 中 | 零样本稳定性受 prompt 影响 |
| Audio reasoning | [Qwen2-Audio-7B-Instruct](https://huggingface.co/Qwen/Qwen2-Audio-7B-Instruct) | Second-stage | 中 | 不适合常驻 fast-path |
| Omni reasoning | [Qwen2.5-Omni-7B](https://huggingface.co/Qwen/Qwen2.5-Omni-7B) | Second-stage | 高 | 7B 规模更重 |
| Sound direction | [ODAS](https://github.com/introlab/odas/wiki) | 独立声学链路 | 高 | 必须依赖麦克风阵列 |
| Closed-set detect | [YOLO11](https://docs.ultralytics.com/models/yolo11/) | Fast-path | 低 | AGPL/商业许可需确认 |
| Open-vocab detect | [YOLO-World](https://github.com/AILab-CVC/YOLO-World) | Second-stage | 中 | GPL-3.0，工程栈较重 |
| Open-set verify | [GroundingDINO](https://github.com/IDEA-Research/GroundingDINO) | Second-stage | 中高 | 更重，不适合全帧常驻 |
| Head pose | [6DRepNet](https://github.com/thohemp/6DRepNet) | Fast-path | 中 | 只解决 head pose，不等于 gaze |
| Gaze | [L2CS-Net](https://github.com/Ahmednull/L2CS-Net) | Second-stage | 中 | 需要与 tracking / dwell state 联动 |

## 4. 候选替代 / 升级模型

### 4.1 主动识人打招呼

#### 现状

- 当前 4090 路线使用 InsightFace：
  - 官方仓库：[InsightFace](https://github.com/deepinsight/insightface)
  - 模型包信息：[InsightFace Model Zoo / buffalo_l & antelopev2](https://huggingface.co/Charles-Elena/InstantID/blob/12d0a16dc5cd0fa6a924589d650172544c357e69/insightface/model_zoo/README.md)

已知信息：

- `buffalo_l`：RetinaFace-10GF + ResNet50@WebFace600K，326MB
- `antelopev2`：RetinaFace-10GF + ResNet100@Glint360K，407MB

#### 候选 1：继续用 InsightFace，但从 `buffalo_l_legacy` 升到 `antelopev2`

- 来源：
  - [InsightFace](https://github.com/deepinsight/insightface)
  - [模型包信息](https://huggingface.co/Charles-Elena/InstantID/blob/12d0a16dc5cd0fa6a924589d650172544c357e69/insightface/model_zoo/README.md)
- 核心能力：
  - 人脸检测、对齐、embedding 一体化
  - 对“已认识/未认识”分流最贴合现有系统
- 4090 友好性：
  - 高。当前仓库 already 接了 InsightFace + ONNX Runtime CUDA
- 集成难度：
  - 低到中
- 潜在风险：
  - 模型分发路径、兼容版本、商业使用条款需要单独核查
  - 仍然不是专为远距离低清晰度交互优化

补充一手来源判断：

- [InsightFace](https://github.com/deepinsight/insightface) 官方仓库明确写了它针对训练与部署都做了优化
- 但 2025 年后的 README / wiki 对开源人脸识别模型的商业使用限制写得更明确，量产前必须单独处理 license

#### 候选 2：AdaFace / CVLFace

- 来源：
  - [AdaFace 官方仓库](https://github.com/mk-minchul/AdaFace)
  - [CVLFace 官方仓库](https://github.com/mk-minchul/CVLface)
- 核心能力：
  - 质量自适应的人脸识别，对低质量 / 模糊 /远距脸更友好
- 4090 友好性：
  - 高，PyTorch 路线对 4090 很合适
- 集成难度：
  - 中到高
- 潜在风险：
  - 需要自己补齐检测、对齐、embedding 管线和 gallery 管理
  - 替换成本显著高于 InsightFace 升级

工程结论：

- 短中期继续 `InsightFace`
- 长期如需更工程化 SDK，可评估 `InspireFace`

#### 缺口补齐：未认识用户询问姓名并绑定

这个能力不只是 face model，还需要语音入口：

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
- [Silero VAD](https://github.com/snakers4/silero-vad)

判断：

- 当前仓库没有把 ASR 放进主线 detector profile
- 如果没有 VAD + ASR + identity registry，这条需求不能闭环

### 4.2 噪音识别引起注意力

#### 现状

当前主线音频是 `rms_audio`，只能做阈值触发，无法稳定区分类别，也无法做声源方向。

#### 候选 1：PANNs（优先推荐的工程型升级）

- 来源：[PANNs / audioset_tagging_cnn](https://github.com/qiuqiangkong/audioset_tagging_cnn)
- 核心能力：
  - AudioSet 预训练音频标签识别
  - 支持 sound event detection
- 公开信息：
  - `CNN14` mAP `0.431`
  - `Wavegram-Logmel-CNN` mAP `0.439`
  - 支持 16k checkpoint
- 4090 友好性：
  - 高，标准 PyTorch 推理，单卡可用
- 集成难度：
  - 中
- 潜在风险：
  - 类别粒度仍取决于 AudioSet 标签
  - 如果要稳定区分“玻璃破碎 vs 门铃 vs 手机铃声”，需要做阈值和类目映射

补充判断：

- 这条路线最适合替换当前 `RMS -> 有声音` 的弱语义能力
- 如果只选一个优先升级项，音频应排第一，PANNs 是最合适的 4090 fast-path 候选

#### 候选 2：AST（Audio Spectrogram Transformer）

- 来源：[MIT/ast-finetuned-audioset-10-10-0.4593](https://huggingface.co/MIT/ast-finetuned-audioset-10-10-0.4593)
- 核心能力：
  - AudioSet 分类
  - HF 上可直接推理
- 已知信息：
  - `86.6M params`
  - HF 标注为 Audio Classification / AudioSet fine-tuned
- 4090 友好性：
  - 中到高
- 集成难度：
  - 中
- 潜在风险：
  - 更偏 clip-level 分类，实时 frame-wise 事件定位不如 PANNs 直接

#### 候选 3：CLAP / Whisper-CLAP（适合补长尾零样本类目）

- 来源：
  - [LAION CLAP](https://github.com/LAION-AI/CLAP)
  - [HF: laion/larger_clap_music_and_speech](https://huggingface.co/laion/larger_clap_music_and_speech)
  - [HF: laion/whisper-clap-version-0.1](https://huggingface.co/laion/whisper-clap-version-0.1)
- 核心能力：
  - 文本-音频匹配
  - 适合做 zero-shot audio classification
- 已知信息：
  - LAION 官方给出的更大模型在 ESC50 zero-shot 上达到 `89.98%` / `90.14%`
- 4090 友好性：
  - 中到高
- 集成难度：
  - 中
- 潜在风险：
  - 零样本标签工程会影响线上稳定性
  - 对连续实时事件的时间定位能力不如 SED 模型

#### 候选 4：Silero VAD + faster-whisper（不是替代音频事件分类，而是补对话入口）

- 来源：
  - [Silero VAD](https://github.com/snakers4/silero-vad)
  - [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
- 核心能力：
  - VAD 切分讲话片段
  - ASR 识别“怎么了”“干啥”“我叫张三”这类语音
- 已知信息：
  - Silero VAD：支持 8k / 16k，MIT
  - faster-whisper：官方称在相同精度下可比原版 Whisper 更快、显存更省，并支持 8-bit 量化
- 4090 友好性：
  - 高
- 集成难度：
  - 低到中
- 潜在风险：
  - 这条链路解决的是“说了什么”，不是“什么声音事件发生了”

#### 声源方向问题

如果要做“朝声源方向转向 3 秒”，仅靠单麦克风基本做不到。需要麦克风阵列和声源定位：

- [ODAS](https://github.com/introlab/odas_ros)
- [ManyEars](https://github.com/introlab/manyears)
- [ReSpeaker Lite](https://github.com/respeaker/ReSpeaker_Lite)

结论：

- 没有 mic array，这条需求只能做“注意到了声音”，做不到“朝声源方向”

工程结论：

- `RMS -> YAMNet` 可做第一步
- `RMS -> PANNs` 是更适合 4090 主线的升级
- “朝声源方向转头”必须升级到 `ODAS + 麦阵`

### 4.3 移动物体抢占注意力

#### 现状

- 本地：OpenCV motion，无语义
- 4090：YOLOv8n，但当前只配 `person`

这意味着：

- 人：能做
- 猫 / 狗：当前 4090 主线没开
- 扫地机器人：当前主线完全不支持

#### 候选 1：继续用 YOLOv8 / YOLOv8-pose

- 来源：[Ultralytics YOLOv8](https://docs.ultralytics.com/models/yolov8/)
- 已知信息：
  - `YOLOv8n`：CPU ONNX `142.4ms`，A100 TensorRT `1.21ms`，`3.5M params`
  - `YOLOv8n-pose`：CPU ONNX `131.8ms`，A100 TensorRT `1.18ms`，`3.3M params`
- 4090 友好性：
  - 高
- 集成难度：
  - 低
- 潜在风险：
  - COCO 类别不包含扫地机器人
  - 如果不做自定义训练，只能覆盖 person/cat/dog 这类通用类

#### 候选 2：YOLO-World（开放词表检测）

- 来源：[YOLO-World 官方仓库](https://github.com/AILab-CVC/YOLO-World)
- 核心能力：
  - open-vocabulary detection
  - 能直接用文本 prompt 检“robot vacuum”
- 已知信息：
  - 官方强调 `real-time open-vocabulary object detection`
  - 提供 Hugging Face 权重
- 4090 友好性：
  - 高
- 集成难度：
  - 中
- 潜在风险：
  - GPL-3.0，需要评估商业产品合规
  - 零样本类名稳定性通常不如自定义训练闭集模型

#### 候选 3：Grounding DINO（开放词表，但更偏重型）

- 来源：
  - [GroundingDINO 官方仓库](https://github.com/IDEA-Research/GroundingDINO)
  - [HF model card](https://huggingface.co/IDEA-Research/grounding-dino-base)
- 核心能力：
  - text-conditioned open-set detection
- 已知信息：
  - HF `grounding-dino-base` 约 `0.2B params`
  - Apache-2.0
- 4090 友好性：
  - 中到高
- 集成难度：
  - 中到高
- 潜在风险：
  - 比 YOLO 路线更重，不适合做所有帧 fast path

结论：

- 如果要尽快验证“扫地机器人也会抢占注意力”，先上 YOLO-World / Grounding DINO 做开放词表验证是最快的
- 如果要做量产 fast path，终局还是建议回到定制闭集 detector

### 4.4 目光注视触发主动交互

#### 现状

当前 gaze 路线是 MediaPipe iris heuristic。它适合做“粗 eye contact / head forward”，但对以下场景偏弱：

- 2m 左右中距离持续注视
- 单目 RGB 摄像头下的稳定 gaze vector
- 多人场景下持续 dwell 到具体 target
- 1 分钟 / 3 分钟级长时 attention 统计

#### 候选 1：L2CS-Net

- 来源：[L2CS-Net 官方仓库](https://github.com/Ahmednull/L2CS-Net)
- 核心能力：
  - gaze estimation and tracking
  - 支持 webcam demo
- 4090 友好性：
  - 高
- 集成难度：
  - 中
- 潜在风险：
  - 需要和现有人脸检测/跟踪打通
  - 单目 gaze 在真实家庭光照里仍需阈值调优

#### 候选 2：保留 MediaPipe，但升级为 head pose + gaze fusion

- 来源：
  - 当前仓库已有 MediaPipe face/iris 路线
  - [Python-Gaze-Face-Tracker](https://github.com/alireza787b/Python-Gaze-Face-Tracker) 可作为工程参考
- 核心能力：
  - 用 face landmarks + head pose + iris 偏移量做 attention score
- 4090 友好性：
  - 高
- 集成难度：
  - 低到中
- 潜在风险：
  - 极限精度不如 dedicated gaze model

结论：

- 如果只是“对着机器人看了很久 -> 触发主动问候”，MediaPipe fusion 还能继续压榨
- 如果要把 2m-1.5m + 1 分钟 / 3 分钟做成稳定产品，建议在 4090 路线引入 L2CS-Net 级别的专门 gaze 模型

## 5. 推荐方案

### 5.1 结论先行

当前模型组合不能完整覆盖图片中的产品需求。

它最适合做：

- 已认识人脸触发 greeting 的骨架验证
- 粗粒度 loud sound / motion / gaze 触发验证
- 事件稳定化、仲裁、行为执行链路验证

它不适合直接承诺的能力：

- 精细音频事件识别
- 声源方向转向
- 猫 / 狗 / 扫地机器人全覆盖语义检测
- 长时高可靠 gaze attention
- 未认识用户语音绑定身份

### 5.2 阶段性过渡方案

#### 阶段 1：最小可用升级

- 人脸：保留 InsightFace `buffalo_l_legacy`
- 音频：`rms_audio -> PANNs`
- 语音：补 `Silero VAD + faster-whisper`
- 目标：4090 路线至少把 YOLO 类别从 `person` 扩到 `person/cat/dog`
- gaze：继续 MediaPipe，但把 dwell timers 做完整

这个阶段的价值：

- 工程改动最小
- 能把产品图里 4 个能力的骨架都“碰到”
- 先验证仲裁逻辑和交互价值

#### 阶段 2：开放词表验证

- 对“扫地机器人”等长尾目标，引入 YOLO-World 或 Grounding DINO 做验证
- 对音频长尾类目，引入 CLAP 做 zero-shot 补类

这个阶段的价值：

- 最快覆盖长尾需求
- 用最少数据先看产品价值

代价：

- 线上稳定性和推理成本不如闭集模型

### 5.3 终局 4090 方案

建议的 4090 终局 fast/slow 组合：

- 人脸识别：
  - 短期：InsightFace `buffalo_l` / `antelopev2`
  - 中期：若远距和低质脸识别不够，再评估 AdaFace/CVLFace
- 手势：
  - 保留 MediaPipe Gesture 作为 fast path
  - 若后续要更多复杂动作，再补 YOLOv8-pose / 自定义 skeleton classifier
- 注视：
  - `MediaPipe face track -> L2CS-Net gaze -> dwell/attention aggregator`
- 音频：
  - `Silero VAD`：切语音片段
  - `faster-whisper`：识别用户说话内容
  - `PANNs`：主音频事件分类 / SED
  - `CLAP`：长尾零样本音频补类
  - `ODAS + mic array`：声源方向
- 目标语义：
  - 过渡：YOLO-World / Grounding DINO
  - 终局：基于真实家庭数据，训练定制闭集 detector，覆盖 `person / cat / dog / robot vacuum / stroller / package ...`

## 6. 替换成本总结

| 模块 | 推荐候选 | 替换成本 | 风险 |
| --- | --- | --- | --- |
| face | InsightFace `antelopev2` | 低到中 | 模型分发、license 核查 |
| face（高阶） | AdaFace / CVLFace | 中到高 | 需要补 detection/alignment/gallery |
| audio event | PANNs | 中 | 类别映射和阈值调优 |
| audio zero-shot | CLAP | 中 | 标签工程、稳定性 |
| speech | Silero VAD + faster-whisper | 低到中 | GPU/延迟预算 |
| object open-vocab | YOLO-World | 中 | GPL-3.0 风险 |
| object open-vocab | Grounding DINO | 中到高 | 更重，不适合全帧快路径 |
| gaze | L2CS-Net | 中 | 需要和 face track 融合 |
| sound direction | ODAS + mic array | 高 | 需要新增硬件，不是纯算法替换 |

## 7. 最终判断

如果目标只是当前仓库继续验证“生命感交互”链路，当前组合够做 MVP 骨架。

如果目标是贴近图片里的产品需求，优先级应该是：

1. `rms_audio -> PANNs`
2. `补 Silero VAD + faster-whisper`
3. `YOLO person-only -> 至少 person/cat/dog + 开放词表补 robot vacuum`
4. `MediaPipe gaze heuristic -> L2CS-Net + dwell attention`
5. `若要朝声源方向转向，新增 mic array + ODAS`

面向 4090 的终局路线是可行的，但前提是把“音频事件分类”和“目标语义检测”从当前的启发式/缩减版 baseline 升起来。

## 参考来源

- MediaPipe Gesture Recognizer: [Google AI Edge](https://ai.google.dev/edge/mediapipe/solutions/vision/gesture_recognizer)
- InsightFace: [GitHub](https://github.com/deepinsight/insightface)
- InsightFace model pack info: [Hugging Face mirror](https://huggingface.co/Charles-Elena/InstantID/blob/12d0a16dc5cd0fa6a924589d650172544c357e69/insightface/model_zoo/README.md)
- Ultralytics YOLOv8 docs: [docs.ultralytics.com](https://docs.ultralytics.com/models/yolov8/)
- YOLO-World: [GitHub](https://github.com/AILab-CVC/YOLO-World)
- Grounding DINO: [GitHub](https://github.com/IDEA-Research/GroundingDINO), [Hugging Face model card](https://huggingface.co/IDEA-Research/grounding-dino-base)
- PANNs: [GitHub](https://github.com/qiuqiangkong/audioset_tagging_cnn)
- AST AudioSet model: [Hugging Face](https://huggingface.co/MIT/ast-finetuned-audioset-10-10-0.4593)
- CLAP: [GitHub](https://github.com/LAION-AI/CLAP), [Hugging Face pipeline example](https://huggingface.co/laion/larger_clap_music_and_speech)
- faster-whisper: [GitHub](https://github.com/SYSTRAN/faster-whisper)
- Silero VAD: [GitHub](https://github.com/snakers4/silero-vad)
- L2CS-Net: [GitHub](https://github.com/Ahmednull/L2CS-Net)
- ODAS / mic array localization: [ODAS ROS](https://github.com/introlab/odas_ros), [ManyEars](https://github.com/introlab/manyears), [ReSpeaker Lite](https://github.com/respeaker/ReSpeaker_Lite)
