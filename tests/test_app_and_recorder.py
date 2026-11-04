from PySide6.QtCore import Qt

from demo2test.app.noc_studio import NocDesign, NocStudioWindow
from demo2test.recorder.recorder import Recorder
from demo2test.recorder.trace import (
    CHECKPOINT,
    INPUT_CLICK,
    INPUT_KEY,
    STATE_OBSERVED,
    load_trace,
    save_trace,
)


def test_design_rules():
    d = NocDesign(name="soc", topology="Ring")
    assert d.add_initiator("cpu0", "AXI") is None
    assert d.add_target("cpu0", "AXI") == "Error: 'cpu0' already exists"
    assert d.add_target("ddr0", "AXI") is None
    assert d.validate() == ["a ring needs at least 3 endpoints"]


def _window(qtbot):
    w = NocStudioWindow()
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    return w


def test_recorder_captures_inputs_values_and_effects(qtbot, tmp_path):
    w = _window(qtbot)
    rec = Recorder(w)
    rec.start()
    qtbot.mouseClick(w.initiator_name, Qt.LeftButton)
    qtbot.keyClicks(w.initiator_name, "cpu0")
    qtbot.mouseClick(w.add_initiator_btn, Qt.LeftButton)
    qtbot.wait(60)
    events = rec.stop()

    keys = [e for e in events if e.type == INPUT_KEY]
    assert [e.key for e in keys] == list("cpu0")  # pas de doublon dû à la propagation
    assert any(e.type == INPUT_CLICK and e.widget == "addInitiator" for e in events)
    observed = {e.widget: e.value for e in events if e.type == STATE_OBSERVED}
    assert observed["initiatorList"] == ["cpu0 (AXI)"]
    assert observed["statusLabel"] == "Added cpu0"

    path = save_trace(events, tmp_path / "t.jsonl")
    assert [e.type for e in load_trace(path)] == [e.type for e in events]


def test_checkpoint_shortcut_is_consumed(qtbot):
    w = _window(qtbot)
    rec = Recorder(w)
    rec.start()
    qtbot.keyClick(w.project_name, Qt.Key_K, Qt.ControlModifier | Qt.ShiftModifier)
    events = rec.stop()
    assert events[-1].type == CHECKPOINT
    assert events[-1].value["statusLabel"] == "Ready"
    assert w.project_name.text() == ""  # le raccourci n'a pas été tapé dans le champ


def test_asynchronous_effect_is_recorded(qtbot):
    w = _window(qtbot)
    for name in ("project_name", "initiator_name"):
        getattr(w, name).setText("x" + name[0])
    w.add_initiator_btn.click()
    w.target_name.setText("t0")
    w.add_target_btn.click()
    w.validate_btn.click()
    rec = Recorder(w)
    rec.start()
    qtbot.mouseClick(w.generate_btn, Qt.LeftButton)
    qtbot.waitUntil(lambda: w.status.text().startswith("Generated"), timeout=3000)
    qtbot.wait(60)
    statuses = [e.value for e in rec.stop() if e.widget == "statusLabel"]
    assert statuses == ["Generating...", "Generated xp.xml"]
