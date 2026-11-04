import json

import pytest

from demo2test.abstraction.matching import Pipeline, rank_candidates
from demo2test.catalog import BY_ID, STEPS
from demo2test.llm import ScriptedClient


def kinds(rec):
    return [(a.kind, a.widget, a.value) for a in rec.actions]


# ------------------------------------------------------------------ grouping
def test_typing_and_corrections_collapse_into_one_action(recording):
    rec = recording("s03_typo")
    sets = [a for a in rec.actions if a.widget == "initiatorName" and a.kind == "set"]
    # « cpu » tapé puis effacé : la valeur finale seule compte
    assert sets[-1].value == "dsp0"
    assert rec.n_raw_events > 5 * len(rec.actions)


def test_enter_key_becomes_submit_and_field_clear_is_an_effect(recording):
    rec = recording("s05_enter_key")
    i = next(i for i, a in enumerate(rec.actions) if a.kind == "submit")
    assert rec.actions[i - 1].kind == "set" and rec.actions[i - 1].value == "cpu0"
    assert any(e.widget == "initiatorList" for e in rec.actions[i].effects)


def test_hesitations_are_inert(recording):
    rec = recording("s12_hesitation")
    focus = [a.widget for a in rec.actions if a.kind == "focus"]
    assert "targetName" in focus


# ------------------------------------------------------------------ matching
def steps(result):
    return [(c.step_id, c.source) for c in result.calls]


def test_rules_recover_business_steps(recording):
    result = Pipeline(use_retrieval=False).run(recording("s01_happy_path"))
    assert steps(result) == [("create_project", "rule"), ("add_initiator", "rule"),
                             ("add_target", "rule"), ("validate_design", "rule"),
                             ("generate_netlist", "rule")]
    assert result.calls[0].params == {"name": "soc_a", "topology": "Mesh", "clock": 1200}


def test_retrieval_tolerates_noise_that_breaks_rules(recording):
    rec = recording("s04_noise_clicks")
    only_rules = Pipeline(use_retrieval=False).run(rec)
    assert ("add_initiator", "rule") not in steps(only_rules)
    full = Pipeline().run(rec)
    call = next(c for c in full.calls if c.step_id == "add_initiator")
    assert call.source == "retrieval" and call.params == {"name": "cpu0", "protocol": "AXI"}
    assert full.ignored  # les clics parasites sont écartés et listés pour la relecture


def test_generic_fallback_keeps_every_action(recording):
    result = Pipeline(use_rules=False, use_retrieval=False).run(recording("s05_enter_key"))
    assert {c.source for c in result.calls} == {"generic"}
    assert ("press_enter", "generic") in steps(result)


def test_catalog_search_ranks_the_right_step(recording):
    rec = recording("s05_enter_key")
    acts = [a for a in rec.actions if a.widget and a.widget.startswith("initiator")]
    assert rank_candidates(acts)[0][0].id == "add_initiator"


# ----------------------------------------------------------------------- LLM
def _llm_maps_enter_to_add_initiator(system, user):
    payload = json.loads(user)
    idx = [a["index"] for a in payload["actions"] if a["widget"] == "initiatorName"]
    return {"steps": [{"id": "add_initiator", "params": {"name": "cpu0", "protocol": "AXI"},
                       "covers": idx, "confidence": 0.9}]}


def test_llm_closes_the_gap_with_verified_proposal(recording):
    client = ScriptedClient(_llm_maps_enter_to_add_initiator)
    result = Pipeline(llm=client).run(recording("s05_enter_key"))
    call = next(c for c in result.calls if c.step_id == "add_initiator")
    assert call.source == "llm" and call.params["name"] == "cpu0"
    system, user = client.prompts[0]
    assert "add_initiator" in user  # le candidat vient bien de la recherche dans le catalogue (RAG)
    assert not any(c.step_id == "press_enter" for c in result.calls)


@pytest.mark.parametrize("bad, reason", [
    ({"id": "add_initiator", "params": {"name": "cpu9", "protocol": "AXI"}}, "hallucination"),
    ({"id": "delete_everything", "params": {}}, "not a candidate"),
    ({"id": "add_target", "params": {"name": "cpu0", "protocol": "AXI"}}, "unrelated"),
])
def test_unverifiable_llm_proposals_are_rejected(recording, bad, reason):
    def responder(system, user):
        idx = [a["index"] for a in json.loads(user)["actions"] if a["widget"] == "initiatorName"]
        return {"steps": [{**bad, "covers": idx}]}

    result = Pipeline(llm=ScriptedClient(responder)).run(recording("s05_enter_key"))
    assert any(reason in r["reason"] for r in result.llm_rejections)
    # le test reste complet grâce au filet générique
    assert ("press_enter", "generic") in steps(result)


def test_llm_failure_degrades_gracefully(recording):
    def boom(system, user):
        raise TimeoutError("ollama not running")

    result = Pipeline(llm=ScriptedClient(boom)).run(recording("s05_enter_key"))
    assert "llm error" in result.llm_rejections[0]["reason"]
    assert len(result.calls) >= 4


# ------------------------------------------------------------------ catalog
def test_every_catalog_step_is_implemented():
    from demo2test.bdd import steps as library

    assert {s.id for s in STEPS} == library.IMPLEMENTED


def test_render_matches_pattern():
    text = BY_ID["create_project"].render(name="soc", topology="Ring", clock=800)
    assert text == 'I create the project "soc" with a Ring topology at 800 MHz'
