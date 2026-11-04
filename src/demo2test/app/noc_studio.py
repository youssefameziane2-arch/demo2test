"""NoC Config Studio — application Qt servant de système sous test.

Petit outil inspiré du domaine EDA : on décrit un Network-on-Chip (topologie,
fréquence, initiateurs et cibles), on le valide, puis on « génère » une netlist.
La génération est volontairement asynchrone (QTimer) pour que les tests aient à
gérer la synchronisation, comme sur un vrai outil industriel.

Chaque widget interactif porte un ``objectName`` (identifiant stable pour les
tests) et un ``accessibleName`` (libellé lisible, utilisé dans le Gherkin).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

PROTOCOLS = ["AXI", "AHB", "CHI"]
TOPOLOGIES = ["Mesh", "Ring", "Crossbar"]
GENERATION_DELAY_MS = 400


@dataclass
class NocDesign:
    """Modèle métier, indépendant de Qt (testable unitairement)."""

    name: str = ""
    topology: str = TOPOLOGIES[0]
    clock_mhz: int = 1000
    qos: bool = False
    initiators: list[tuple[str, str]] = field(default_factory=list)
    targets: list[tuple[str, str]] = field(default_factory=list)

    def add_initiator(self, name: str, protocol: str) -> str | None:
        return self._add(self.initiators, name, protocol)

    def add_target(self, name: str, protocol: str) -> str | None:
        return self._add(self.targets, name, protocol)

    def _add(self, bucket: list[tuple[str, str]], name: str, protocol: str) -> str | None:
        name = name.strip()
        if not name:
            return "Error: name is required"
        if any(n == name for n, _ in self.initiators + self.targets):
            return f"Error: '{name}' already exists"
        bucket.append((name, protocol))
        return None

    def validate(self) -> list[str]:
        errors = []
        if not self.name.strip():
            errors.append("project name is required")
        if not self.initiators:
            errors.append("at least one initiator is required")
        if not self.targets:
            errors.append("at least one target is required")
        if self.topology == "Ring" and len(self.initiators) + len(self.targets) < 3:
            errors.append("a ring needs at least 3 endpoints")
        return errors


class NocStudioWindow(QMainWindow):
    generation_finished = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("mainWindow")
        self.setWindowTitle("NoC Config Studio")
        self.design = NocDesign()
        self._valid = False

        root = QWidget(objectName="central")
        layout = QVBoxLayout(root)

        # --- Projet -------------------------------------------------------
        project = QGroupBox("Project", objectName="projectGroup")
        form = QFormLayout(project)
        self.project_name = self._named(QLineEdit(), "projectName", "Project name")
        self.topology = self._named(QComboBox(), "topology", "Topology")
        self.topology.addItems(TOPOLOGIES)
        self.clock = self._named(QSpinBox(), "clockMhz", "Clock (MHz)")
        self.clock.setRange(100, 4000)
        self.clock.setValue(1000)
        self.qos = self._named(QCheckBox("Enable QoS"), "enableQos", "Enable QoS")
        form.addRow("Project name", self.project_name)
        form.addRow("Topology", self.topology)
        form.addRow("Clock (MHz)", self.clock)
        form.addRow("", self.qos)
        layout.addWidget(project)

        # --- Initiateurs / cibles ----------------------------------------
        ports = QHBoxLayout()
        (self.initiator_name, self.initiator_protocol, self.add_initiator_btn,
         self.initiator_list, box) = self._port_box("initiator", "Initiator")
        ports.addWidget(box)
        (self.target_name, self.target_protocol, self.add_target_btn,
         self.target_list, box) = self._port_box("target", "Target")
        ports.addWidget(box)
        layout.addLayout(ports)

        # --- Actions --------------------------------------------------------
        actions = QHBoxLayout()
        self.validate_btn = self._named(QPushButton("Validate"), "validateBtn", "Validate")
        self.generate_btn = self._named(QPushButton("Generate netlist"), "generateBtn", "Generate netlist")
        self.generate_btn.setEnabled(False)
        actions.addWidget(self.validate_btn)
        actions.addWidget(self.generate_btn)
        layout.addLayout(actions)
        self.status = self._named(QLabel("Ready"), "statusLabel", "Status")
        layout.addWidget(self.status)
        self.setCentralWidget(root)

        # --- Câblage --------------------------------------------------------
        self.project_name.textChanged.connect(self._on_project_changed)
        self.topology.currentTextChanged.connect(self._on_project_changed)
        self.clock.valueChanged.connect(self._on_project_changed)
        self.qos.toggled.connect(self._on_project_changed)
        self.add_initiator_btn.clicked.connect(self._add_initiator)
        self.initiator_name.returnPressed.connect(self._add_initiator)  # raccourci clavier
        self.add_target_btn.clicked.connect(self._add_target)
        self.target_name.returnPressed.connect(self._add_target)
        self.validate_btn.clicked.connect(self._validate)
        self.generate_btn.clicked.connect(self._generate)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _named(widget: QWidget, object_name: str, accessible: str) -> QWidget:
        widget.setObjectName(object_name)
        widget.setAccessibleName(accessible)
        return widget

    def _port_box(self, key: str, title: str):
        box = QGroupBox(f"{title}s", objectName=f"{key}Group")
        v = QVBoxLayout(box)
        name = self._named(QLineEdit(), f"{key}Name", f"{title} name")
        proto = self._named(QComboBox(), f"{key}Protocol", f"{title} protocol")
        proto.addItems(PROTOCOLS)
        add = self._named(QPushButton(f"Add {key}"), f"add{title}", f"Add {key}")
        lst = self._named(QListWidget(), f"{key}List", f"{title}s")
        for w in (name, proto, add, lst):
            v.addWidget(w)
        return name, proto, add, lst, box

    def _set_status(self, text: str) -> None:
        self.status.setText(text)

    # ----------------------------------------------------------------- slots
    def _on_project_changed(self, *_):
        self.design.name = self.project_name.text()
        self.design.topology = self.topology.currentText()
        self.design.clock_mhz = self.clock.value()
        self.design.qos = self.qos.isChecked()
        self._invalidate()

    def _invalidate(self):
        self._valid = False
        self.generate_btn.setEnabled(False)

    def _add_initiator(self):
        self._add_port(self.design.add_initiator, self.initiator_name,
                       self.initiator_protocol, self.initiator_list)

    def _add_target(self):
        self._add_port(self.design.add_target, self.target_name,
                       self.target_protocol, self.target_list)

    def _add_port(self, add, name_edit, proto_combo, lst):
        name, proto = name_edit.text().strip(), proto_combo.currentText()
        error = add(name, proto)
        if error:
            self._set_status(error)
            return
        lst.addItem(f"{name} ({proto})")
        name_edit.clear()
        self._invalidate()
        self._set_status(f"Added {name}")

    def _validate(self):
        errors = self.design.validate()
        if errors:
            self._set_status("Error: " + "; ".join(errors))
            self._invalidate()
            return
        self._valid = True
        self.generate_btn.setEnabled(True)
        d = self.design
        self._set_status(f"Valid: {len(d.initiators)} initiators, {len(d.targets)} targets")

    def _generate(self):
        if not self._valid:
            return
        self.generate_btn.setEnabled(False)
        self._set_status("Generating...")
        QTimer.singleShot(GENERATION_DELAY_MS, self._finish_generation)

    def _finish_generation(self):
        filename = f"{self.design.name.strip()}.xml"
        self._set_status(f"Generated {filename}")
        self.generate_btn.setEnabled(True)
        self.generation_finished.emit(filename)


def main() -> None:  # pragma: no cover - lancement manuel
    import sys

    app = QApplication.instance() or QApplication(sys.argv)
    win = NocStudioWindow()
    win.resize(720, 520)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":  # pragma: no cover
    main()
