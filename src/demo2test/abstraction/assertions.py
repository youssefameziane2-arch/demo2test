"""Étape 3 : proposer les vérifications (steps ``Then``).

Deux sources :
* les **checkpoints** posés par le testeur (Ctrl+Maj+K) : l'état observable figé
  à cet instant devient une suite d'assertions ;
* les **effets observés** pendant la démonstration : après une action « clé »
  (valider, générer, ajouter un port), on propose de vérifier l'effet visible.
  Ces propositions sont marquées ``suggested`` pour la relecture.

Pour les effets asynchrones, le délai observé est conservé : la bibliothèque de
steps attend la condition (pas de ``sleep`` fixe) avec une marge sur ce délai.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .actions import Action, Recording
from .matching import MatchResult, StepCall

KEY_STEPS = {"validate_design", "generate_netlist", "add_initiator", "add_target"}


@dataclass
class Assertion:
    step_id: str
    params: dict[str, Any]
    after_call: int            # index de l'appel (StepCall) après lequel vérifier ; -1 = début
    origin: str                # checkpoint | suggested
    observed_delay_ms: int | None = None


def _status_effects(action: Action) -> list:
    return [e for e in action.effects if e.widget == "statusLabel"]


def _label_of(rec: Recording, widget: str, fallback: str) -> str:
    for a in rec.actions:
        for e in a.effects:
            if e.widget == widget:
                return e.label
    return fallback


def from_checkpoint(cp: Action, rec: Recording, after_call: int) -> list[Assertion]:
    out = []
    for widget, value in (cp.value or {}).items():
        initial = rec.initial_state.get(widget)
        if widget == "statusLabel":
            out.append(Assertion("status_is", {"text": value}, after_call, "checkpoint"))
        elif isinstance(value, list) and value:
            label = _label_of(rec, widget, widget)
            out.append(Assertion("list_count", {"list": label, "count": len(value)},
                                 after_call, "checkpoint"))
        elif isinstance(value, bool) and value != initial:
            label = {"generateBtn": "Generate netlist"}.get(widget, widget)
            out.append(Assertion("button_enabled" if value else "button_disabled",
                                 {"button": label}, after_call, "checkpoint"))
    return out


def suggest(rec: Recording, result: MatchResult, mode: str = "key") -> list[Assertion]:
    if mode == "none":
        return []
    calls: list[StepCall] = result.calls
    assertions: list[Assertion] = []
    for idx, call in enumerate(calls):
        acts = [rec.actions[i] for i in call.covered]
        last = max(call.covered)
        # Checkpoints situés après cet appel et avant le suivant.
        nxt = calls[idx + 1].anchor if idx + 1 < len(calls) else len(rec.actions)
        for j in range(last + 1, nxt):
            if rec.actions[j].kind == "checkpoint":
                assertions += from_checkpoint(rec.actions[j], rec, idx)
        is_key = call.step_id in KEY_STEPS or (mode == "all" and call.source == "generic")
        if not is_key:
            continue
        effects = [e for a in acts for e in a.effects]
        if call.step_id in ("add_initiator", "add_target"):
            lists = [e for e in effects if e.prop == "items" and e.value]
            if lists:
                e = lists[-1]
                assertions.append(Assertion("list_contains", {"list": e.label, "item": e.value[-1]},
                                            idx, "suggested"))
        status = [e for a in acts for e in _status_effects(a)]
        if status and call.step_id in ("validate_design", "generate_netlist"):
            final = status[-1]
            delay = final.t_ms - acts[-1].t_start
            assertions.append(Assertion("status_is", {"text": final.value}, idx, "suggested",
                                        observed_delay_ms=delay if delay > 100 else None))
    # Checkpoints placés avant la première action.
    first = calls[0].anchor if calls else len(rec.actions)
    for j in range(first):
        if rec.actions[j].kind == "checkpoint":
            assertions += from_checkpoint(rec.actions[j], rec, -1)
    # Dédoublonnage : un checkpoint prime sur une suggestion identique.
    seen, unique = set(), []
    for a in sorted(assertions, key=lambda a: (a.after_call, a.origin != "checkpoint")):
        key = (a.after_call, a.step_id, tuple(sorted(map(str, a.params.items()))))
        if key not in seen:
            seen.add(key)
            unique.append(a)
    return unique
