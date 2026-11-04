"""Format de trace : une suite d'événements sérialisée en JSON Lines."""
from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Types d'événements
SESSION_START = "session.start"   # état initial de tous les widgets nommés
INPUT_CLICK = "input.click"       # clic souris brut
INPUT_KEY = "input.key"           # frappe clavier brute
STATE_INPUT = "state.input"       # nouvelle valeur d'un widget de saisie
STATE_OBSERVED = "state.observed" # changement d'un widget observable (label, liste, bouton)
CHECKPOINT = "checkpoint"         # point de vérification demandé par le testeur


@dataclass
class RawEvent:
    seq: int
    t_ms: int
    type: str
    widget: str | None = None
    cls: str | None = None
    label: str | None = None
    value: Any = None
    key: str | None = None
    text: str | None = None
    prop: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        data = {k: v for k, v in asdict(self).items() if v is not None and v != {}}
        return json.dumps(data, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RawEvent:
        return cls(**data)


def save_trace(events: Iterable[RawEvent], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(e.to_json() for e in events) + "\n", encoding="utf-8")
    return path


def load_trace(path: str | Path) -> list[RawEvent]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [RawEvent.from_dict(json.loads(line)) for line in lines if line.strip()]
