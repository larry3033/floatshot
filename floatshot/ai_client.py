"""Minimal OpenAI / Claude compatible vision client.

Standard library only (urllib, json, base64, os), so the app keeps its
single-*installed*-dependency promise. The request builders and response
parsers are pure functions -- the network call is the only side effect --
which lets them be unit tested without a server.

The two supported wire formats:

* openai -- POST {base_url}/chat/completions, image as an image_url data URI.
* claude -- POST {base_url}/v1/messages, image as a base64 source block.

Both are sent as a single user turn: one image plus the prompt.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request

DEFAULT_MAX_TOKENS = 1024
DEFAULT_TIMEOUT_S = 60.0


def resolve_key(ai: dict) -> str:
    """The API key: the configured value, else an environment variable.

    Keeping the env fallback means a key need not be written to disk.
    """
    key = str(ai.get("api_key") or "").strip()
    if key:
        return key
    env_name = str(ai.get("api_key_env") or "").strip()
    if env_name:
        return os.environ.get(env_name, "").strip()
    return ""


def build_request(
    ai: dict, prompt: str, image_png: bytes
) -> tuple[str, dict[str, str], dict]:
    """Return (url, headers, body) for one vision request."""
    fmt = str(ai.get("format", "openai")).strip().lower()
    base = str(ai.get("base_url", "")).strip().rstrip("/")
    model = str(ai.get("model", "")).strip()
    system = str(ai.get("system_prompt", "")).strip()
    max_tokens = int(ai.get("max_tokens", DEFAULT_MAX_TOKENS))
    key = resolve_key(ai)
    encoded = base64.b64encode(image_png).decode("ascii")

    if fmt == "claude":
        url = f"{base}/v1/messages"
        headers = {
            "content-type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        }
        body: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": encoded,
                    }},
                    {"type": "text", "text": prompt},
                ],
            }],
        }
        if system:
            body["system"] = system
        return url, headers, body

    url = f"{base}/chat/completions"
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {key}",
    }
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{encoded}"}},
            ]},
        ],
    }
    return url, headers, body


def _from_openai(payload: dict) -> str:
    choices = payload.get("choices") or []
    if not choices:
        return ""
    content = (choices[0].get("message") or {}).get("content")
    if isinstance(content, list):
        return "".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict)
        ).strip()
    return str(content or "").strip()


def _from_claude(payload: dict) -> str:
    content = payload.get("content")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    # Text blocks only: reasoning models also emit "thinking" blocks, which
    # are not the answer.
    return "".join(
        str(block.get("text", ""))
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ).strip()


def extract_text(fmt: str, payload: dict) -> str:
    """Pull the assistant's answer out of the response.

    A gateway does not always answer in the dialect its request format
    implies -- a relay can take an OpenAI body and reply with an Anthropic
    `content` list, for instance. So both shapes are tried; the configured
    one is simply tried first.
    """
    preferred, other = (_from_claude, _from_openai)
    if str(fmt).strip().lower() != "claude":
        preferred, other = (_from_openai, _from_claude)
    return preferred(payload) or other(payload)


def _error_message(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if not error:
        return None
    if isinstance(error, dict):
        return str(error.get("message") or error)
    return str(error)


def ask(ai: dict, prompt: str, image_png: bytes) -> str:
    """Send one image + prompt and return the answer text.

    Raises RuntimeError with a readable message on any failure.
    """
    url, headers, body = build_request(ai, prompt, image_png)
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    timeout = float(ai.get("timeout_s", DEFAULT_TIMEOUT_S))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"HTTP {exc.code}：{detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"网络错误：{exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"响应不是合法 JSON：{exc}") from exc

    message = _error_message(payload)
    if message:
        raise RuntimeError(f"接口返回错误：{message}")
    text = extract_text(str(ai.get("format", "openai")), payload)
    if not text:
        stop = payload.get("stop_reason") or payload.get("finish_reason")
        raise RuntimeError(f"接口没有返回文本内容（stop_reason={stop}）。")
    return text
