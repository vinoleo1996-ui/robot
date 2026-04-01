from robot_life.perception.adapters.gguf_qwen_adapter import GGUFQwenVLAdapter


class _FakeLLM:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def create_chat_completion(self, **_kwargs):
        self.calls += 1
        if not self._responses:
            return {
                "choices": [
                    {
                        "message": {"content": ""},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            }
        return self._responses.pop(0)


def _resp(content: str, finish: str, prompt_tokens: int = 10, completion_tokens: int = 10):
    return {
        "choices": [
            {
                "message": {"content": content},
                "finish_reason": finish,
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def test_gguf_understand_scene_continues_after_length_truncation() -> None:
    adapter = GGUFQwenVLAdapter(
        model_path="unused.gguf",
        config={
            "max_new_tokens": 16,
            "enable_continuation": True,
            "max_continuations": 2,
            "continuation_max_new_tokens": 32,
        },
    )
    adapter._initialized = True  # noqa: SLF001 - unit test bypass
    adapter._supports_vision = False  # noqa: SLF001 - unit test bypass
    adapter._llm = _FakeLLM(
        [
            _resp(
                '{"scene_type":"attention_scene","confidence":0.73,',
                "length",
                prompt_tokens=100,
                completion_tokens=16,
            ),
            _resp(
                '"involved_targets":[],"emotion_hint":"curious","urgency_hint":"low","recommended_strategy":"nonverbal_first","escalate_to_cloud":false}',
                "stop",
                prompt_tokens=40,
                completion_tokens=22,
            ),
        ]
    )

    scene = adapter.understand_scene(image={"frame": 1}, context="unit-test", timeout_ms=2000)
    debug = adapter.debug_last_io()

    assert scene.scene_type == "attention_scene"
    assert abs(scene.confidence - 0.73) < 1e-6
    assert debug["last_finish_reason"] == "stop"
    assert debug["last_error"] is None
    assert debug["last_usage"]["segments"] == 2
    assert debug["last_usage"]["completion_tokens"] == 38


def test_extract_first_json_object_handles_nested_braces() -> None:
    text = 'prefix {"a":{"b":1},"c":"x"} trailing {"ignored":true}'
    payload = GGUFQwenVLAdapter._extract_first_json_object(text)  # noqa: SLF001 - helper test
    assert payload == '{"a":{"b":1},"c":"x"}'
