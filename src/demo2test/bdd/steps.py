"""Bibliothèque de steps pytest-bdd qui exécute les scénarios générés.

Plugin pytest : ``pytest_plugins = ["demo2test.bdd.steps"]``. Chaque step est
enregistré à partir du catalogue (``catalog.STEPS``) : un step absent de la
bibliothèque ferait échouer ``test_catalog_is_fully_implemented``.

Synchronisation : les assertions *attendent* la condition (``qtbot.waitUntil``)
au lieu d'utiliser des pauses fixes — robustes face aux traitements asynchrones.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QComboBox, QLineEdit, QListWidget, QSpinBox, QWidget
from pytest_bdd import given, parsers, then, when

from ..app.noc_studio import NocStudioWindow
from ..catalog import BY_ID

WAIT_TIMEOUT_MS = 3000
IMPLEMENTED: set[str] = set()


def _p(step_id: str):
    IMPLEMENTED.add(step_id)
    return parsers.parse(BY_ID[step_id].pattern)


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
def studio(qtbot):
    window = NocStudioWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    return window


# ------------------------------------------------------------------ Given
@given(_p("given_open"))
def _open(studio):
    return studio


# -------------------------------------------------------------- génériques
@when(_p("set_field"))
def _set(qtbot, studio, field, value):
    type_into(qtbot, find(studio, field), value)


@when(_p("select_option"))
def _select(studio, field, value):
    choose(find(studio, field), value)


@when(_p("check_box"))
def _check(qtbot, studio, field):
    box = find(studio, field)
    if not box.isChecked():
        click(qtbot, box)


@when(_p("uncheck_box"))
def _uncheck(qtbot, studio, field):
    box = find(studio, field)
    if box.isChecked():
        click(qtbot, box)


@when(_p("click_button"))
def _click(qtbot, studio, button):
    click(qtbot, find(studio, button))


@when(_p("press_enter"))
def _enter(studio, field):
    QTest.keyClick(find(studio, field), Qt.Key_Return)


# ------------------------------------------------------------------ métier
@when(_p("create_project"))
def _create_project(qtbot, studio, name, topology, clock):
    type_into(qtbot, studio.project_name, name)
    choose(studio.topology, topology)
    type_into(qtbot, studio.clock, clock)


@when(_p("add_initiator"))
def _add_initiator(qtbot, studio, name, protocol):
    type_into(qtbot, studio.initiator_name, name)
    choose(studio.initiator_protocol, protocol)
    click(qtbot, studio.add_initiator_btn)


@when(_p("add_target"))
def _add_target(qtbot, studio, name, protocol):
    type_into(qtbot, studio.target_name, name)
    choose(studio.target_protocol, protocol)
    click(qtbot, studio.add_target_btn)


@when(_p("validate_design"))
def _validate(qtbot, studio):
    click(qtbot, studio.validate_btn)


@when(_p("generate_netlist"))
def _generate(qtbot, studio):
    click(qtbot, studio.generate_btn)


# -------------------------------------------------------------- assertions
@then(_p("status_is"))
def _status(qtbot, studio, text):
    qtbot.waitUntil(lambda: studio.status.text() == text, timeout=WAIT_TIMEOUT_MS)


@then(_p("list_contains"))
def _list_contains(qtbot, studio, list, item):  # noqa: A002 (nom imposé par le step)
    widget: QListWidget = find(studio, list)
    qtbot.waitUntil(lambda: item in [widget.item(i).text() for i in range(widget.count())],
                    timeout=WAIT_TIMEOUT_MS)


@then(_p("list_count"))
def _list_count(qtbot, studio, list, count):  # noqa: A002
    widget: QListWidget = find(studio, list)
    qtbot.waitUntil(lambda: widget.count() == count, timeout=WAIT_TIMEOUT_MS)


@then(_p("button_enabled"))
def _enabled(qtbot, studio, button):
    widget = find(studio, button)
    qtbot.waitUntil(widget.isEnabled, timeout=WAIT_TIMEOUT_MS)


@then(_p("button_disabled"))
def _disabled(qtbot, studio, button):
    widget = find(studio, button)
    qtbot.waitUntil(lambda: not widget.isEnabled(), timeout=WAIT_TIMEOUT_MS)
