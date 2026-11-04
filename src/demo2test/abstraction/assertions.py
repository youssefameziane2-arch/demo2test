"""Étape 3 : proposer les vérifications (steps ``Then``).

Trois sources :
* les **checkpoints** posés par le testeur (Ctrl+Maj+K) : l'état observable figé
  à cet instant devient une suite d'assertions ;
* les **effets observés** pendant la démonstration : après une action « clé »
  (valider, générer, ajouter un port), on propose de vérifier l'effet visible.
  Ces propositions sont marquées ``suggested`` pour la relecture ;
* le **LLM** (modes ``llm`` et ``key+llm``) : il reçoit les steps du test et les
  effets observés après chacun, et choisit les vérifications utiles parmi les steps
  d'assertion du catalogue. Chaque proposition est **vérifiée** : step d'assertion
  existant, paramètres complets, valeur attendue identique à l'état réellement
  observé à cet endroit de la démonstration. Une vérification non conforme à ce
  qui a été observé est rejetée (elle ferait échouer le test sans raison).

Pour les effets asynchrones, le délai observé est conservé : la bibliothèque de
steps attend la condition (pas de ``sleep`` fixe) avec une marge sur ce délai.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..catalog import BY_ID, STEPS
from ..llm import LLMClient
from .actions import Action, Recording
from .matching import MatchResult, StepCall

KEY_STEPS = {"validate_design", "generate_netlist", "add_initiator", "add_target"}


@dataclass
class Assertion:
    step_id: str
    params: dict[str, Any]
    after_call: int            # index de l'appel (StepCall) après lequel vérifier ; -1 = début
    origin: str                # checkpoint | suggested | llm
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


def _rule_checks(rec: Recording, calls: list[StepCall], mode: str) -> list[Assertion]:
    out: list[Assertion] = []
    for idx, call in enumerate(calls):
        acts = [rec.actions[i] for i in call.covered]
        is_key = call.step_id in KEY_STEPS or (mode == "all" and call.source == "generic")
        if not is_key:
            continue
        effects = [e for a in acts for e in a.effects]
        if call.step_id in ("add_initiator", "add_target"):
            lists = [e for e in effects if e.prop == "items" and e.value]
            if lists:
                e = lists[-1]
                out.append(Assertion("list_contains", {"list": e.label, "item": e.value[-1]},
                                     idx, "suggested"))
        status = [e for a in acts for e in _status_effects(a)]
        if status and call.step_id in ("validate_design", "generate_netlist"):
            final = status[-1]
            delay = final.t_ms - acts[-1].t_start
            out.append(Assertion("status_is", {"text": final.value}, idx, "suggested",
                                 observed_delay_ms=delay if delay > 100 else None))
    return out


def _checkpoint_checks(rec: Recording, calls: list[StepCall]) -> list[Assertion]:
    out: list[Assertion] = []
    for idx, call in enumerate(calls):
        last = max(call.covered)
        nxt = calls[idx + 1].anchor if idx + 1 < len(calls) else len(rec.actions)
        for j in range(last + 1, nxt):
            if rec.actions[j].kind == "checkpoint":
                out += from_checkpoint(rec.actions[j], rec, idx)
    first = calls[0].anchor if calls else len(rec.actions)
    for j in range(first):
        if rec.actions[j].kind == "checkpoint":
            out += from_checkpoint(rec.actions[j], rec, -1)
    return out


# ----------------------------------------------------------------------- LLM
def observed_states(rec: Recording, calls: list[StepCall]) -> tuple[list[dict], dict[str, str]]:
    """État observable (labels, listes, boutons) juste avant le step suivant, pour chaque step."""
    state = {k: v for k, v in rec.initial_state.items()}
    labels: dict[str, str] = {}
    for a in rec.actions:
        for e in a.effects:
            labels.setdefault(e.label, e.widget)
    after_action = []
    for a in rec.actions:
        for e in a.effects:
            if e.prop in ("text", "items", "enabled"):
                state[e.widget] = e.value
        after_action.append(dict(state))
    per_call = []
    for idx in range(len(calls)):
        nxt = calls[idx + 1].anchor if idx + 1 < len(calls) else len(rec.actions)
        per_call.append(after_action[nxt - 1])
    return per_call, labels


ASSERT_SYSTEM = (
    "You are a senior QA engineer reviewing an automatically generated GUI test. "
    "For each step you get what was observed on screen right after it. Choose the checks "
    "(Then steps) that best verify the important behaviour: business results, error "
    "messages, results of asynchronous operations, state changes a regression could break. "
    "Skip trivial or redundant checks. Use only assertion step ids from the catalog, and copy "
    "expected values exactly as observed. Answer with JSON only: "
    '{"checks": [{"after": step index, "id": str, "params": {name: value}}]}'
)


def _llm_payload(rec: Recording, calls: list[StepCall]) -> str:
    per_call, labels = observed_states(rec, calls)
    widget_label = {w: label for label, w in labels.items()}
    steps = []
    prev = {k: rec.initial_state.get(k) for k in widget_label}
    for idx, call in enumerate(calls):
        now = per_call[idx]
        changed = {widget_label[w]: now.get(w) for w in widget_label if now.get(w) != prev.get(w)}
        steps.append({"index": idx, "step": call.text, "observed_changes": changed})
        prev = {w: now.get(w) for w in widget_label}
    catalog = [{"id": s.id, "pattern": s.pattern, "description": s.description}
               for s in STEPS if s.level == "assertion"]
    return json.dumps({"assertion_steps": catalog, "test": steps}, ensure_ascii=False)


def verify_check(prop: dict, rec: Recording, calls: list[StepCall],
                 check_observed: bool = True) -> tuple[Assertion | None, str]:
    per_call, labels = observed_states(rec, calls)
    sid, after, params = prop.get("id"), prop.get("after"), prop.get("params") or {}
    step = BY_ID.get(sid)
    if step is None or step.level != "assertion":
        return None, f"'{sid}' is not an assertion step of the catalog"
    if not isinstance(after, int) or not 0 <= after < len(calls):
        return None, f"invalid step index {after!r}"
    missing = [p for p in step.params if p not in params]
    if missing:
        return None, f"missing parameters: {', '.join(missing)}"
    state = per_call[after]
    target = params.get("list") or params.get("button")
    widget = labels.get(target) if target else "statusLabel"
    observed = state.get(widget) if widget else None
    ok = {
        "status_is": lambda: observed == params["text"],
        "list_contains": lambda: isinstance(observed, list) and params["item"] in observed,
        "list_count": lambda: isinstance(observed, list) and len(observed) == int(params["count"]),
        "button_enabled": lambda: observed is True,
        "button_disabled": lambda: observed is False,
    }.get(sid, lambda: False)
    try:
        good = widget is not None and ok()
    except (TypeError, ValueError):
        good = False
    if not good and check_observed:
        return None, f"expected value does not match what was observed ({sid} {params} vs {observed!r})"
    try:
        clean = {p: (int(params[p]) if "{" + p + ":d}" in step.pattern else params[p])
                 for p in step.params}
    except (TypeError, ValueError):
        return None, f"invalid parameter value {params}"
    return Assertion(sid, clean, after, "llm"), ""


def llm_checks(rec: Recording, calls: list[StepCall], client: LLMClient,
               rejections: list[dict] | None = None, verify: bool = True) -> list[Assertion]:
    if not calls:
        return []
    try:
        answer = client.complete_json(ASSERT_SYSTEM, _llm_payload(rec, calls))
    except Exception as exc:  # réseau, JSON invalide, rejeu incomplet...
        if rejections is not None:
            rejections.append({"reason": f"llm error: {exc}"})
        return []
    out = []
    for prop in answer.get("checks", []):
        check, reason = verify_check(prop, rec, calls, check_observed=verify)
        if check:
            out.append(check)
        elif rejections is not None:
            rejections.append({"proposal": prop, "reason": reason})
    return out


# -------------------------------------------------------------------- façade
def suggest(rec: Recording, result: MatchResult, mode: str = "key",
            llm: LLMClient | None = None) -> list[Assertion]:
    """``mode`` : none | key (règles) | llm | key+llm | all (règles, y compris steps génériques)
    | llm-unverified (propositions du LLM acceptées sans comparaison avec l'état observé :
    sert uniquement à mesurer ce que la vérification évite)."""
    if mode == "none":
        return []
    calls: list[StepCall] = result.calls
    assertions = _checkpoint_checks(rec, calls)
    if mode in ("key", "all", "key+llm"):
        assertions += _rule_checks(rec, calls, mode)
    if mode in ("llm", "key+llm", "llm-unverified"):
        if llm is None:
            raise ValueError(f"assertion mode '{mode}' needs an LLM client")
        result.llm_check_rejections = []
        assertions += llm_checks(rec, calls, llm, result.llm_check_rejections,
                                 verify=mode != "llm-unverified")
    # Dédoublonnage : checkpoint > règle > LLM pour une vérification identique.
    rank = {"checkpoint": 0, "suggested": 1, "llm": 2}
    seen, unique = set(), []
    for a in sorted(assertions, key=lambda a: (a.after_call, rank[a.origin])):
        key = (a.after_call, a.step_id, tuple(sorted(map(str, a.params.items()))))
        if key not in seen:
            seen.add(key)
            unique.append(a)
    return unique
