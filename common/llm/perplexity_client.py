"""
perplexity_client.py
Perplexity API client implementing LLMClient.

Requires: PERPLEXITY_API_KEY environment variable.
"""

import json
import os
import re
import urllib.request

from .base import LLMClient

_ENDPOINT      = "https://api.perplexity.ai/chat/completions"
_DEFAULT_MODEL = "sonar"


class PerplexityClient(LLMClient):
    def __init__(self, model: str = _DEFAULT_MODEL, max_tokens: int = 2048):
        self.model      = model
        self.max_tokens = max_tokens
        self._api_key   = os.environ.get("PERPLEXITY_API_KEY", "").strip()
        if not self._api_key:
            raise RuntimeError("PERPLEXITY_API_KEY environment variable is not set.")

    def _call(self, messages: list) -> str:
        payload = json.dumps({
            "model":      self.model,
            "messages":   messages,
            "max_tokens": self.max_tokens,
        }).encode()
        req = urllib.request.Request(
            _ENDPOINT,
            data=payload,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type":  "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            body = json.loads(r.read())
        return body["choices"][0]["message"]["content"]

    def generate(self, prompt: str, system: str = "") -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self._call(messages)

    def structured_generate(self, prompt: str, system: str = "", schema: dict = None) -> dict:
        sys_parts = [system] if system else []
        if schema:
            sys_parts.append(
                "Respond with valid JSON only — no markdown fences, no prose. "
                f"Schema: {json.dumps(schema)}"
            )
        else:
            sys_parts.append("Respond with valid JSON only — no markdown fences, no prose.")

        messages = [
            {"role": "system", "content": "\n\n".join(sys_parts)},
            {"role": "user",   "content": prompt},
        ]
        response = self._call(messages).strip()
        response = re.sub(r"^```[^\n]*\n?", "", response)
        response = re.sub(r"\n?```$", "", response.rstrip())
        return json.loads(response)
