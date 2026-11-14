"""
Pluggable LLM provider.

Pick the backend at runtime so you can demo offline, swap providers, or run local
on your Mac via Ollama. Every backend implements `complete(prompt, temperature)`.

The OFFLINE stub returns "" so planner/comms both fall back to their deterministic
paths — the whole system runs with zero API keys. Flip to a real provider for the
"LLM reasoning" part of the demo.
"""
from __future__ import annotations

import os


class LLMProvider:
    def complete(self, prompt: str, temperature: float = 0.5) -> str:
        raise NotImplementedError


class OfflineStub(LLMProvider):
    """No network. Forces heuristic planner + template comms."""
    def complete(self, prompt: str, temperature: float = 0.5) -> str:
        return ""


class OpenAIProvider(LLMProvider):
    def __init__(self, model: str = "gpt-4o-mini"):
        from openai import OpenAI  # lazy import so offline needs no deps
        self.client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        self.model = model

    def complete(self, prompt: str, temperature: float = 0.5) -> str:
        r = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=40,
        )
        return r.choices[0].message.content or ""


class OllamaProvider(LLMProvider):
    """Local model on your Mac (e.g. `ollama run llama3.1`). No API key, no cost."""
    def __init__(self, model: str = "llama3.1", host: str = "http://localhost:11434"):
        self.model = model
        self.host = host

    def complete(self, prompt: str, temperature: float = 0.5) -> str:
        import requests
        r = requests.post(
            f"{self.host}/api/generate",
            json={"model": self.model, "prompt": prompt, "stream": False,
                  "options": {"temperature": temperature, "num_predict": 40}},
            timeout=20,
        )
        return r.json().get("response", "")


def make_provider(name: str) -> LLMProvider:
    name = (name or "offline").lower()
    if name == "offline":
        return OfflineStub()
    if name == "openai":
        return OpenAIProvider()
    if name == "ollama":
        return OllamaProvider()
    # add "gemini" / "claude" the same way when you pick one
    raise ValueError(f"unknown provider: {name}")
