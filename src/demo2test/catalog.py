"""Catalogue de steps — source unique de vérité.

Le même catalogue sert :
* au moteur d'abstraction (rattacher des actions enregistrées à des steps),
* à la bibliothèque pytest-bdd (``bdd/steps.py``) qui exécute ces steps.

Deux niveaux :
* **generic** : un step par action d'interface (toujours applicable, filet de sécurité) ;
* **business** : un step métier qui regroupe plusieurs actions. Sa *signature*
  décrit les actions attendues ; elle sert aux règles, à la recherche de
  candidats et à la vérification des propositions du LLM.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


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


STEPS: list[Step] = [
    # ------------------------------------------------------------ contexte
    Step("given_open", "Given", "the NoC Config Studio is open",
         "Start the application with a blank design", level="context"),

    # ------------------------------------------------------------ génériques
    Step("set_field", "When", 'I set "{field}" to "{value}"',
         "Type a value into a text or number field", kinds=("set",)),
    Step("select_option", "When", 'I select "{value}" in "{field}"',
         "Choose an option in a drop-down list", kinds=("select",)),
    Step("check_box", "When", 'I check "{field}"',
         "Tick a check box", kinds=("toggle:on",)),
    Step("uncheck_box", "When", 'I uncheck "{field}"',
         "Untick a check box", kinds=("toggle:off",)),
    Step("click_button", "When", 'I click "{button}"',
         "Press a push button", kinds=("click",)),
    Step("press_enter", "When", 'I press Enter in "{field}"',
         "Validate a text field with the Enter key", kinds=("submit",)),

    # ------------------------------------------------------------ métier
    Step("create_project", "When",
         'I create the project "{name}" with a {topology} topology at {clock:d} MHz',
         "Set up a new NoC project: name, interconnect topology (mesh, ring, crossbar) "
         "and clock frequency",
         level="business",
         signature=(SigItem("projectName", "set", "name"),
                    SigItem("topology", "select", "topology", optional=True),
                    SigItem("clockMhz", "set", "clock", optional=True))),
    Step("add_initiator", "When", 'I add the initiator "{name}" using {protocol}',
         "Add an initiator (master) port such as a CPU or DMA with its bus protocol "
         "(AXI, AHB, CHI) to the network on chip",
         level="business",
         signature=(SigItem("initiatorName", "set", "name"),
                    SigItem("initiatorProtocol", "select", "protocol", optional=True),
                    SigItem("addInitiator", "click"))),
    Step("add_target", "When", 'I add the target "{name}" using {protocol}',
         "Add a target (slave) port such as a memory controller or peripheral with its "
         "bus protocol to the network on chip",
         level="business",
         signature=(SigItem("targetName", "set", "name"),
                    SigItem("targetProtocol", "select", "protocol", optional=True),
                    SigItem("addTarget", "click"))),
    Step("validate_design", "When", "I validate the design",
         "Run the design rule checks of the NoC", level="business",
         signature=(SigItem("validateBtn", "click"),)),
    Step("generate_netlist", "When", "I generate the netlist",
         "Generate the netlist file of a validated design (asynchronous)",
         level="business", signature=(SigItem("generateBtn", "click"),)),

    # ------------------------------------------------------------ assertions
    Step("status_is", "Then", 'the status shows "{text}"',
         "Check the status bar message (waits for asynchronous updates)", level="assertion",
         tags=("statusLabel",)),
    Step("list_contains", "Then", 'the "{list}" list contains "{item}"',
         "Check that a list contains an entry", level="assertion"),
    Step("list_count", "Then", 'the "{list}" list has {count:d} items',
         "Check the number of entries of a list", level="assertion"),
    Step("button_enabled", "Then", '"{button}" is enabled',
         "Check that a button can be used", level="assertion"),
    Step("button_disabled", "Then", '"{button}" is disabled',
         "Check that a button cannot be used", level="assertion"),
]

BY_ID = {s.id: s for s in STEPS}


def business_steps() -> list[Step]:
    return [s for s in STEPS if s.level == "business"]


def generic_for(kind: str) -> Step:
    return next(s for s in STEPS if s.level == "generic" and kind in s.kinds)
