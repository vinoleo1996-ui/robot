import json

from robot_life.perception.adapters.gguf_qwen_adapter import GGUFQwenVLAdapter


def test_gguf_prompt_uses_structured_json_template() -> None:
    prompt = GGUFQwenVLAdapter._build_prompt("单元测试上下文")  # noqa: SLF001 - static helper verification
    assert "元信息" in prompt
    assert "决策信息" in prompt
    assert "执行动作" in prompt
    assert "先判断画面里有没有可交互人" in prompt
    assert "核心门控" in prompt
    assert "单元测试上下文" in prompt


def test_gguf_parser_accepts_structured_scene_json() -> None:
    output = """
    {
      "元信息": {"事件ID": "e1", "时间戳": "t1", "画面来源": "camera", "运行模式": "live"},
      "场景信息": {"房间类型": "客厅", "子区域": "沙发区", "光照情况": "正常", "环境噪声等级": "低", "电视状态": "关", "音乐状态": "关", "门状态": "关", "人员活动密度": "低", "场景稳定性": "稳定"},
      "人员信息": [{"人员ID": "user_001", "身份类型": "访客", "是否在场": "是", "距离等级": "近", "相对位置": "前方", "姿态": "站立", "运动状态": "静止", "对机器人的注意力": "高", "人脸是否可见": "是", "交互参与度": "高"}],
      "物体信息": [{"物体名称": "杯子", "物体状态": "静止", "重要性等级": "低"}],
      "事件信息": {"触发类型": "语音", "触发来源": "人声", "事件持续时长毫秒": "1200", "新颖性": "中", "风险等级": "高", "是否需要关注": "是"},
      "交互上下文": {"用户可能意图": "求助", "可打扰程度": "高", "是否安静时段": "否", "是否隐私敏感": "否", "近期相同交互次数": "1", "冷却期是否生效": "否"},
      "决策信息": {"是否说话": "是", "说话优先级": "高", "交互行为类型": "安全提醒", "交互目标": "user_001", "原因缩略": ["高风险"], "置信度": "85"},
      "执行动作": {"话术模板": "请注意安全", "非语言动作": "灯光提醒", "机器人运动动作": "轻微转头", "后续跟进策略": "立即提醒"}
    }
    """

    scene = GGUFQwenVLAdapter._parse_scene_json(output)  # noqa: SLF001 - static helper verification
    assert scene.scene_type == "safety_alert_scene"
    assert scene.confidence == 0.85
    assert scene.urgency_hint == "high"
    assert scene.involved_targets == ["user_001"]
    assert scene.escalate_to_cloud is True


def test_gguf_parser_keeps_model_decision_when_no_person_present() -> None:
    output = """
    {
      "元信息": {"事件ID": "e2", "时间戳": "t2", "画面来源": "camera", "运行模式": "live"},
      "场景信息": {"房间类型": "客厅", "子区域": "走廊", "光照情况": "正常", "环境噪声等级": "低", "电视状态": "关", "音乐状态": "关", "门状态": "关", "人员活动密度": "低", "场景稳定性": "稳定"},
      "人员信息": [{"人员ID": "", "身份类型": "未知", "是否在场": "否", "是否检测到人体": "否", "距离等级": "未知", "相对位置": "未知", "姿态": "未知", "运动状态": "未知", "对机器人的注意力": "低", "人脸是否可见": "否", "交互参与度": "低"}],
      "物体信息": [{"物体名称": "沙发", "物体状态": "静止", "重要性等级": "低"}],
      "事件信息": {"触发类型": "画面更新", "触发来源": "视觉", "事件持续时长毫秒": "1200", "新颖性": "低", "风险等级": "中", "是否需要关注": "否"},
      "交互上下文": {"用户可能意图": "未知", "可打扰程度": "低", "是否安静时段": "否", "是否隐私敏感": "否", "近期相同交互次数": "1", "冷却期是否生效": "否"},
      "决策信息": {"是否说话": "是", "说话优先级": "高", "交互行为类型": "问候", "交互目标": "user_001", "原因缩略": ["测试"], "置信度": "92"},
      "执行动作": {"话术模板": "你好", "非语言动作": "挥手", "机器人运动动作": "前进", "后续跟进策略": "主动互动"}
    }
    """
    scene = GGUFQwenVLAdapter._parse_scene_json(output)  # noqa: SLF001 - static helper verification
    assert scene.scene_type == "greeting_scene"
    assert scene.urgency_hint == "medium"
    assert scene.recommended_strategy == "主动互动"
    assert scene.confidence == 0.92


def test_gguf_validate_structured_json_detects_missing_or_empty_fields() -> None:
    raw = """
    {
      "元信息": {"事件ID": "", "时间戳": "t", "画面来源": "camera", "运行模式": "live"},
      "场景信息": {}
    }
    """
    issues = GGUFQwenVLAdapter._validate_structured_json_text(raw)  # noqa: SLF001
    assert any("元信息.事件ID 为空字符串" in item for item in issues)
    assert any("场景信息.房间类型 缺失" in item for item in issues)


def test_gguf_validate_structured_json_accepts_complete_payload() -> None:
    template = GGUFQwenVLAdapter._structured_scene_template()  # noqa: SLF001
    payload = {
        "元信息": {
            "事件ID": "EVT-1",
            "时间戳": "2026-03-28 01:00:00",
            "画面来源": "camera",
            "运行模式": "live",
        },
        "场景信息": {
            "房间类型": "客厅",
            "子区域": "沙发区",
            "光照情况": "正常",
            "环境噪声等级": "低",
            "电视状态": "关闭",
            "音乐状态": "无",
            "门状态": "关闭",
            "人员活动密度": "低",
            "场景稳定性": "稳定",
        },
        "人员信息": [
            {
                "人员ID": "unknown_1",
                "身份类型": "未知",
                "是否在场": "否",
                "距离等级": "未知",
                "相对位置": "未知",
                "姿态": "未知",
                "运动状态": "静止",
                "对机器人的注意力": "低",
                "人脸是否可见": "否",
                "交互参与度": "低",
            }
        ],
        "物体信息": [
            {
                "物体名称": "沙发",
                "物体状态": "静止",
                "重要性等级": "低",
            }
        ],
        "事件信息": {
            "触发类型": "画面更新",
            "触发来源": "视觉",
            "事件持续时长毫秒": "5000",
            "新颖性": "低",
            "风险等级": "低",
            "是否需要关注": "否",
        },
        "交互上下文": {
            "用户可能意图": "未知",
            "可打扰程度": "低",
            "是否安静时段": "未知",
            "是否隐私敏感": "否",
            "近期相同交互次数": "0",
            "冷却期是否生效": "是",
        },
        "决策信息": {
            "是否说话": "否",
            "说话优先级": "P3",
            "交互行为类型": "环境观察",
            "交互目标": "无",
            "原因缩略": ["无人出现"],
            "置信度": "0.90",
        },
        "执行动作": {
            "话术模板": "保持静默观察",
            "非语言动作": "无",
            "机器人运动动作": "无",
            "后续跟进策略": "继续观察",
        },
    }
    # Ensure test payload covers all template keys.
    assert set(payload.keys()) == set(template.keys())
    issues = GGUFQwenVLAdapter._validate_structured_json_text(json.dumps(payload, ensure_ascii=False))  # noqa: SLF001
    assert issues == []
