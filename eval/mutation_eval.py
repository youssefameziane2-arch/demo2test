"""Banc de mutation : les vérifications générées détectent-elles de vraies régressions ?

Pour chaque façon de produire les vérifications (aucune, règles, LLM, règles + LLM),
on génère les 12 scénarios puis on les exécute :

* contre l'application **intacte** : tout doit passer (sinon = fausse alerte) ;
* contre chacun des **mutants** (``demo2test/bdd/mutants.py``), qui injectent une
  régression réaliste : un mutant est *tué* si au moins un scénario échoue.

    python eval/mutation_eval.py                                  # sans LLM
    python eval/mutation_eval.py --llm ollama:qwen2.5:3b --record-llm eval/llm_cache.json
    python eval/mutation_eval.py --llm replay:eval/llm_cache.json  # rejeu (CI)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

from run_eval import ensure_traces  # noqa: E402
from scenarios import SCENARIOS  # noqa: E402

from demo2test.bdd.mutants import MUTANTS  # noqa: E402
from demo2test.cli import make_pipeline, run_features  # noqa: E402
from demo2test.gherkin import generate, write_outputs  # noqa: E402
from demo2test.llm import make_client  # noqa: E402
from demo2test.recorder.trace import load_trace  # noqa: E402

TRACES = HERE / "traces"
WAIT_MS = "2000"


def failures(junit: Path) -> set[str]:
    if not junit.exists():
        return {"<no report>"}
    return {c.get("name", "") for c in ET.parse(junit).getroot().iter("testcase")
            if any(ch.tag in ("failure", "error") for ch in c)}


def run_mode(mode: str, llm_spec: str | None, record: str | None, out: Path) -> dict:
    strategy = "rules+retrieval+llm" if llm_spec else "rules+retrieval"
    pipeline = make_pipeline(strategy, llm_spec, record)
    checks_llm = make_client(llm_spec, record) if (llm_spec and "llm" in mode) else None
    folder = out / f"mut_{mode.replace('+', '_')}"
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("*.feature"):
        old.unlink()
    n_checks, rejected = 0, 0
    for scn in SCENARIOS:
        gen = generate(load_trace(TRACES / f"{scn.name}.jsonl"), scn.name, pipeline, mode,
                       f"{scn.name}.jsonl", llm=checks_llm)
        write_outputs(gen, folder, scn.name)
        n_checks += len(gen.assertions)
        rejected += len(gen.result.llm_check_rejections)
    t0 = time.perf_counter()
    base = folder / "junit_original.xml"
    run_features(folder, base, extra_env={"D2T_WAIT_MS": WAIT_MS})
    false_alarms = sorted(failures(base))
    killed = {}
    for name in MUTANTS:
        junit = folder / f"junit_{name}.xml"
        run_features(folder, junit, extra_env={"D2T_WAIT_MS": WAIT_MS, "D2T_MUTANT": name})
        # Seuls les scénarios fiables (qui passent sur l'application intacte) comptent :
        # un test qui échoue toujours « tuerait » tous les mutants sans rien prouver.
        killed[name] = sorted(failures(junit) - set(false_alarms))
    return {"mode": mode, "checks": n_checks, "llm_rejected": rejected,
            "false_alarms": false_alarms, "killed": killed,
            "score": sum(bool(v) for v in killed.values()) / len(MUTANTS),
            "seconds": round(time.perf_counter() - t0, 1)}


def to_markdown(results: list[dict]) -> str:
    lines = [
        "# Banc de mutation",
        "",
        f"Les 12 scénarios générés sont exécutés contre l'application intacte puis contre "
        f"{len(MUTANTS)} versions défectueuses. Un mutant est **tué** si au moins un test échoue.",
        "",
        "| Vérifications | Nombre de checks | Fausses alertes | Mutants tués | Score de mutation |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        rej = f" ({r['llm_rejected']} rejetés)" if r["llm_rejected"] else ""
        lines.append(f"| `{r['mode']}` | {r['checks']}{rej} | {len(r['false_alarms'])} | "
                     f"{sum(bool(v) for v in r['killed'].values())}/{len(MUTANTS)} | "
                     f"**{100 * r['score']:.0f} %** |")
    lines += ["", "## Détail par mutant", "",
              "| Mutant (régression injectée) | " + " | ".join(f"`{r['mode']}`" for r in results) + " |",
              "|---|" + "---|" * len(results)]
    for name, (*_, desc) in MUTANTS.items():
        cells = ["tué" if r["killed"][name] else "**survit**" for r in results]
        lines.append(f"| {desc} | " + " | ".join(cells) + " |")
    lines += ["", "*Fausses alertes* : scénarios qui échouent contre l'application intacte "
              "(une vérification incorrecte). Ces scénarios sont exclus du calcul des mutants "
              "tués : un test qui échoue toujours détecterait toutes les régressions sans rien "
              "prouver.", ""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm")
    ap.add_argument("--record-llm")
    ap.add_argument("--out", default=str(HERE / "out"))
    args = ap.parse_args()
    ensure_traces(False)
    modes = ["none", "key"] + (["llm-unverified", "llm", "key+llm"] if args.llm else [])
    results = [run_mode(m, args.llm, args.record_llm, Path(args.out)) for m in modes]
    suffix = "_llm" if args.llm else ""
    md = to_markdown(results)
    (HERE / f"MUTATION{suffix}.md").write_text(md, encoding="utf-8")
    (HERE / f"mutation{suffix}.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
