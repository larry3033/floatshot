import base64
import json

import pytest

from floatshot.ai_client import build_request, extract_text, resolve_key

IMAGE = b"\x89PNG\r\n\x1a\nfake"
AI = {
    "format": "openai",
    "base_url": "https://example.test/v1/",
    "model": "deepseek-v4-flash",
    "api_key": "sk-test",
    "max_tokens": 512,
    "system_prompt": "be terse",
}


# ---------- key resolution ----------

def test_key_uses_configured_value():
    assert resolve_key({"api_key": "abc"}) == "abc"


def test_key_falls_back_to_environment(monkeypatch):
    monkeypatch.setenv("FLOATSHOT_TEST_KEY", "from-env")
    assert resolve_key({"api_key": "", "api_key_env": "FLOATSHOT_TEST_KEY"}) == "from-env"


def test_key_is_empty_when_nothing_set(monkeypatch):
    monkeypatch.delenv("FLOATSHOT_TEST_KEY", raising=False)
    assert resolve_key({"api_key": "", "api_key_env": "FLOATSHOT_TEST_KEY"}) == ""


# ---------- OpenAI format ----------

def test_openai_request_shape():
    ai = dict(AI)
    url, headers, body = build_request(ai, "what is this?", IMAGE)

    assert url == "https://example.test/v1/chat/completions"   # no double slash
    assert headers["authorization"] == "Bearer sk-test"
    assert body["model"] == "deepseek-v4-flash"
    assert body["max_tokens"] == 512
    assert body["messages"][0] == {"role": "system", "content": "be terse"}

    parts = body["messages"][1]["content"]
    assert parts[0] == {"type": "text", "text": "what is this?"}
    data_uri = parts[1]["image_url"]["url"]
    assert data_uri.startswith("data:image/png;base64,")
    assert base64.b64decode(data_uri.split(",", 1)[1]) == IMAGE


def test_build_request_is_json_serialisable():
    _, _, body = build_request(AI, "hi", IMAGE)
    assert json.loads(json.dumps(body)) == body


# ---------- Claude format ----------

def test_claude_request_shape():
    ai = dict(AI, format="claude", base_url="https://example.test")
    url, headers, body = build_request(ai, "what is this?", IMAGE)

    assert url == "https://example.test/v1/messages"
    assert headers["x-api-key"] == "sk-test"
    assert headers["anthropic-version"] == "2023-06-01"
    assert body["system"] == "be terse"

    parts = body["messages"][0]["content"]
    assert parts[0]["type"] == "image"
    assert parts[0]["source"]["media_type"] == "image/png"
    assert base64.b64decode(parts[0]["source"]["data"]) == IMAGE
    assert parts[1] == {"type": "text", "text": "what is this?"}


def test_claude_omits_empty_system():
    ai = dict(AI, format="claude", system_prompt="")
    _, _, body = build_request(ai, "hi", IMAGE)
    assert "system" not in body


# ---------- response parsing ----------

def test_extract_openai_string_content():
    payload = {"choices": [{"message": {"content": "hello"}}]}
    assert extract_text("openai", payload) == "hello"


def test_extract_openai_part_list_content():
    payload = {"choices": [{"message": {"content": [
        {"type": "text", "text": "a"},
        {"type": "text", "text": "b"},
    ]}}]}
    assert extract_text("openai", payload) == "ab"


def test_extract_openai_empty():
    assert extract_text("openai", {}) == ""
    assert extract_text("openai", {"choices": []}) == ""


def test_extract_claude_concatenates_text_blocks():
    payload = {"content": [
        {"type": "text", "text": "line1 "},
        {"type": "text", "text": "line2"},
    ]}
    assert extract_text("claude", payload) == "line1 line2"


def test_extract_claude_ignores_non_text_blocks():
    payload = {"content": [
        {"type": "tool_use", "id": "x"},
        {"type": "text", "text": "ok"},
    ]}
    assert extract_text("claude", payload) == "ok"


@pytest.mark.parametrize("fmt", ["openai", "claude"])
def test_extract_is_empty_for_unexpected_payload(fmt):
    assert extract_text(fmt, {}) == ""


# ---------- cross-dialect tolerance ----------

ANTHROPIC_PAYLOAD = {
    "type": "message",
    "role": "assistant",
    "stop_reason": "end_turn",
    "content": [
        {"type": "thinking", "thinking": "let me look", "signature": "x"},
        {"type": "text", "text": "红色"},
    ],
}


def test_openai_format_still_reads_an_anthropic_response():
    # A relay can answer an OpenAI-shaped request with an Anthropic body.
    assert extract_text("openai", ANTHROPIC_PAYLOAD) == "红色"


def test_claude_format_still_reads_an_openai_response():
    payload = {"choices": [{"message": {"content": "hi"}}]}
    assert extract_text("claude", payload) == "hi"


def test_thinking_blocks_are_never_the_answer():
    payload = {"content": [{"type": "thinking", "thinking": "me"}]}
    assert extract_text("claude", payload) == ""
