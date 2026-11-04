"""Clients LLM interchangeables.

* ``ollama:<modèle>``  — LLM local via l'API HTTP d'Ollama (aucune donnée ne sort du poste) ;
* ``openai:<modèle>``  — toute API compatible OpenAI (``OPENAI_BASE_URL``, ``OPENAI_API_KEY``) ;
* ``replay:<fichier>`` — rejoue des réponses enregistrées : tests reproductibles et CI sans GPU.

Tout appel réel peut être journalisé (``record_to``) pour être rejoué ensuite :
c'est ce qui rend les évaluations comparables d'une exécution à l'autre.
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from pathlib import Path
from typing import Protocol


class LLMClient(Protocol):
    name: str

    def complete_json(self, system: str, user: str) -> dict: ...


def _key(system: str, user: str) -> str:
    return hashlib.sha256((system + "\x00" + user).encode()).hexdigest()[:16]


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError(f"no JSON object in LLM answer: {text[:120]!r}")
    return json.loads(text[start:end + 1])


class _HTTPClient:
    timeout = 120

    def __init__(self, model: str, record_to: str | Path | None = None) -> None:
        self.model = model
        self.record_to = Path(record_to) if record_to else None
        self.calls = 0

    def _post(self, url: str, payload: dict, headers: dict | None = None) -> dict:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", **(headers or {})})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
            return json.loads(resp.read())

    def _record(self, system: str, user: str, answer: dict) -> None:
        if not self.record_to:
            return
        cache = json.loads(self.record_to.read_text()) if self.record_to.exists() else {}
        cache[_key(system, user)] = answer
        self.record_to.parent.mkdir(parents=True, exist_ok=True)
        self.record_to.write_text(json.dumps(cache, indent=1, ensure_ascii=False))


class OllamaClient(_HTTPClient):
    def __init__(self, model: str, host: str | None = None, **kw) -> None:
        super().__init__(model, **kw)
        self.host = host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        self.name = f"ollama:{model}"

    def complete_json(self, system: str, user: str) -> dict:
        self.calls += 1
        data = self._post(f"{self.host}/api/chat", {
            "model": self.model, "stream": False, "format": "json",
            "options": {"temperature": 0},
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}]})
        answer = _extract_json(data["message"]["content"])
        self._record(system, user, answer)
        return answer


class OpenAICompatClient(_HTTPClient):
    def __init__(self, model: str, **kw) -> None:
        super().__init__(model, **kw)
        self.base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.name = f"openai:{model}"

    def complete_json(self, system: str, user: str) -> dict:
        self.calls += 1
        data = self._post(f"{self.base}/chat/completions", {
            "model": self.model, "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}]},
            headers={"Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY', '')}"})
        answer = _extract_json(data["choices"][0]["message"]["content"])
        self._record(system, user, answer)
        return answer


class ReplayClient:
    """Rejoue des réponses enregistrées ; lève KeyError si la question est inconnue."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.cache = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.name = f"replay:{self.path.name}"
        self.calls = 0

    def complete_json(self, system: str, user: str) -> dict:
        self.calls += 1
        return self.cache[_key(system, user)]


class ScriptedClient:
    """Client de test : renvoie une réponse fixe ou calculée (tests unitaires)."""

    def __init__(self, responder) -> None:
        self.responder = responder
        self.name = "scripted"
        self.calls = 0
        self.prompts: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str) -> dict:
        self.calls += 1
        self.prompts.append((system, user))
        return self.responder(system, user)


def make_client(spec: str | None, record_to: str | Path | None = None) -> LLMClient | None:
    if not spec:
        return None
    backend, _, arg = spec.partition(":")
    if backend == "ollama":
        return OllamaClient(arg or "qwen2.5:3b", record_to=record_to)
    if backend == "openai":
        return OpenAICompatClient(arg or "gpt-4o-mini", record_to=record_to)
    if backend == "replay":
        return ReplayClient(arg)
    raise ValueError(f"unknown LLM backend: {spec}")
