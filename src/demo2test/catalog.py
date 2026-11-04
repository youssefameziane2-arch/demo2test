"""Catalogue de steps — lu dans la bibliothèque pytest-bdd elle-même.

Il n'y a pas de liste à maintenir à part : le catalogue est extrait du code de la
bibliothèque de steps (``bdd/steps.py`` par défaut, ou celle d'une autre équipe via
``use_library``). Il sert au moteur d'abstraction ; la bibliothèque, elle, exécute
les steps. Les deux ne peuvent donc pas diverger.

Deux niveaux :
* **generic** : un step par action d'interface (toujours applicable, filet de sécurité) ;
* **business** : un step métier qui regroupe plusieurs actions. Sa *signature*
  décrit les actions attendues ; elle sert aux règles, à la recherche de
  candidats et à la vérification des propositions du LLM.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SigItem:
    widget: str
    kind: str                  # set | select | toggle | click | submit
    param: str | None = None   # paramètre du step alimenté par la valeur de l'action
    optional: bool = False     # peut être absent : la valeur courante du widget est alors utilisée


@dataclass(frozen=True)
class Step:
    id: str
    keyword: str               # Given | When | Then
    pattern: str               # format pytest-bdd ``parsers.parse``
    description: str
    level: str = "generic"     # generic | business | assertion
    kinds: tuple[str, ...] = ()            # generic : types d'action couverts
    signature: tuple[SigItem, ...] = ()    # business : actions regroupées
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def params(self) -> list[str]:
        return [m.split(":")[0] for m in re.findall(r"{([^}]+)}", self.pattern)]

    def render(self, **values) -> str:
        out = self.pattern
        for spec in re.findall(r"{([^}]+)}", self.pattern):
            name = spec.split(":")[0]
            out = out.replace("{" + spec + "}", str(values[name]))
        return out


DEFAULT_LIBRARY = Path(__file__).resolve().parent / "bdd" / "steps.py"

STEPS: list[Step] = []
BY_ID: dict[str, Step] = {}


def use_library(*paths: str | Path) -> list[Step]:
    """Charge le catalogue depuis une (ou plusieurs) bibliothèque(s) pytest-bdd."""
    from .catalog_import import load_step_library

    steps = load_step_library(*paths)
    STEPS[:] = steps          # mise à jour en place : les modules qui ont importé
    BY_ID.clear()             # STEPS / BY_ID voient le nouveau catalogue
    BY_ID.update({s.id: s for s in steps})
    return steps



def business_steps(with_signature: bool = False) -> list[Step]:
    return [s for s in STEPS if s.level == "business" and (s.signature or not with_signature)]


def generic_for(kind: str) -> Step:
    for s in STEPS:
        if s.level == "generic" and kind in s.kinds:
            return s
    raise LookupError(f"the step library has no generic step for UI action '{kind}' "
                      "(add one with 'd2t: kinds=...')")


use_library(DEFAULT_LIBRARY)
