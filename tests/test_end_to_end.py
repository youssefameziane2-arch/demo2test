"""De bout en bout : démonstration live -> trace -> Gherkin -> exécution réelle."""
import pytest
from scenarios import SCENARIOS

from demo2test.abstraction.matching import Pipeline
from demo2test.cli import run_features
from demo2test.gherkin import generate, write_outputs
from demo2test.player import record


def test_live_demo_becomes_a_passing_test(qtbot, tmp_path):
    scenario = next(s for s in SCENARIOS if s.name == "s01_happy_path")
    events = record(scenario.play)
    gen = generate(events, "Configure and generate a NoC", Pipeline())
    feature, _ = write_outputs(gen, tmp_path, "Configure and generate a NoC")

    text = feature.read_text()
    assert 'When I create the project "soc_a" with a Mesh topology at 1200 MHz' in text
    assert 'Then the status shows "Generated soc_a.xml"' in text  # effet asynchrone vérifié
    assert run_features(tmp_path) == 0


def test_generated_test_detects_a_regression(tmp_path, monkeypatch):
    """Le test généré n'est pas décoratif : il échoue si le comportement change."""
    scenario = next(s for s in SCENARIOS if s.name == "s06_ring_error")
    gen = generate(record(scenario.play), "Ring rule", Pipeline())
    feature, _ = write_outputs(gen, tmp_path, "Ring rule")
    feature.write_text(feature.read_text().replace("a ring needs at least 3 endpoints",
                                                   "a ring needs at least 4 endpoints"))
    assert run_features(tmp_path) != 0


@pytest.mark.parametrize("strategy, min_f1", [("rules", 0.85), ("rules+retrieval", 0.9)])
def test_quality_does_not_regress(recording, strategy, min_f1):
    from collections import Counter

    from run_eval import _key  # type: ignore

    pipe = Pipeline(use_retrieval="retrieval" in strategy)
    tp = got = exp = 0
    for scn in SCENARIOS:
        calls = pipe.run(recording(scn.name)).calls
        e = Counter(_key(i, p) for i, p in scn.expected)
        g = Counter(_key(c.step_id, c.params) for c in calls)
        tp += sum((e & g).values())
        got += sum(g.values())
        exp += sum(e.values())
    p, r = tp / got, tp / exp
    assert 2 * p * r / (p + r) >= min_f1
