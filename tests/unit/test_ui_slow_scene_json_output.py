import json

from robot_life.perception.adapters.gguf_qwen_adapter import GGUFQwenVLAdapter
from robot_life.runtime.ui_slow_scene import _extract_json_text


def test_extract_json_text_preserves_model_partial_json_without_local_fill() -> None:
    raw = """
    {
      "元信息": {"事件ID": "old", "时间戳": "", "画面来源": "", "运行模式": ""}
    """
    text = _extract_json_text(raw)
    assert "元信息" in text
    assert "old" in text
    assert "运行模式" in text


def test_extract_json_text_pretty_prints_valid_model_json() -> None:
    raw = '{"a":1,"b":{"c":"x"}}'
    text = _extract_json_text(raw)
    payload = json.loads(text)
    assert payload["a"] == 1
    assert payload["b"]["c"] == "x"


def test_gguf_prompt_is_minimal_template_fill_instruction() -> None:
    prompt = GGUFQwenVLAdapter._build_prompt("当前帧来自客厅")
    assert "请填写以下空JSON模板" in prompt
    assert "字段与模板完全一致" in prompt
    assert "话术模板" in prompt
    assert "核心门控" in prompt
    assert "若无人或无人脸" in prompt
    assert "补充上下文：当前帧来自客厅" in prompt
