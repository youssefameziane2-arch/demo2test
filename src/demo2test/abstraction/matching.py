"""Étape 2 de l'abstraction : rattacher les actions aux steps du catalogue.

Chaîne en cascade, du plus sûr au plus souple :

1. **Règles** : la signature d'un step métier est reconnue telle quelle, dans l'ordre.
2. **Recherche** : on interroge le catalogue (recouvrement des widgets + similarité
   textuelle) puis on accepte un step si ses actions sont toutes présentes dans
   une fenêtre, quel que soit leur ordre (corrections et clics parasites tolérés).
3. **LLM** : pour les segments restants, les *k* meilleurs candidats du catalogue
   sont injectés dans le prompt (RAG). La réponse est **vérifiée** avant d'être
   acceptée : step existant, paramètres présents *et* présents dans la trace,
   actions couvertes cohérentes avec la signature. Une proposition non vérifiable
   est rejetée, jamais « devinée ».
4. **Générique** : toute action restante devient un step d'interface, pour que le
   test reste toujours exécutable.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from ..catalog import BY_ID, SigItem, Step, business_steps, generic_for
from ..llm import LLMClient
from .actions import Action, Recording

SOURCES = ("rule", "retrieval", "llm", "generic")


@dataclass
class StepCall:
    step_id: str
    params: dict[str, Any]
    covered: list[int]
    source: str
    confidence: float = 1.0
    note: str = ""

    @property
    def step(self) -> Step:
        return BY_ID[self.step_id]

    @property
    def text(self) -> str:
        return self.step.render(**self.params)

    @property
    def anchor(self) -> int:
        return min(self.covered)


@dataclass
class MatchResult:
    calls: list[StepCall]
    ignored: list[int]                         # actions inertes écartées
    llm_rejections: list[dict] = field(default_factory=list)
    llm_calls: int = 0
    llm_check_rejections: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------- utilitaires
def _matches(action: Action, item: SigItem) -> bool:
    return action.widget == item.widget and action.kind == item.kind


def _state_timeline(rec: Recording) -> list[dict[str, Any]]:
    """Valeur de chaque widget de saisie *après* chaque action."""
    values = dict(rec.initial_state)
    timeline = []
    for a in rec.actions:
        if a.kind in ("set", "select", "toggle") and a.value is not None:
            values[a.widget] = a.value
        timeline.append(dict(values))
    return timeline


def _coerce(step: Step, name: str, value: Any) -> Any:
    if f"{{{name}:d}}" in step.pattern:
        return int(value)
    return value


def _build_params(step: Step, rec: Recording, timeline, covered: list[int]) -> dict[str, Any] | None:
    """Paramètres d'un step métier à partir des actions couvertes (la dernière valeur l'emporte)."""
    params: dict[str, Any] = {}
    last = max(covered)
    for item in step.signature:
        if not item.param:
            continue
        hits = [i for i in covered if _matches(rec.actions[i], item)]
        if hits:
            value = rec.actions[hits[-1]].value
        elif item.optional:
            value = timeline[last].get(item.widget)
        else:
            return None
        if value in (None, ""):
            return None
        params[item.param] = _coerce(step, item.param, value)
    return params


_TOKEN = re.compile(r"[a-z]+")


def _tokens(text: str) -> Counter:
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    return Counter(t for t in _TOKEN.findall(text.lower()) if len(t) > 2)


def _cosine(a: Counter, b: Counter) -> float:
    num = sum(a[t] * b[t] for t in a)
    den = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return num / den if den else 0.0


def rank_candidates(actions: list[Action], k: int = 4) -> list[tuple[Step, float]]:
    """Recherche dans le catalogue : recouvrement des widgets + similarité lexicale."""
    widgets = {a.widget for a in actions if not a.inert}
    query = _tokens(" ".join(f"{a.widget} {a.label or ''}" for a in actions if not a.inert))
    scored = []
    for step in business_steps():
        sig_widgets = {s.widget for s in step.signature}
        # Un step importé sans signature n'est retrouvé que par sa description.
        overlap = len(widgets & sig_widgets) / len(sig_widgets) if sig_widgets else 0.0
        lexical = _cosine(query, _tokens(step.description + " " + " ".join(sig_widgets)))
        scored.append((step, round(0.7 * overlap + 0.3 * lexical, 3)))
    scored.sort(key=lambda x: -x[1])
    return [s for s in scored if s[1] > 0][:k]


# ------------------------------------------------------------------- passes
class Pipeline:
    def __init__(self, use_rules: bool = True, use_retrieval: bool = True,
                 llm: LLMClient | None = None, top_k: int = 4) -> None:
        self.use_rules = use_rules
        self.use_retrieval = use_retrieval
        self.llm = llm
        self.top_k = top_k

    @property
    def name(self) -> str:
        parts = [p for p, on in (("rules", self.use_rules), ("retrieval", self.use_retrieval)) if on]
        if self.llm:
            parts.append("llm")
        return "+".join(parts) or "generic"

    def run(self, rec: Recording) -> MatchResult:
        self.rec = rec
        self.timeline = _state_timeline(rec)
        self.claimed: set[int] = set()
        self.calls: list[StepCall] = []
        self.rejections: list[dict] = []
        self.llm_calls = 0
        if self.use_rules:
            self._rules()
        if self.use_retrieval:
            for seg in self._segments():
                self._retrieval(seg)
        if self.llm:
            for seg in self._segments():
                self._llm(seg)
        ignored = self._generic()
        self.calls.sort(key=lambda c: c.anchor)
        return MatchResult(self.calls, ignored, self.rejections, self.llm_calls)

    # -- helpers
    def _active(self, i: int) -> bool:
        a = self.rec.actions[i]
        return i not in self.claimed and not a.inert and a.kind != "checkpoint"

    def _claim(self, step: Step, covered: list[int], source: str, conf: float, note: str = "",
               proposed: dict | None = None) -> bool:
        if step.signature:
            params = _build_params(step, self.rec, self.timeline, covered)
        else:  # step sans signature : paramètres proposés, déjà vérifiés dans la trace
            try:
                params = {p: _coerce(step, p, (proposed or {})[p]) for p in step.params}
            except (KeyError, ValueError):
                params = None
        if params is None:
            return False
        self.claimed.update(covered)
        self.calls.append(StepCall(step.id, params, sorted(covered), source, conf, note))
        return True

    def _segments(self) -> list[list[int]]:
        """Suites maximales d'actions non rattachées (les checkpoints coupent)."""
        segs, cur = [], []
        for i, a in enumerate(self.rec.actions):
            if a.kind == "checkpoint" or i in self.claimed:
                if any(self._active(j) for j in cur):
                    segs.append(cur)
                cur = []
            else:
                cur.append(i)
        if any(self._active(j) for j in cur):
            segs.append(cur)
        return segs

    # -- 1. règles : signature exacte, dans l'ordre, sans action parasite
    def _rules(self) -> None:
        steps = sorted(business_steps(with_signature=True), key=lambda s: -len(s.signature))
        acts, i = self.rec.actions, 0
        while i < len(acts):
            if not self._active(i):
                i += 1
                continue
            for step in steps:
                j, covered = i, []
                sig_widgets = {s.widget for s in step.signature}
                for item in step.signature:
                    # un clic sans effet sur un champ du même formulaire ne rompt pas la signature
                    while j < len(acts) and acts[j].inert and acts[j].widget in sig_widgets:
                        j += 1
                    if j < len(acts) and self._active(j) and _matches(acts[j], item):
                        covered.append(j)
                        j += 1
                    elif not item.optional:
                        covered = []
                        break
                if covered and self._claim(step, self._absorb_before(step, covered), "rule", 1.0):
                    i = j
                    break
            else:
                i += 1

    def _absorb_before(self, step: Step, covered: list[int]) -> list[int]:
        """Rattache un réglage optionnel fait juste avant le formulaire (ex. protocole puis nom)."""
        acts, missing = self.rec.actions, [it for it in step.signature
                                           if it.optional and not any(_matches(self.rec.actions[i], it)
                                                                      for i in covered)]
        k = min(covered) - 1
        while k >= 0 and missing:
            if acts[k].inert:
                k -= 1
                continue
            item = next((it for it in missing if self._active(k) and _matches(acts[k], it)), None)
            if item is None:
                break
            covered = [k] + covered
            missing.remove(item)
            k -= 1
        return covered

    # -- 2. recherche : présence de toute la signature dans une fenêtre, ordre libre
    def _retrieval(self, seg: list[int]) -> None:
        acts = self.rec.actions
        progress = True
        while progress:
            progress = False
            live = [i for i in seg if self._active(i)]
            for step, _score in rank_candidates([acts[i] for i in live], k=len(business_steps())):
                if not step.signature:
                    continue  # sans signature, seule la recherche sémantique (LLM) peut conclure
                sig_widgets = {s.widget for s in step.signature}
                required = [s for s in step.signature if not s.optional]
                for start in range(len(live)):
                    window: list[int] = []
                    for i in live[start:]:
                        if acts[i].widget not in sig_widgets:
                            break  # action étrangère au step : la fenêtre s'arrête
                        window.append(i)
                        if all(any(_matches(acts[w], it) for w in window) for it in required):
                            break
                    if window and all(any(_matches(acts[w], it) for w in window) for it in required):
                        distinct = {(acts[w].widget, acts[w].kind) for w in window}
                        dup = len(window) - len(distinct)
                        note = "tolerant match: order and noise"
                        if dup:
                            note += f", {dup} redundant action(s)"
                        if self._claim(step, window, "retrieval", 0.85, note):
                            progress = True
                            break
                if progress:
                    break

    # -- 3. LLM avec candidats issus du catalogue (RAG) + vérification
    SYSTEM = (
        "You map recorded GUI actions to steps of an existing BDD step catalog. "
        "Only use step ids from the candidate list. A step may cover several actions, "
        "in any order; the Enter key in a text field can submit a form like its button. "
        "Parameter values must be copied from the action values. "
        "Do not map actions that match no candidate. Answer with JSON only: "
        '{"steps": [{"id": str, "params": {name: value}, "covers": [action indices], '
        '"confidence": float between 0 and 1}]}'
    )

    def _llm(self, seg: list[int]) -> None:
        acts = self.rec.actions
        live = [i for i in seg if self._active(i)]
        candidates = rank_candidates([acts[i] for i in live], k=self.top_k)
        if not candidates:
            return
        payload = {
            "candidates": [{"id": s.id, "pattern": s.pattern, "description": s.description,
                            "actions": [{"widget": it.widget, "kind": it.kind,
                                         "param": it.param, "optional": it.optional}
                                        for it in s.signature]} for s, _ in candidates],
            "actions": [{"index": i, **acts[i].to_dict()} for i in live],
            "current_values": {k: v for k, v in self.timeline[live[-1]].items()
                               if not isinstance(v, (list, bool))},
        }
        self.llm_calls += 1
        try:
            answer = self.llm.complete_json(self.SYSTEM, json.dumps(payload, ensure_ascii=False))
        except Exception as exc:  # réseau, JSON invalide, réponse inconnue en replay...
            self.rejections.append({"segment": live, "reason": f"llm error: {exc}"})
            return
        allowed = {s.id for s, _ in candidates}
        for prop in answer.get("steps", []):
            reason = self._verify(prop, allowed, set(live))
            if reason:
                self.rejections.append({"proposal": prop, "reason": reason})
                continue
            step = BY_ID[prop["id"]]
            conf = float(prop.get("confidence", 0.7))
            note = "proposed by LLM, verified against trace"
            if prop.get("trimmed"):
                note += "; invalid or unrelated actions removed from the proposal"
            if not self._claim(step, sorted(prop["covers"]), "llm", min(max(conf, 0.0), 0.95),
                               note, prop.get("params")):
                self.rejections.append({"proposal": prop, "reason": "parameters not derivable"})

    def _verify(self, prop: dict, allowed: set[str], live: set[int]) -> str | None:
        acts = self.rec.actions
        sid, covers = prop.get("id"), prop.get("covers") or []
        if sid not in allowed:
            return f"step '{sid}' is not a candidate"
        valid = [i for i in covers if isinstance(i, int) and i in live and i not in self.claimed]
        if not valid:
            return "covered actions invalid or already used"
        if len(valid) != len(covers):
            # Indices hors du segment ou déjà rattachés : retirés de la proposition
            # (la suite des vérifications porte sur ce qui reste).
            covers = valid
            prop["covers"] = covers
            prop["trimmed"] = True
        step = BY_ID[sid]
        if not step.signature:
            if any(acts[i].inert for i in covers):
                return "covers an inert action"
            missing = [p for p in step.params if p not in (prop.get("params") or {})]
            if missing:
                return f"missing parameters: {', '.join(missing)}"
        sig_widgets = {s.widget for s in step.signature}
        if step.signature and any(acts[i].widget not in sig_widgets for i in covers):
            # Le LLM a inclus une action sans rapport avec ce step : on la lui retire
            # (elle sera traitée à part) et on vérifie le reste, au lieu de tout rejeter.
            covers = [i for i in covers if acts[i].widget in sig_widgets]
            if not covers:
                return "covers only actions unrelated to the step signature"
            prop["covers"] = covers
            prop["trimmed"] = True
        for item in step.signature:
            if item.optional or any(_matches(acts[i], item) for i in covers):
                continue
            # Équivalence admise : « Entrée » dans un champ du formulaire au lieu du bouton.
            if item.kind == "click" and any(acts[i].kind == "submit" for i in covers):
                continue
            return f"required action missing: {item.kind} {item.widget}"
        # Ancrage : chaque valeur proposée doit exister dans la trace.
        trace_values = {str(acts[i].value) for i in covers} | {
            str(v) for v in self.timeline[max(covers)].values()}
        for name, value in (prop.get("params") or {}).items():
            if str(value) not in trace_values:
                return f"param {name}={value!r} not found in the trace (hallucination)"
        return None

    # -- 4. filet de sécurité générique
    def _generic(self) -> list[int]:
        ignored = []
        for i, a in enumerate(self.rec.actions):
            if i in self.claimed or a.kind == "checkpoint":
                continue
            if a.inert:
                ignored.append(i)
                continue
            if a.kind == "toggle":
                step = generic_for("toggle:on" if a.value else "toggle:off")
                params = {"field": a.label}
            else:
                step = generic_for(a.kind)
                key = step.params
                params = {}
                for p in key:
                    params[p] = a.value if p == "value" else a.label
            self.claimed.add(i)
            self.calls.append(StepCall(step.id, params, [i], "generic", 1.0))
        return ignored
