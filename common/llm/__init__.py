"""
common/llm/__init__.py
LLM client factory for the DUKE pipeline.

Usage:
    from common.llm import get_client
    client = get_client("extraction")
    text   = client.generate(prompt, system)
    data   = client.structured_generate(prompt, system)

Task → backend mapping (config-driven; all tasks currently use Claude):
    extraction  → claude
    debate      → claude
    synthesis   → claude
"""

from .base import LLMClient
from .claude_client import ClaudeClient

_TASK_MAP: dict = {
    "extraction": "claude",
    "debate":     "claude",
    "synthesis":  "claude",
}


def get_client(task: str) -> LLMClient:
    """Return the LLMClient configured for the given pipeline task."""
    backend = _TASK_MAP.get(task, "claude")
    if backend == "claude":
        return ClaudeClient()
    if backend == "perplexity":
        from .perplexity_client import PerplexityClient
        return PerplexityClient()
    raise ValueError(f"Unknown LLM backend: {backend!r}")


__all__ = ["get_client", "LLMClient"]
