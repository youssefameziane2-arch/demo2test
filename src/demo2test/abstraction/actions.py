"""Étape 1 de l'abstraction : des événements bruts aux actions d'interface.

Une frappe de 12 touches, deux corrections et un Tab deviennent *une* action
``set projectName = "soc_a"``. Les changements observés (labels, listes...) sont
rattachés comme *effets* à l'action qui les a provoqués : ils serviront à
proposer des vérifications.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..recorder.trace import (
    SESSION_START,
    RawEvent,
)

EDITABLE = {"QLineEdit": "set", "QSpinBox": "set", "QComboBox": "select"}
BUTTONS = {"QPushButton", "QToolButton"}

# Types d'action « inertes » : présents dans la trace mais sans effet sur le test.
INERT = {"focus", "inspect"}


@dataclass
class Effect:
    widget: str
    label: str
    prop: str
    value: Any
    t_ms: int


@dataclass
class Action:
    kind: str                       # set | select | toggle | click | submit | focus | inspect | checkpoint
    widget: str | None
    label: str | None
    cls: str | None
    value: Any = None
    seqs: list[int] = field(default_factory=list)
    t_start: int = 0
    t_end: int = 0
    effects: list[Effect] = field(default_factory=list)

    @property
    def inert(self) -> bool:
        return self.kind in INERT

    def short(self) -> str:
        v = "" if self.value is None else f" = {self.value!r}"
        return f"{self.kind} {self.widget}{v}"

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "widget": self.widget, "label": self.label,
                "value": self.value, "effects": [
                    {"widget": e.widget, "prop": e.prop, "value": e.value} for e in self.effects]}


@dataclass
class Recording:
    initial_state: dict[str, Any]
    actions: list[Action]
    n_raw_events: int


class _Grouper:
    def __init__(self, events: list[RawEvent]) -> None:
        self.events = events
        self.values: dict[str, Any] = {}
        self.actions: list[Action] = []
        self.pending: Action | None = None      # saisie en cours
        self.pending_before: Any = None
        self.toggle_wait: Action | None = None  # case à cocher cliquée, valeur à venir

    # -------------------------------------------------------------- helpers
    def _push(self, action: Action) -> Action:
        self.actions.append(action)
        return action

    def _flush(self) -> None:
        a = self.pending
        if a is None:
            return
        self.pending = None
        if a.value is None or a.value == self.pending_before:
            a.kind, a.value = "focus", None  # clic/frappe sans changement de valeur
        self._push(a)

    @staticmethod
    def _new(ev: RawEvent, kind: str, value: Any = None) -> Action:
        return Action(kind, ev.widget, ev.label, ev.cls, value, [ev.seq], ev.t_ms, ev.t_ms)

    # ----------------------------------------------------------------- main
    def run(self) -> Recording:
        initial: dict[str, Any] = {}
        for ev in self.events:
            handler = getattr(self, "_on_" + ev.type.replace(".", "_"), None)
            if ev.type == SESSION_START:
                initial = dict(ev.value or {})
                self.values = dict(initial)
            elif handler:
                handler(ev)
        self._flush()
        return Recording(initial, self.actions, len(self.events))

    def _on_input_click(self, ev: RawEvent) -> None:
        if self.pending and self.pending.widget == ev.widget:
            self.pending.seqs.append(ev.seq)
            return
        self._flush()
        if ev.cls in EDITABLE:
            self._start_edit(ev)
        elif ev.cls == "QCheckBox":
            self.toggle_wait = self._push(self._new(ev, "toggle"))
        elif ev.cls in BUTTONS:
            self._push(self._new(ev, "click"))
        else:
            self._push(self._new(ev, "inspect"))

    def _on_input_key(self, ev: RawEvent) -> None:
        if ev.key in ("Return", "Enter") and ev.cls == "QLineEdit":
            self._flush()
            self._push(self._new(ev, "submit"))
            return
        if ev.key == "Tab":
            self._flush()
            return
        if self.pending and self.pending.widget == ev.widget:
            self.pending.seqs.append(ev.seq)
            self.pending.t_end = ev.t_ms
            return
        self._flush()
        if ev.cls in EDITABLE:
            self._start_edit(ev)

    def _start_edit(self, ev: RawEvent) -> None:
        self.pending = self._new(ev, EDITABLE[ev.cls])
        self.pending_before = self.values.get(ev.widget)

    def _on_state_input(self, ev: RawEvent) -> None:
        self.values[ev.widget] = ev.value
        if self.pending and self.pending.widget == ev.widget:
            self.pending.value = ev.value
            self.pending.seqs.append(ev.seq)
            self.pending.t_end = ev.t_ms
        elif self.toggle_wait and self.toggle_wait.widget == ev.widget:
            self.toggle_wait.value = bool(ev.value)
            self.toggle_wait.seqs.append(ev.seq)
            self.toggle_wait = None
        else:
            # Changement programmatique (ex. champ vidé par l'application) : c'est un effet.
            self._effect(ev, prop="value")

    def _on_state_observed(self, ev: RawEvent) -> None:
        self._effect(ev, prop=ev.prop or "value")

    def _effect(self, ev: RawEvent, prop: str) -> None:
        target = self.pending or (self.actions[-1] if self.actions else None)
        if target is not None:
            target.effects.append(Effect(ev.widget, ev.label, prop, ev.value, ev.t_ms))

    def _on_checkpoint(self, ev: RawEvent) -> None:
        self._flush()
        cp = self._new(ev, "checkpoint", ev.value)
        cp.label = ev.text
        self._push(cp)


def group_events(events: list[RawEvent]) -> Recording:
    rec = _Grouper(events).run()
    # Une case cliquée dont l'état n'a pas changé est inerte.
    for a in rec.actions:
        if a.kind == "toggle" and a.value is None:
            a.kind = "focus"
    return rec
