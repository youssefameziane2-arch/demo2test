"""Mutants de l'application, pour mesurer si les tests générés détectent vraiment les régressions.

Un test qui passe toujours ne protège de rien. Le banc exécute les scénarios générés
contre des versions volontairement défectueuses de l'application (une régression
réaliste par mutant) : un mutant est **tué** si au moins un scénario échoue.
Le *score de mutation* (mutants tués / mutants) mesure la valeur des vérifications.

Activation : variable d'environnement ``D2T_MUTANT=<nom>`` (fixture ``studio``).
"""
from __future__ import annotations

from PySide6.QtCore import QTimer

from ..app.noc_studio import GENERATION_DELAY_MS, NocDesign, NocStudioWindow

_original_validate = NocDesign.validate
_original_add = NocDesign._add
_original_finish = NocStudioWindow._finish_generation
_original_validate_slot = NocStudioWindow._validate
_original_add_port = NocStudioWindow._add_port


def _ring_rule_ignored(self):
    return [e for e in _original_validate(self) if "ring" not in e]


def _duplicates_allowed(self, bucket, name, protocol):
    name = name.strip()
    if not name:
        return "Error: name is required"
    bucket.append((name, protocol))
    return None


def _wrong_extension(self):
    self._set_status(f"Generated {self.design.name.strip()}.net")
    self.generate_btn.setEnabled(True)


def _generation_hangs(self):
    if not self._valid:
        return
    self.generate_btn.setEnabled(False)
    self._set_status("Generating...")  # ... et la génération ne se termine jamais


def _counts_swapped(self):
    _original_validate_slot(self)
    if self._valid:
        d = self.design
        self._set_status(f"Valid: {len(d.targets)} initiators, {len(d.initiators)} targets")


def _generate_stays_disabled(self):
    _original_validate_slot(self)
    self.generate_btn.setEnabled(False)


def _protocol_not_shown(self, add, name_edit, proto_combo, lst):
    name, proto = name_edit.text().strip(), proto_combo.currentText()
    error = add(name, proto)
    if error:
        self._set_status(error)
        return
    lst.addItem(f"{name} (AXI)")  # affiche toujours AXI, quel que soit le protocole choisi
    name_edit.clear()
    self._invalidate()
    self._set_status(f"Added {name}")


def _added_status_missing(self, add, name_edit, proto_combo, lst):
    _original_add_port(self, add, name_edit, proto_combo, lst)
    if self.status.text().startswith("Added"):
        self._set_status("Ready")


def _slow_generation(self):
    # Régression de performance : 10 fois plus lent que le délai observé.
    if not self._valid:
        return
    self.generate_btn.setEnabled(False)
    self._set_status("Generating...")
    QTimer.singleShot(GENERATION_DELAY_MS * 10, self._finish_generation)


MUTANTS = {
    "ring_rule_ignored": (NocDesign, "validate", _ring_rule_ignored,
                          "la règle « un anneau demande 3 extrémités » n'est plus appliquée"),
    "duplicates_allowed": (NocDesign, "_add", _duplicates_allowed,
                           "deux ports peuvent porter le même nom"),
    "wrong_extension": (NocStudioWindow, "_finish_generation", _wrong_extension,
                        "la netlist générée porte la mauvaise extension"),
    "generation_hangs": (NocStudioWindow, "_generate", _generation_hangs,
                         "la génération ne se termine jamais"),
    "counts_swapped": (NocStudioWindow, "_validate", _counts_swapped,
                       "le message de validation inverse initiateurs et cibles"),
    "generate_stays_disabled": (NocStudioWindow, "_validate", _generate_stays_disabled,
                                "le bouton de génération reste grisé après validation"),
    "protocol_not_shown": (NocStudioWindow, "_add_port", _protocol_not_shown,
                           "la liste affiche AXI quel que soit le protocole choisi"),
    "added_status_missing": (NocStudioWindow, "_add_port", _added_status_missing,
                             "plus de message de confirmation après un ajout"),
    "slow_generation": (NocStudioWindow, "_generate", _slow_generation,
                        "la génération devient 10 fois plus lente"),
}


def apply_mutant(name: str | None, monkeypatch) -> None:
    if not name:
        return
    target, attr, replacement, _ = MUTANTS[name]
    # Appliqué avant la création de la fenêtre : les signaux se relient à la version mutée.
    monkeypatch.setattr(target, attr, replacement)
