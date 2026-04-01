# 桌面端开发目录与命名规范

## 1. 目标

本规范用于统一桌面端 MVP 开发目录、命名方式和文档放置规则，避免后续开发阶段出现结构混乱、职责不清和脚本堆积。

---

## 2. 根目录建议

```text
robot_life_dev/
  docs/
  configs/
  data/
  logs/
  runtime/
  scripts/
  src/
  tests/
  tools/
```

---

## 3. 源码目录建议

```text
src/
  common/
  perception/
  event_engine/
  behavior/
  slow_scene/
```

### common

放通用基础设施：

- schema
- tracing
- logging
- config
- time utilities

### perception

放统一感知模块及其子 pipeline：

- face
- gesture
- gaze
- audio
- motion
- common

### event_engine

放事件链路主模块：

- event_builder
- event_stabilizer
- scene_aggregator
- arbitrator
- cooldown_manager
- state_store

### behavior

放行为执行模块：

- behavior registry
- resource_manager
- bt_executor
- adapters
- mock_drivers

### slow_scene

放慢思考链路：

- context_builder
- qwen_adapter
- scene_schema
- cloud_bridge

---

## 4. 配置目录建议

建议按配置职责拆分，而不是按人拆分：

```text
configs/
  detectors/
  stabilizer/
  scenes/
  arbitration/
  behavior/
  runtime/
```

命名建议：

- `face.default.yaml`
- `gesture.default.yaml`
- `cooldown.default.yaml`
- `scene_rules.v1.yaml`
- `arbitration.v1.yaml`

---

## 5. 文档目录建议

`docs/` 内建议使用编号命名，便于版本和阅读顺序管理：

- `00_project_structure.md`
- `01_prd.md`
- `02_sdd.md`
- `03_validation_4090.md`
- `04_migration_orin_nx.md`
- `05_event_schema.md`
- `06_scene_rules.md`
- `07_behavior_list.md`

---

## 6. 测试目录建议

```text
tests/
  unit/
  integration/
  replay/
  scenarios/
```

说明：

- `unit/`：单模块逻辑测试
- `integration/`：链路集成测试
- `replay/`：事件回放测试
- `scenarios/`：面向体验场景的测试

---

## 7. 数据与运行目录建议

### data

用于存放：

- 视频样本
- 音频样本
- 录制事件流
- 标注数据
- 慢思考输入输出样本

### logs

用于存放：

- 运行日志
- trace 日志
- 性能统计

### runtime

用于存放：

- pid
- socket
- 临时缓存
- 中间产物

---

## 8. 命名规范建议

### 文件命名

- 文档：小写英文 + 下划线
- 配置：模块名 + 版本
- 测试：`test_<module>.py`
- 脚本：动词开头，如 `run_demo.py`、`replay_trace.py`

### 代码命名

- 事件统一使用名词短语：`familiar_face_detected`
- 场景统一使用名词短语：`greeting_scene`
- 行为统一使用动宾短语：`perform_light_greeting`
- trace 字段统一使用：`trace_id`

---

## 9. 开发约束建议

- 不允许直接在根目录堆测试脚本；
- 不允许让 detector 直接调用行为执行；
- 不允许业务代码直接依赖第三方模型接口；
- 所有第三方模型都必须包一层 adapter；
- 所有关键阈值必须进入配置文件；
- 所有核心链路都必须有 trace。

---

## 10. 结论

先把目录和命名规范固定住，可以显著降低后续多人协作和模块替换的成本。这一步虽然不显眼，但对主动交互引擎这种多模块系统非常关键。
