"""Local Ollama client."""

from __future__ import annotations

import requests


class OllamaClient:
    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    def generate(self, prompt: str, timeout: int = 60) -> str:
        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={"model": self.model, "prompt": prompt, "stream": False},
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
            return str(payload.get("response", "")).strip()
        except Exception as exc:  # noqa: BLE001
            return f"Ollama unavailable: {exc}"
