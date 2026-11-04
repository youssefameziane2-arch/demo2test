"""Rejoue des démonstrations « comme un humain » (souris + clavier via QTest).

Sert à constituer un jeu d'évaluation reproductible : chaque scénario est joué
sur la vraie application pendant que l'enregistreur tourne, exactement comme si
un testeur l'avait fait à la main (y compris hésitations, fautes de frappe,
clics inutiles et raccourcis clavier).
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QWidget

from .app.noc_studio import NocStudioWindow
from .recorder.recorder import Recorder
from .recorder.trace import RawEvent

HUMAN_PAUSE_MS = 30


class Player:
    def __init__(self, window: NocStudioWindow, recorder: Recorder) -> None:
        self.w = window
        self.rec = recorder

    def _get(self, name: str) -> QWidget:
        widget = self.w.findChild(QWidget, name)
        if widget is None:
            raise LookupError(name)
        return widget

    def pause(self, ms: int = HUMAN_PAUSE_MS) -> Player:
        QTest.qWait(ms)
        return self

    def click(self, name: str) -> Player:
        widget = self._get(name)
        target = widget.viewport() if hasattr(widget, "viewport") else widget
        if isinstance(widget, QCheckBox):  # viser la case, pas le centre du widget étiré
            QTest.mouseClick(widget, Qt.LeftButton, Qt.NoModifier, QPoint(8, widget.height() // 2))
        else:
            QTest.mouseClick(target, Qt.LeftButton)
        self.pause()
        return self

    def type(self, name: str, text: str, replace: bool = True) -> Player:
        self.click(name)
        widget = self._get(name)
        if replace:
            QTest.keyClick(widget, Qt.Key_A, Qt.ControlModifier)
            QTest.keyClick(widget, Qt.Key_Backspace)
        QTest.keyClicks(widget, text)
        self.pause()
        return self

    def backspace(self, name: str, n: int) -> Player:
        for _ in range(n):
            QTest.keyClick(self._get(name), Qt.Key_Backspace)
        self.pause()
        return self

    def pick(self, name: str, value: str) -> Player:
        """Sélection au clavier dans une liste déroulante (flèches)."""
        combo: QComboBox = self._get(name)
        self.click(name)
        target = combo.findText(value)
        while combo.currentIndex() != target:
            key = Qt.Key_Down if combo.currentIndex() < target else Qt.Key_Up
            QTest.keyClick(combo, key)
        self.pause()
        return self

    def enter(self, name: str) -> Player:
        QTest.keyClick(self._get(name), Qt.Key_Return)
        self.pause()
        return self

    def tab(self, name: str) -> Player:
        QTest.keyClick(self._get(name), Qt.Key_Tab)
        self.pause()
        return self

    def checkpoint(self) -> Player:
        QTest.keyClick(self.w, Qt.Key_K, Qt.ControlModifier | Qt.ShiftModifier)
        self.pause()
        return self


def record(play, settle_ms: int = 80) -> list[RawEvent]:
    """Lance l'application, enregistre ``play(player)`` et renvoie la trace."""
    app = QApplication.instance() or QApplication([])
    window = NocStudioWindow()
    window.show()
    QTest.qWaitForWindowExposed(window)
    recorder = Recorder(window)
    recorder.start()
    try:
        play(Player(window, recorder))
        QTest.qWait(settle_ms)
    finally:
        events = recorder.stop()
        window.close()
        window.deleteLater()
        app.processEvents()
    return events
