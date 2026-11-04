"""Enregistreur d'interactions par instrumentation Qt.

Trois sources complémentaires, comme le suggère l'analyse d'instrumentation :

1. **Filtre d'événements** installé sur ``QApplication`` : capture les entrées
   brutes (clics, touches) quel que soit le widget visé, y compris les
   sous-widgets internes (viewport d'une liste, popup d'une combo).
2. **Signaux des widgets de saisie** (textChanged, valueChanged...) : donnent la
   valeur finale, indépendamment de la façon dont l'utilisateur l'a saisie.
3. **Observation périodique** des widgets non interactifs (labels, listes,
   état activé des boutons) : capte les effets, y compris asynchrones.

Le rattachement d'un événement à un widget se fait par l'``accessibleName`` :
seuls les widgets « annoncés » par l'application sont tracés, ce qui filtre le
bruit (conteneurs, layouts) sans connaître l'application à l'avance.
"""
from __future__ import annotations

import time
from typing import Any

import shiboken6
from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QCheckBox,
    QComboBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QSpinBox,
    QWidget,
)

from .trace import (
    CHECKPOINT,
    INPUT_CLICK,
    INPUT_KEY,
    SESSION_START,
    STATE_INPUT,
    STATE_OBSERVED,
    RawEvent,
)

CHECKPOINT_SHORTCUT = (Qt.Key_K, Qt.ControlModifier | Qt.ShiftModifier)
POLL_INTERVAL_MS = 25

_KEY_NAMES = {
    Qt.Key_Return: "Return", Qt.Key_Enter: "Enter", Qt.Key_Tab: "Tab",
    Qt.Key_Backspace: "Backspace", Qt.Key_Delete: "Delete", Qt.Key_Down: "Down",
    Qt.Key_Up: "Up", Qt.Key_Escape: "Escape", Qt.Key_Home: "Home", Qt.Key_End: "End",
}


def widget_value(w: QWidget) -> Any:
    """Valeur « métier » d'un widget, utilisée pour les traces et les assertions."""
    if isinstance(w, QLineEdit):
        return w.text()
    if isinstance(w, QComboBox):
        return w.currentText()
    if isinstance(w, QSpinBox):
        return w.value()
    if isinstance(w, QCheckBox):
        return w.isChecked()
    if isinstance(w, QListWidget):
        return [w.item(i).text() for i in range(w.count())]
    if isinstance(w, QLabel):
        return w.text()
    if isinstance(w, QAbstractButton):
        return w.isEnabled()
    return None


def observed_property(w: QWidget) -> str | None:
    if isinstance(w, QLabel):
        return "text"
    if isinstance(w, QListWidget):
        return "items"
    if isinstance(w, QAbstractButton) and not isinstance(w, QCheckBox):
        return "enabled"
    return None


class Recorder(QObject):
    """Enregistre une démonstration jouée sur une fenêtre Qt."""

    def __init__(self, root: QWidget, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.root = root
        self.events: list[RawEvent] = []
        self._t0 = 0.0
        self._seq = 0
        self._last_event: tuple[int, int, QObject] | None = None
        self._observed: dict[str, Any] = {}
        self._connections: list[tuple[Any, Any]] = []
        self._poller = QTimer(self)
        self._poller.setInterval(POLL_INTERVAL_MS)
        self._poller.timeout.connect(self._poll)
        self.recording = False

    # ------------------------------------------------------------ cycle de vie
    def named_widgets(self) -> list[QWidget]:
        return [w for w in self.root.findChildren(QWidget) if w.accessibleName()]

    def start(self) -> None:
        self.events.clear()
        self._seq = 0
        self._t0 = time.monotonic()
        snapshot = {w.objectName(): widget_value(w) for w in self.named_widgets()}
        self._emit(SESSION_START, value=snapshot)
        self._observed = {
            w.objectName(): widget_value(w)
            for w in self.named_widgets() if observed_property(w)
        }
        self._hook_inputs()
        QApplication.instance().installEventFilter(self)
        self._poller.start()
        self.recording = True

    def stop(self) -> list[RawEvent]:
        if not self.recording:
            return self.events
        self._poll()
        self._poller.stop()
        QApplication.instance().removeEventFilter(self)
        for signal, slot in self._connections:
            signal.disconnect(slot)
        self._connections.clear()
        self.recording = False
        return self.events

    def checkpoint(self, note: str | None = None) -> None:
        """Point de vérification : fige l'état observable courant."""
        self._poll()
        state = {w.objectName(): widget_value(w)
                 for w in self.named_widgets() if observed_property(w)}
        self._emit(CHECKPOINT, value=state, text=note)

    # ------------------------------------------------------------- internals
    def _emit(self, type_: str, widget: QWidget | None = None, **kw) -> RawEvent:
        self._seq += 1
        ev = RawEvent(
            seq=self._seq,
            t_ms=int((time.monotonic() - self._t0) * 1000),
            type=type_,
            widget=widget.objectName() if widget is not None else None,
            cls=type(widget).__name__ if widget is not None else None,
            label=widget.accessibleName() if widget is not None else None,
            **kw,
        )
        self.events.append(ev)
        return ev

    def _hook_inputs(self) -> None:
        for w in self.named_widgets():
            signal = None
            if isinstance(w, QLineEdit):
                signal = w.textChanged
            elif isinstance(w, QComboBox):
                signal = w.currentTextChanged
            elif isinstance(w, QSpinBox):
                signal = w.valueChanged
            elif isinstance(w, QCheckBox):
                signal = w.toggled
            if signal is None:
                continue
            def slot(_=None, widget=w):
                self._emit(STATE_INPUT, widget, value=widget_value(widget))

            signal.connect(slot)
            self._connections.append((signal, slot))

    def _resolve(self, obj: QObject) -> QWidget | None:
        """Remonte au premier ancêtre annoncé (accessibleName)."""
        w = obj if isinstance(obj, QWidget) else None
        while w is not None:
            if w.accessibleName() and self.root.isAncestorOf(w):
                return w
            w = w.parentWidget()
        return None

    def _is_duplicate(self, obj: QObject, event: QEvent) -> bool:
        # Un événement non accepté est re-présenté au filtre pour chaque parent :
        # même objet QEvent, reçu cette fois par un ancêtre du destinataire précédent.
        ptr = int(shiboken6.getCppPointer(event)[0])
        last = self._last_event
        self._last_event = (ptr, int(event.type()), obj)
        if last is None or last[:2] != (ptr, int(event.type())):
            return False
        prev = last[2]
        return (isinstance(obj, QWidget) and isinstance(prev, QWidget)
                and shiboken6.isValid(prev) and obj is not prev and obj.isAncestorOf(prev))

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 (API Qt)
        etype = event.type()
        if etype not in (QEvent.MouseButtonRelease, QEvent.KeyPress):
            return False
        if etype == QEvent.KeyPress and (event.key(), event.modifiers()) == CHECKPOINT_SHORTCUT:
            if not self._is_duplicate(obj, event):
                self.checkpoint()
            return True  # le raccourci est consommé par l'enregistreur
        widget = self._resolve(obj)
        if widget is None or self._is_duplicate(obj, event):
            return False
        self._poll()  # rattacher les effets en attente à l'action précédente
        if etype == QEvent.MouseButtonRelease:
            self._emit(INPUT_CLICK, widget)
        else:
            key = _KEY_NAMES.get(event.key()) or (event.text() or None)
            self._emit(INPUT_KEY, widget, key=key, text=event.text() or None)
        QTimer.singleShot(0, self._poll)  # capter l'effet immédiat de l'action
        return False

    def _poll(self) -> None:
        for w in self.named_widgets():
            prop = observed_property(w)
            if not prop:
                continue
            value = widget_value(w)
            name = w.objectName()
            if self._observed.get(name) != value:
                self._observed[name] = value
                self._emit(STATE_OBSERVED, w, value=value, prop=prop)
