"""Banc d'évaluation : mesurer l'apport de chaque étage de la chaîne.

    python eval/run_eval.py                       # stratégies sans LLM (reproductible, CI)
    python eval/run_eval.py --llm ollama:qwen2.5:3b --record-llm eval/llm_cache.json
    python eval/run_eval.py --llm replay:eval/llm_cache.json   # rejouer sans GPU

Métriques par stratégie (sur les 12 démonstrations) :
* précision / rappel / F1 des steps ``When`` vs le test écrit à la main ;
* scénarios exactement retrouvés (mêmes steps, même ordre) ;
* taux d'abstraction métier (steps métier attendus effectivement retrouvés) ;
* compression : événements bruts par step généré ;
* **exécutabilité** : le .feature généré passe-t-il réellement contre l'application ?
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

from scenarios import SCENARIOS  # noqa: E402

from demo2test.catalog import BY_ID  # noqa: E402
from demo2test.cli import make_pipeline, run_features  # noqa: E402
from demo2test.gherkin import generate, write_outputs  # noqa: E402
from demo2test.recorder.trace import load_trace, save_trace  # noqa: E402

TRACES = HERE / "traces"
BASE_STRATEGIES = ["generic", "rules", "rules+retrieval"]


def ensure_traces(rerecord: bool) -> None:
    from demo2test.player import record

    TRACES.mkdir(exist_ok=True)
    for scn in SCENARIOS:
        path = TRACES / f"{scn.name}.jsonl"
        if rerecord or not path.exists():
            save_trace(record(scn.play), path)


def _key(step_id: str, params: dict) -> tuple:
    return (step_id, tuple(sorted((k, str(v)) for k, v in params.items())))


def score(expected: list[tuple[str, dict]], calls) -> dict:
    exp = [_key(i, p) for i, p in expected]
    got = [_key(c.step_id, c.params) for c in calls]
    inter = sum((Counter(exp) & Counter(got)).values())
    business_exp = [k for k in exp if BY_ID[k[0]].level == "business"]
    business_hit = sum((Counter(business_exp) & Counter(got)).values())
    return {"tp": inter, "n_exp": len(exp), "n_got": len(got), "exact": exp == got,
            "business_exp": len(business_exp), "business_hit": business_hit}


def junit_results(path: Path) -> dict[str, bool]:
    results = {}
    if not path.exists():
        return results
    for case in ET.parse(path).getroot().iter("testcase"):
        failed = any(child.tag in ("failure", "error") for child in case)
        results[case.get("name", "")] = not failed
    return results


def evaluate(strategy: str, llm_spec: str | None, record_llm: str | None, out: Path) -> dict:
    pipeline = make_pipeline(strategy, llm_spec, record_llm)
    folder = out / strategy.replace("+", "_")
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("*.feature"):
        old.unlink()
    rows, t0 = [], time.perf_counter()
    for scn in SCENARIOS:
        events = load_trace(TRACES / f"{scn.name}.jsonl")
        gen = generate(events, scn.name, pipeline, "key", f"{scn.name}.jsonl")
        write_outputs(gen, folder, scn.name)
        row = score(scn.expected, gen.result.calls)
        row.update(name=scn.name, difficulty=scn.difficulty, raw=len(events),
                   steps=len(gen.result.calls), checks=len(gen.assertions),
                   llm_calls=gen.result.llm_calls, llm_rejections=len(gen.result.llm_rejections),
                   sources=gen.report["steps_by_source"])
        rows.append(row)
    gen_time = time.perf_counter() - t0
    junit = folder / "junit.xml"
    run_features(folder, junit)
    passed = junit_results(junit)
    for row in rows:
        row["executes"] = any(ok for name, ok in passed.items() if row["name"] in name)
    tp = sum(r["tp"] for r in rows)
    prec = tp / max(1, sum(r["n_got"] for r in rows))
    rec = tp / max(1, sum(r["n_exp"] for r in rows))
    return {
        "strategy": pipeline.name if strategy != "generic" else "generic",
        "precision": prec, "recall": rec,
        "f1": 2 * prec * rec / (prec + rec) if prec + rec else 0.0,
        "exact": sum(r["exact"] for r in rows) / len(rows),
        "business": sum(r["business_hit"] for r in rows) / max(1, sum(r["business_exp"] for r in rows)),
        "compression": sum(r["raw"] for r in rows) / max(1, sum(r["steps"] for r in rows)),
        "executes": sum(r["executes"] for r in rows) / len(rows),
        "llm_calls": sum(r["llm_calls"] for r in rows),
        "llm_rejections": sum(r["llm_rejections"] for r in rows),
        "gen_seconds": round(gen_time, 2),
        "rows": rows,
    }


def to_markdown(results: list[dict]) -> str:
    pct = lambda x: f"{100 * x:.0f} %"  # noqa: E731
    lines = [
        "# Résultats du banc d'évaluation",
        "",
        f"{len(SCENARIOS)} démonstrations enregistrées sur l'application réelle "
        "(`eval/traces/`), comparées au test qu'un ingénieur QA écrirait à la main.",
        "",
        "| Stratégie | Précision | Rappel | F1 | Scénarios exacts | Steps métier retrouvés "
        "| Événements / step | Tests exécutables | Appels LLM (rejets) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| `{r['strategy']}` | {pct(r['precision'])} | {pct(r['recall'])} | {pct(r['f1'])} "
            f"| {pct(r['exact'])} | {pct(r['business'])} | {r['compression']:.1f} "
            f"| {pct(r['executes'])} | {r['llm_calls']} ({r['llm_rejections']}) |")
    lines += ["", "## Détail par scénario", "",
              "| Scénario | Difficulté | " + " | ".join(f"`{r['strategy']}`" for r in results) + " |",
              "|---|---|" + "---|" * len(results)]
    for i, scn in enumerate(SCENARIOS):
        cells = []
        for r in results:
            row = r["rows"][i]
            mark = "exact" if row["exact"] else f"{row['tp']}/{row['n_exp']}"
            cells.append(mark + ("" if row["executes"] else " (KO)"))
        lines.append(f"| {scn.name} | {scn.difficulty} | " + " | ".join(cells) + " |")
    lines += ["", "*exact* = steps identiques au test manuel, dans le même ordre ; "
              "*x/y* = steps attendus retrouvés ; *(KO)* = le test généré échoue à l'exécution.", ""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", help="ollama:<model> | openai:<model> | replay:<file>")
    ap.add_argument("--record-llm")
    ap.add_argument("--rerecord", action="store_true", help="re-record the demonstrations")
    ap.add_argument("--out", default=str(HERE / "out"))
    args = ap.parse_args()
    ensure_traces(args.rerecord)
    strategies = list(BASE_STRATEGIES)
    if args.llm:
        strategies += ["rules+llm", "rules+retrieval+llm"]
    results = [evaluate(s, args.llm, args.record_llm, Path(args.out)) for s in strategies]
    md = to_markdown(results)
    suffix = "_llm" if args.llm else ""
    (HERE / f"RESULTS{suffix}.md").write_text(md, encoding="utf-8")
    (HERE / f"results{suffix}.json").write_text(json.dumps(results, indent=1, default=str))
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
