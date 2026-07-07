"""Model Router / client (spec Section 7.8).

Defaults to the deterministic MockLLM. If a real OpenAI-compatible endpoint is configured via env
(OPENAI_API_KEY / OPENAI_BASE_URL / GATEWAY_MODEL), get_client() returns a real client that posts the
already-obfuscated packet. Uses only stdlib (urllib) so there is no dependency to install.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from .mock_llm import MockLLM
from .prompts import SYSTEM_PROMPT, build_user_prompt

# Decoder-enforced response contract (OpenAI structured-outputs format). Mirrors
# gateway/llm_client/schemas.py and prompts.RESPONSE_TEMPLATE — keep the three in sync.
_FAR_SCHEMA = {
    "type": "object",
    "properties": {
        "recommended": {"type": "boolean"},
        "direction": {"type": "string", "enum": ["decrease", "increase", "unchanged"]},
        "reason": {"type": "string"},
    },
    "required": ["recommended", "direction", "reason"],
    "additionalProperties": False,
}
RESPONSE_JSON_SCHEMA = {
    "name": "fpa_analysis",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "executive_summary": {"type": "string"},
            "material_variance_commentary": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "issue_id": {"type": "string"},
                        "summary": {"type": "string"},
                        "likely_drivers": {"type": "array", "items": {"type": "string"}},
                        "management_questions": {"type": "array", "items": {"type": "string"}},
                        "recommended_action": {"type": "string"},
                        "forecast_adjustment_recommendation": _FAR_SCHEMA,
                    },
                    "required": ["issue_id", "summary", "likely_drivers", "management_questions",
                                 "recommended_action", "forecast_adjustment_recommendation"],
                    "additionalProperties": False,
                },
            },
            "board_narrative": {
                "type": "object",
                "properties": {"draft": {"type": "string"}},
                "required": ["draft"],
                "additionalProperties": False,
            },
            "risks_to_monitor": {"type": "array", "items": {"type": "string"}},
            "open_questions": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["executive_summary", "material_variance_commentary", "board_narrative",
                     "risks_to_monitor", "open_questions"],
        "additionalProperties": False,
    },
}


class LLMClient:
    """Thin wrapper over an OpenAI-compatible chat-completions endpoint."""

    def __init__(self, api_key: str, base_url: str, model: str, timeout: Optional[float] = None):
        self.provider = "openai_compatible"
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        # Local OpenAI-compatible servers (e.g. Ollama) can take well over a minute on large
        # prompts; 60s stays the default for hosted APIs but must be overridable.
        self.timeout = timeout if timeout is not None else float(os.environ.get("GATEWAY_LLM_TIMEOUT", "60"))

    def complete(self, system_prompt: str, user_prompt: str, packet: Dict[str, Any]) -> Dict[str, Any]:
        # Prefer decoder-enforced structured outputs (OpenAI "json_schema"; recent Ollama supports
        # it too) — it makes schema compliance near-guaranteed. Servers that reject it get one
        # fallback attempt in plain JSON mode, where the validator + retry loop carry the load.
        try:
            return self._post(system_prompt, user_prompt,
                              {"type": "json_schema", "json_schema": RESPONSE_JSON_SCHEMA})
        except urllib.error.HTTPError as e:
            if e.code in (400, 404, 422):
                return self._post(system_prompt, user_prompt, {"type": "json_object"})
            raise
        except (json.JSONDecodeError, KeyError):
            # Some servers return empty/malformed content when generation fights the strict
            # grammar; one plain-JSON-mode attempt before the caller's mock fallback kicks in.
            return self._post(system_prompt, user_prompt, {"type": "json_object"})

    def _post(self, system_prompt: str, user_prompt: str, response_format: Dict[str, Any]) -> Dict[str, Any]:
        body = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "response_format": response_format,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
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
