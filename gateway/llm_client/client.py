"""Model Router / client (spec Section 7.8).

Defaults to the deterministic MockLLM. If a real OpenAI-compatible endpoint is configured via env
(OPENAI_API_KEY / OPENAI_BASE_URL / GATEWAY_MODEL), get_client() returns a real client that posts the
already-obfuscated packet. Uses only stdlib (urllib) so there is no dependency to install.
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, Dict

from .mock_llm import MockLLM
from .prompts import SYSTEM_PROMPT, build_user_prompt


class LLMClient:
    """Thin wrapper over an OpenAI-compatible chat-completions endpoint."""

    def __init__(self, api_key: str, base_url: str, model: str):
        self.provider = "openai_compatible"
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    def complete(self, system_prompt: str, user_prompt: str, packet: Dict[str, Any]) -> Dict[str, Any]:
        body = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        content = payload["choices"][0]["message"]["content"]
        return json.loads(content)


def get_client(prefer: str = "auto"):
    """Return a usable client. 'auto' uses a real endpoint only if fully configured, else MockLLM."""
    if prefer == "mock":
        return MockLLM()
    api_key = os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model = os.environ.get("GATEWAY_MODEL", "gpt-4o-mini")
    if prefer in ("auto", "openai") and api_key:
        return LLMClient(api_key=api_key, base_url=base_url, model=model)
    return MockLLM()
