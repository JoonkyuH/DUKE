"""
claude_client.py
Claude API client implementing LLMClient.

Requires: ANTHROPIC_API_KEY environment variable.
"""

import json
import os
import re
import urllib.request

from .base import LLMClient

_ENDPOINT      = "https://api.anthropic.com/v1/messages"
_DEFAULT_MODEL = "claude-sonnet-4-6"
_API_VERSION   = "2023-06-01"


class ClaudeClient(LLMClient):
    def __init__(self, model: str = _DEFAULT_MODEL, max_tokens: int = 4096):
        self.model      = model
        self.max_tokens = max_tokens
        self._api_key   = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not self._api_key:
            raise RuntimeError("ANTHROPIC_API_KEY environment variable is not set.")

    def _call(self, messages: list, system: str = "") -> str:
        payload: dict = {
            "model":      self.model,
            "max_tokens": self.max_tokens,
            "messages":   messages,
        }
        if system:
            payload["system"] = system

        req = urllib.request.Request(
            _ENDPOINT,
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type":      "application/json",
                "x-api-key":         self._api_key,
                "anthropic-version": _API_VERSION,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            body = json.loads(r.read())
        return body["content"][0]["text"]

    def generate(self, prompt: str, system: str = "") -> str:
        return self._call([{"role": "user", "content": prompt}], system)

    def structured_generate(self, prompt: str, system: str = "", schema: dict = None) -> dict:
        sys_parts = [system] if system else []
        if schema:
            sys_parts.append(
                "Respond with valid JSON only — no markdown fences, no prose. "
                f"Schema: {json.dumps(schema)}"
            )
        else:
            sys_parts.append("Respond with valid JSON only — no markdown fences, no prose.")

        response = self._call(
            [{"role": "user", "content": prompt}],
            "\n\n".join(sys_parts),
        ).strip()

        # Strip optional markdown code fences
        response = re.sub(r"^```[^\n]*\n?", "", response)
        response = re.sub(r"\n?```$", "", response.rstrip())

        data = json.loads(response)

        if schema is not None:
            import jsonschema
            try:
                jsonschema.validate(data, schema)
            except jsonschema.ValidationError as exc:
                raise ValueError(f"LLM response failed schema validation: {exc.message}") from exc

        return data
