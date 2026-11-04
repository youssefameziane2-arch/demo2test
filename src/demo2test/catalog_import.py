"""Lecture d'un catalogue de steps à partir d'une bibliothèque pytest-bdd existante.

Le catalogue est extrait du **code source** par analyse syntaxique (``ast``), sans
importer ni exécuter la bibliothèque : on peut donc analyser la bibliothèque d'une
autre équipe sans installer ses dépendances.

Pour chaque fonction décorée par ``@given`` / ``@when`` / ``@then`` :

* le motif vient du décorateur (chaîne littérale ou ``parsers.parse("...")``) ;
* la description vient de la première phrase de la docstring ;
* une ligne ``d2t: id=... sig=... kinds=...`` (facultative) apporte les
  métadonnées utiles aux règles. Sans elle, le step reste exploitable par la
  recherche et par le LLM, mais pas par les règles.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from .catalog import SigItem, Step

KEYWORDS = {"given": "Given", "when": "When", "then": "Then"}


def _pattern(call: ast.Call) -> str | None:
    if not call.args:
        return None
    arg = call.args[0]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    if isinstance(arg, ast.Call) and arg.args and isinstance(arg.args[0], ast.Constant):
        return arg.args[0].value  # parsers.parse("...") / parsers.cfparse("...")
    return None


def _parse_meta(doc: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for line in doc.splitlines():
        line = line.strip()
        if not line.startswith("d2t:"):
            continue
        body = line[4:].strip()
        sig = re.search(r"sig=(.*)$", body)
        if sig:
            meta["sig"] = sig.group(1).strip()
            body = body[: sig.start()]
        for key, value in re.findall(r"(\w+)=(\S+)", body):
            meta[key] = value
    return meta


def _signature(spec: str) -> tuple[SigItem, ...]:
    items = []
    for part in filter(None, (p.strip() for p in spec.split(","))):
        fields = part.split(":")
        widget, kind = fields[0], fields[1]
        param = fields[2] if len(fields) > 2 else None
        optional = bool(param and param.endswith("?"))
        items.append(SigItem(widget, kind, param.rstrip("?") if param else None, optional))
    return tuple(items)


def _description(doc: str) -> str:
    first = doc.strip().split("\n\n")[0]
    text = " ".join(line.strip() for line in first.splitlines() if not line.strip().startswith("d2t:"))
    return text.rstrip(".")


def load_step_library(*paths: str | Path) -> list[Step]:
    steps: list[Step] = []
    files = [p for path in paths for p in (sorted(Path(path).rglob("*.py")) if Path(path).is_dir()
                                           else [Path(path)])]
    for file in files:
        tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for deco in node.decorator_list:
                if not (isinstance(deco, ast.Call) and isinstance(deco.func, ast.Name)
                        and deco.func.id in KEYWORDS):
                    continue
                pattern = _pattern(deco)
                if pattern is None:
                    continue
                doc = ast.get_docstring(node) or ""
                meta = _parse_meta(doc)
                keyword = KEYWORDS[deco.func.id]
                signature = _signature(meta["sig"]) if "sig" in meta else ()
                kinds = tuple(meta["kinds"].split("|")) if "kinds" in meta else ()
                if keyword == "Given":
                    level = "context"
                elif keyword == "Then":
                    level = "assertion"
                else:
                    level = "generic" if kinds else "business"
                steps.append(Step(
                    id=meta.get("id") or node.name.lstrip("_"),
                    keyword=keyword, pattern=pattern,
                    description=_description(doc) or node.name.replace("_", " "),
                    level=level, kinds=kinds, signature=signature,
                    tags=(f"source={file.name}",)))
    return steps
