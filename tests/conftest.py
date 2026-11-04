import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

import pytest  # noqa: E402

from demo2test.abstraction.actions import group_events  # noqa: E402
from demo2test.recorder.trace import load_trace  # noqa: E402

TRACES = ROOT / "eval" / "traces"


@pytest.fixture
def trace():
    def _load(name: str):
        return load_trace(TRACES / f"{name}.jsonl")
    return _load


@pytest.fixture
def recording(trace):
    def _rec(name: str):
        return group_events(trace(name))
    return _rec
