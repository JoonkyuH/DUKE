"""
llm_client.py
Thin stdlib-only wrapper for the Perplexity chat completions API.

The Perplexity API is OpenAI-compatible. The `sonar` model family has
real-time web access, making it suitable for daily news monitoring.

Entry point:
  call_perplexity(prompt, model, max_tokens, temperature) -> str

Requires:
  PERPLEXITY_API_KEY environment variable (export PERPLEXITY_API_KEY=pplx-...)
"""

import json
import os
import urllib.error
import urllib.request

_ENDPOINT     = "https://api.perplexity.ai/chat/completions"
DEFAULT_MODEL = "sonar"   # real-time web search; use "sonar-pro" for deeper reasoning


def call_perplexity(
    prompt:      str,
    model:       str   = DEFAULT_MODEL,
    max_tokens:  int   = 1024,
    temperature: float = 0.0,
) -> str:
    """
    Call the Perplexity chat completions API with a single user prompt.

    Args:
        prompt:      The user message to send.
        model:       Perplexity model name (default: sonar).
        max_tokens:  Maximum tokens in the response.
        temperature: Sampling temperature (0.0 = deterministic).

    Returns:
        The assistant message content string.

    Raises:
        RuntimeError:              PERPLEXITY_API_KEY not set.
        urllib.error.HTTPError:    Non-2xx response from the API.
        json.JSONDecodeError:      Response body is not valid JSON.
        KeyError:                  Unexpected API response structure.
    """
    api_key = os.environ.get("PERPLEXITY_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "PERPLEXITY_API_KEY environment variable is not set.\n"
            "Export it before running: export PERPLEXITY_API_KEY=pplx-..."
        )

    payload = json.dumps({
        "model":       model,
        "messages":    [{"role": "user", "content": prompt}],
        "max_tokens":  max_tokens,
        "temperature": temperature,
    }).encode("utf-8")

    req = urllib.request.Request(
        _ENDPOINT,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
            "Accept":        "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    return body["choices"][0]["message"]["content"]
