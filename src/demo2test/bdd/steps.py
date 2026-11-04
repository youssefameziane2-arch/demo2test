"""Bibliothèque de steps pytest-bdd : c'est elle, le « catalogue de test ».

Comme dans une vraie équipe, le catalogue n'est pas maintenu à part : demo2test
le **lit directement dans le code de la bibliothèque** (analyse AST, voir
``catalog_import``). Chaque step décrit ce qu'il fait dans sa docstring ; la ligne
``d2t:`` facultative indique les actions d'interface qu'il regroupe, ce qui permet
aux règles de le reconnaître. Un step sans ligne ``d2t:`` reste utilisable par la
recherche dans le catalogue et par le LLM.

Format de la ligne ``d2t:`` ::

    d2t: id=<identifiant> kinds=<type d'action>             (step générique)
    d2t: id=<identifiant> sig=<widget>:<action>[:<param>[?]], ...   (step métier)

Synchronisation : les assertions *attendent* la condition (``qtbot.waitUntil``)
au lieu d'utiliser des pauses fixes — robustes face aux traitements asynchrones.
"""
from __future__ import annotations

import os

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QComboBox, QLineEdit, QListWidget, QSpinBox, QWidget
from pytest_bdd import given, parsers, then, when

from ..app.noc_studio import NocStudioWindow
from .mutants import apply_mutant

WAIT_TIMEOUT_MS = int(os.environ.get("D2T_WAIT_MS", "3000"))


def find(window: QWidget, label: str) -> QWidget:
    """Retrouve un widget par son nom accessible (ou son objectName)."""
    for w in window.findChildren(QWidget):
        if w.accessibleName() == label or w.objectName() == label:
            return w
    raise LookupError(f"no widget labelled {label!r}")


def type_into(qtbot, widget: QWidget, value) -> None:
    widget.setFocus()
    if isinstance(widget, QSpinBox):
        widget.selectAll()
        QTest.keyClicks(widget, str(value))
        widget.interpretText()
    elif isinstance(widget, QLineEdit):
        widget.selectAll()
        QTest.keyClick(widget, Qt.Key_Backspace)  # vider vraiment le champ, même pour ""
        QTest.keyClicks(widget, str(value))
    else:
        raise TypeError(f"cannot type into {type(widget).__name__}")


def choose(widget: QComboBox, value: str) -> None:
    index = widget.findText(value)
    if index < 0:
        raise ValueError(f"{value!r} is not an option of {widget.accessibleName()!r}")
    widget.setCurrentIndex(index)


def click(qtbot, widget: QAbstractButton) -> None:
    assert widget.isEnabled(), f"{widget.accessibleName()!r} is disabled"
    qtbot.mouseClick(widget, Qt.LeftButton)


@pytest.fixture
def studio(qtbot, monkeypatch):
    apply_mutant(os.environ.get("D2T_MUTANT"), monkeypatch)  # banc de mutation, sinon rien
    window = NocStudioWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    return window


# ------------------------------------------------------------------ Given
@given("the NoC Config Studio is open")
def _open(studio):
    """Start the application with a blank design.

    d2t: id=given_open
    """
    return studio


# -------------------------------------------------------------- génériques
@when(parsers.parse('I set "{field}" to "{value}"'))
def _set(qtbot, studio, field, value):
    """Type a value into a text or number field.

    d2t: id=set_field kinds=set
    """
    type_into(qtbot, find(studio, field), value)


@when(parsers.parse('I select "{value}" in "{field}"'))
def _select(studio, field, value):
    """Choose an option in a drop-down list.

    d2t: id=select_option kinds=select
    """
    choose(find(studio, field), value)


@when(parsers.parse('I check "{field}"'))
def _check(qtbot, studio, field):
    """Tick a check box.

    d2t: id=check_box kinds=toggle:on
    """
    box = find(studio, field)
    if not box.isChecked():
        click(qtbot, box)


@when(parsers.parse('I uncheck "{field}"'))
def _uncheck(qtbot, studio, field):
    """Untick a check box.

    d2t: id=uncheck_box kinds=toggle:off
    """
    box = find(studio, field)
    if box.isChecked():
        click(qtbot, box)


@when(parsers.parse('I click "{button}"'))
def _click(qtbot, studio, button):
    """Press a push button.

    d2t: id=click_button kinds=click
    """
    click(qtbot, find(studio, button))


@when(parsers.parse('I press Enter in "{field}"'))
def _enter(studio, field):
    """Validate a text field with the Enter key.

    d2t: id=press_enter kinds=submit
    """
    QTest.keyClick(find(studio, field), Qt.Key_Return)


# ------------------------------------------------------------------ métier
@when(parsers.parse('I create the project "{name}" with a {topology} topology at {clock:d} MHz'))
def _create_project(qtbot, studio, name, topology, clock):
    """Set up a new NoC project: name, interconnect topology (mesh, ring, crossbar)
    and clock frequency.

    d2t: id=create_project sig=projectName:set:name, topology:select:topology?, clockMhz:set:clock?
    """
    type_into(qtbot, studio.project_name, name)
    choose(studio.topology, topology)
    type_into(qtbot, studio.clock, clock)


@when(parsers.parse('I add the initiator "{name}" using {protocol}'))
def _add_initiator(qtbot, studio, name, protocol):
    """Add an initiator (master) port such as a CPU or DMA with its bus protocol
    (AXI, AHB, CHI) to the network on chip.

    d2t: id=add_initiator sig=initiatorName:set:name, initiatorProtocol:select:protocol?, addInitiator:click
    """
    type_into(qtbot, studio.initiator_name, name)
    choose(studio.initiator_protocol, protocol)
    click(qtbot, studio.add_initiator_btn)


@when(parsers.parse('I add the target "{name}" using {protocol}'))
def _add_target(qtbot, studio, name, protocol):
    """Add a target (slave) port such as a memory controller or peripheral with its bus
    protocol to the network on chip.

    d2t: id=add_target sig=targetName:set:name, targetProtocol:select:protocol?, addTarget:click
    """
    type_into(qtbot, studio.target_name, name)
    choose(studio.target_protocol, protocol)
    click(qtbot, studio.add_target_btn)


@when("I validate the design")
def _validate(qtbot, studio):
    """Run the design rule checks of the NoC.

    d2t: id=validate_design sig=validateBtn:click
    """
    click(qtbot, studio.validate_btn)


@when("I generate the netlist")
def _generate(qtbot, studio):
    """Generate the netlist file of a validated design (asynchronous).

    d2t: id=generate_netlist sig=generateBtn:click
    """
    click(qtbot, studio.generate_btn)


# -------------------------------------------------------------- assertions
@then(parsers.parse('the status shows "{text}"'))
def _status(qtbot, studio, text):
    """Check the status bar message (waits for asynchronous updates).

    d2t: id=status_is
    """
    qtbot.waitUntil(lambda: studio.status.text() == text, timeout=WAIT_TIMEOUT_MS)


@then(parsers.parse('the "{list}" list contains "{item}"'))
def _list_contains(qtbot, studio, list, item):  # noqa: A002 (nom imposé par le step)
    """Check that a list contains an entry.

    d2t: id=list_contains
    """
    widget: QListWidget = find(studio, list)
    qtbot.waitUntil(lambda: item in [widget.item(i).text() for i in range(widget.count())],
                    timeout=WAIT_TIMEOUT_MS)


@then(parsers.parse('the "{list}" list has {count:d} items'))
def _list_count(qtbot, studio, list, count):  # noqa: A002
    """Check the number of entries of a list.

    d2t: id=list_count
    """
    widget: QListWidget = find(studio, list)
    qtbot.waitUntil(lambda: widget.count() == count, timeout=WAIT_TIMEOUT_MS)


@then(parsers.parse('"{button}" is enabled'))
def _enabled(qtbot, studio, button):
    """Check that a button can be used.

    d2t: id=button_enabled
    """
    widget = find(studio, button)
    qtbot.waitUntil(widget.isEnabled, timeout=WAIT_TIMEOUT_MS)


@then(parsers.parse('"{button}" is disabled'))
def _disabled(qtbot, studio, button):
    """Check that a button cannot be used.

    d2t: id=button_disabled
    """
    widget = find(studio, button)
    qtbot.waitUntil(lambda: not widget.isEnabled(), timeout=WAIT_TIMEOUT_MS)
