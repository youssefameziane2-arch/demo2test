"""Interface en ligne de commande.

    demo2test record  demo.jsonl            # ouvre l'application et enregistre (Ctrl+Maj+K = checkpoint)
    demo2test generate demo.jsonl -n "Add a CPU" [--llm ollama:qwen2.5:3b]
    demo2test run features/                 # exécute les scénarios générés
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from .abstraction.matching import Pipeline
from .gherkin import generate, write_outputs
from .llm import make_client
from .recorder.trace import load_trace, save_trace

RUNNER_TEST = 'from pytest_bdd import scenarios\n\nscenarios(".")\n'
RUNNER_CONFTEST = 'pytest_plugins = ["demo2test.bdd.steps"]\n'


def make_pipeline(strategy: str, llm_spec: str | None, record_llm: str | None = None) -> Pipeline:
    parts = set(strategy.split("+"))
    return Pipeline(use_rules="rules" in parts, use_retrieval="retrieval" in parts,
                    llm=make_client(llm_spec, record_llm) if "llm" in parts else None)


def cmd_record(args) -> int:
    from PySide6.QtWidgets import QApplication

    from .app.noc_studio import NocStudioWindow
    from .recorder.recorder import Recorder

    app = QApplication.instance() or QApplication(sys.argv)
    window = NocStudioWindow()
    window.setWindowTitle("NoC Config Studio  [REC - close the window to stop, Ctrl+Shift+K = checkpoint]")
    window.resize(720, 520)
    recorder = Recorder(window)
    window.show()
    recorder.start()
    app.exec()
    path = save_trace(recorder.stop(), args.trace)
    print(f"{len(recorder.events)} events saved to {path}")
    return 0


def cmd_generate(args) -> int:
    strategy = args.strategy or ("rules+retrieval+llm" if args.llm else "rules+retrieval")
    pipeline = make_pipeline(strategy, args.llm, args.record_llm)
    events = load_trace(args.trace)
    gen = generate(events, args.name, pipeline, args.assertions, Path(args.trace).name)
    feature, report = write_outputs(gen, args.out, args.name)
    print(gen.feature)
    print(f"-> {feature}\n-> {report} (review report)")
    return 0


def prepare_runner(folder: Path) -> None:
    (folder / "test_generated_features.py").write_text(RUNNER_TEST)
    (folder / "conftest.py").write_text(RUNNER_CONFTEST)


def run_features(folder: str | Path, junit: str | Path | None = None, quiet: bool = True) -> int:
    folder = Path(folder).resolve()
    prepare_runner(folder)
    env = {**os.environ, "QT_QPA_PLATFORM": os.environ.get("QT_QPA_PLATFORM", "offscreen")}
    cmd = [sys.executable, "-m", "pytest", str(folder), "-p", "no:cacheprovider",
           "-q" if quiet else "-v", "--rootdir", str(folder)]
    if junit:
        cmd += ["--junitxml", str(junit)]
    return subprocess.call(cmd, env=env, cwd=folder,
                           stdout=subprocess.DEVNULL if quiet else None)


def cmd_run(args) -> int:
    return run_features(args.folder, quiet=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="demo2test", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("record", help="record a live demonstration")
    p.add_argument("trace")
    p.set_defaults(func=cmd_record)

    p = sub.add_parser("generate", help="turn a trace into a Gherkin scenario")
    p.add_argument("trace")
    p.add_argument("-n", "--name", default="Recorded scenario")
    p.add_argument("-o", "--out", default="features")
    p.add_argument("--strategy", help="generic | rules | rules+retrieval | rules+retrieval+llm ...")
    p.add_argument("--llm", help="ollama:<model> | openai:<model> | replay:<file.json>")
    p.add_argument("--record-llm", help="save LLM answers to this file for later replay")
    p.add_argument("--assertions", choices=["none", "key", "all"], default="key")
    p.set_defaults(func=cmd_generate)

    p = sub.add_parser("run", help="execute generated .feature files")
    p.add_argument("folder")
    p.set_defaults(func=cmd_run)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
