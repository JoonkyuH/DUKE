"""
base.py
Abstract base class for LLM clients used in the DUKE pipeline.
"""

from abc import ABC, abstractmethod


class LLMClient(ABC):
    """Minimal interface for LLM backends."""

    @abstractmethod
    def generate(self, prompt: str, system: str = "") -> str:
        """Return a text response to prompt."""

    @abstractmethod
    def structured_generate(self, prompt: str, system: str = "", schema: dict = None) -> dict:
        """
        Return a parsed dict/list from a JSON-mode response.
        Raises ValueError if the response cannot be parsed as JSON.
        """
