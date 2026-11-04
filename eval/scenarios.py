"""Jeu d'évaluation : 12 démonstrations et le test qu'un ingénieur QA écrirait à la main.

Chaque scénario combine un parcours métier et une difficulté réaliste
(ordre de saisie différent, faute de frappe, clic parasite, touche Entrée...).
La vérité terrain est la liste des steps ``When`` attendus.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from demo2test.player import Player


@dataclass
class Scenario:
    name: str
    difficulty: str
    play: Callable[[Player], None]
    expected: list[tuple[str, dict]]


def _project(p: Player, name="soc_a", topo=None, clock=None):
    p.type("projectName", name)
    if topo:
        p.pick("topology", topo)
    if clock:
        p.type("clockMhz", str(clock))


def s01(p):
    _project(p, clock=1200)
    p.type("initiatorName", "cpu0").click("addInitiator")
    p.type("targetName", "ddr0").click("addTarget")
    p.click("validateBtn").click("generateBtn").pause(600)


def s02(p):
    _project(p, "soc_b", "Crossbar")
    p.pick("initiatorProtocol", "CHI").type("initiatorName", "cpu0").click("addInitiator")
    p.pick("targetProtocol", "AHB").type("targetName", "uart0").click("addTarget")
    p.click("validateBtn")


def s03(p):
    _project(p, "soc_c")
    p.type("initiatorName", "cpu").backspace("initiatorName", 3)
    p.type("initiatorName", "dsp0", replace=False).click("addInitiator")
    p.type("targetName", "sram0").click("addTarget").click("validateBtn")


def s04(p):
    _project(p, "soc_d")
    p.type("initiatorName", "cpu0").click("initiatorList").click("statusLabel").click("addInitiator")
    p.type("targetName", "ddr0").click("addTarget").click("validateBtn")


def s05(p):
    _project(p, "soc_e")
    p.type("initiatorName", "cpu0").enter("initiatorName")
    p.type("targetName", "ddr0").click("addTarget").click("validateBtn")


def s06(p):
    _project(p, "soc_f", "Ring")
    p.type("initiatorName", "cpu0").click("addInitiator")
    p.type("targetName", "ddr0").click("addTarget")
    p.click("validateBtn").checkpoint()


def s07(p):
    _project(p, "soc_g")
    p.type("initiatorName", "cpu0").click("addInitiator")
    p.type("targetName", "cpu0").click("addTarget").checkpoint()


def s08(p):
    _project(p, "soc_h", clock=800)
    p.click("enableQos")
    p.type("initiatorName", "gpu0").pick("initiatorProtocol", "AHB").click("addInitiator")
    p.type("targetName", "ddr0").click("addTarget").click("validateBtn")


def s09(p):
    _project(p, "soc_i", "Mesh", 2000)
    p.type("initiatorName", "cpu0").click("addInitiator")
    p.type("initiatorName", "cpu1").pick("initiatorProtocol", "CHI").click("addInitiator")
    p.type("targetName", "ddr0").click("addTarget")
    p.click("validateBtn").click("generateBtn").pause(600).checkpoint()


def s10(p):
    _project(p, "soc_j")
    p.type("initiatorName", "cpu0").click("addInitiator")
    p.type("targetName", "ddr0").click("addTarget")
    p.type("clockMhz", "1500").click("validateBtn")


def s11(p):
    _project(p, "soc_k")
    p.type("initiatorName", "dma0").click("addInitiator")
    p.type("targetName", "flash0").pick("targetProtocol", "AHB").enter("targetName")
    p.click("validateBtn")


def s12(p):
    _project(p, "soc_l")
    p.click("targetName").click("initiatorName")  # hésitation : champs ouverts puis abandonnés
    p.pick("initiatorProtocol", "AHB").pick("initiatorProtocol", "AXI")
    p.type("initiatorName", "cpu0").click("addInitiator")
    p.type("targetName", "ddr0").click("addTarget").click("validateBtn")


def proj(name, topo="Mesh", clock=1000):
    return ("create_project", {"name": name, "topology": topo, "clock": clock})


def ini(name, proto="AXI"):
    return ("add_initiator", {"name": name, "protocol": proto})


def tgt(name, proto="AXI"):
    return ("add_target", {"name": name, "protocol": proto})


V = ("validate_design", {})
G = ("generate_netlist", {})

SCENARIOS = [
    Scenario("s01_happy_path", "nominal, asynchronous generation", s01,
             [proj("soc_a", clock=1200), ini("cpu0"), tgt("ddr0"), V, G]),
    Scenario("s02_protocol_first", "protocol chosen before the name", s02,
             [proj("soc_b", "Crossbar"), ini("cpu0", "CHI"), tgt("uart0", "AHB"), V]),
    Scenario("s03_typo", "typing mistake corrected", s03,
             [proj("soc_c"), ini("dsp0"), tgt("sram0"), V]),
    Scenario("s04_noise_clicks", "useless clicks in the middle of a form", s04,
             [proj("soc_d"), ini("cpu0"), tgt("ddr0"), V]),
    Scenario("s05_enter_key", "form submitted with Enter instead of the button", s05,
             [proj("soc_e"), ini("cpu0"), tgt("ddr0"), V]),
    Scenario("s06_ring_error", "design rule error + checkpoint", s06,
             [proj("soc_f", "Ring"), ini("cpu0"), tgt("ddr0"), V]),
    Scenario("s07_duplicate", "rejected duplicate name + checkpoint", s07,
             [proj("soc_g"), ini("cpu0"), tgt("cpu0")]),
    Scenario("s08_qos", "check box with no business step", s08,
             [proj("soc_h", clock=800), ("check_box", {"field": "Enable QoS"}), ini("gpu0", "AHB"),
              tgt("ddr0"), V]),
    Scenario("s09_two_initiators", "repeated step + async + checkpoint", s09,
             [proj("soc_i", "Mesh", 2000), ini("cpu0"), ini("cpu1", "CHI"), tgt("ddr0"), V, G]),
    Scenario("s10_late_edit", "isolated edit after the project setup", s10,
             [proj("soc_j"), ini("cpu0"), tgt("ddr0"),
              ("set_field", {"field": "Clock (MHz)", "value": 1500}), V]),
    Scenario("s11_enter_permuted", "Enter key + protocol after the name", s11,
             [proj("soc_k"), ini("dma0"), tgt("flash0", "AHB"), V]),
    Scenario("s12_hesitation", "abandoned fields and reverted choice", s12,
             [proj("soc_l"), ini("cpu0"), tgt("ddr0"), V]),
]


# --------------------------------------------------------------------------------
# Jeu indépendant : démonstrations enregistrées À LA MAIN par une autre personne
# (Youssef), à partir de consignes. Il les réalise à sa façon (ordre, fautes,
# souris ou clavier) ; seule la consigne fixe le test attendu.
# --------------------------------------------------------------------------------
USER_TASKS = {
    "u01_crossbar": (
        "Crée le projet « youssef_soc » en topologie Crossbar à 1600 MHz. Ajoute les initiateurs "
        "« cpu0 » (AXI) et « dma0 » (AHB), puis la cible « ddr0 » (CHI). Valide, génère la "
        "netlist, attends le message « Generated », puis appuie sur Ctrl+Maj+K.",
        [proj("youssef_soc", "Crossbar", 1600), ini("cpu0"), ini("dma0", "AHB"), tgt("ddr0", "CHI"),
         V, G]),
    "u02_ring_fix": (
        "Crée le projet « ring_test » en topologie Ring. Ajoute l'initiateur « cpu0 » et la cible "
        "« sram0 ». Valide : une erreur s'affiche, appuie sur Ctrl+Maj+K. Ajoute ensuite la cible "
        "« uart0 » (AHB), valide de nouveau, puis appuie sur Ctrl+Maj+K.",
        [proj("ring_test", "Ring"), ini("cpu0"), tgt("sram0"), V, tgt("uart0", "AHB"), V]),
    "u03_qos_enter": (
        "Crée le projet « qos_soc ». Coche « Enable QoS ». Ajoute l'initiateur « gpu0 » (CHI) en "
        "validant le nom avec la touche Entrée au lieu du bouton. Ajoute la cible « ddr0 ». "
        "Valide puis génère la netlist.",
        [proj("qos_soc"), ("check_box", {"field": "Enable QoS"}), ini("gpu0", "CHI"), tgt("ddr0"), V, G]),
}

USER_SCENARIOS = [Scenario(name, "recorded by hand from written instructions", None, expected)
                  for name, (_, expected) in USER_TASKS.items()]
