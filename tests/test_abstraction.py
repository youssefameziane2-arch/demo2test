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
def test_catalog_is_read_from_the_step_library_itself():
    """Le catalogue vient du code de la bibliothèque : impossible qu'ils divergent."""
    from demo2test.catalog import DEFAULT_LIBRARY
    from demo2test.catalog_import import load_step_library

    ids = {s.id for s in load_step_library(DEFAULT_LIBRARY)}
    assert ids == {s.id for s in STEPS}
    assert BY_ID["add_initiator"].signature[1].optional  # « initiatorProtocol:select:protocol? »
    assert BY_ID["status_is"].level == "assertion"


def test_foreign_library_without_metadata_is_usable_by_the_llm(recording):
    """Bibliothèque d'une autre équipe : pas de signature, mais des descriptions."""
    from pathlib import Path

    from demo2test.catalog import DEFAULT_LIBRARY, use_library

    foreign = Path(__file__).resolve().parents[1] / "examples" / "other_team_library"
    try:
        # leur bibliothèque + nos steps génériques (filet de sécurité)
        steps = use_library(foreign, DEFAULT_LIBRARY)
        theirs = [s for s in steps if "source=noc_steps.py" in s.tags]
        assert {s.id for s in theirs} == {"studio_open", "declare_cpu_port", "run_drc"}
        assert all(not s.signature for s in theirs)

        def responder(system, user):
            payload = json.loads(user)
            assert "declare_cpu_port" in {c["id"] for c in payload["candidates"]}
            idx = [a["index"] for a in payload["actions"] if a["widget"] == "initiatorName"]
            return {"steps": [{"id": "declare_cpu_port", "params": {"name": "cpu0", "protocol": "AXI"},
                               "covers": idx, "confidence": 0.8}]}

        result = Pipeline(llm=ScriptedClient(responder)).run(recording("s05_enter_key"))
        call = next(c for c in result.calls if c.step_id == "declare_cpu_port")
        assert call.text == 'I declare the CPU port "cpu0" speaking AXI'
    finally:
        use_library(DEFAULT_LIBRARY)


def test_render_matches_pattern():
    text = BY_ID["create_project"].render(name="soc", topology="Ring", clock=800)
    assert text == 'I create the project "soc" with a Ring topology at 800 MHz'


# --------------------------------------------------------- assertions LLM
def test_llm_checks_are_verified_against_what_was_observed(recording):
    from demo2test.abstraction.assertions import suggest

    rec = recording("s01_happy_path")
    result = Pipeline().run(rec)

    def responder(system, user):
        payload = json.loads(user)
        assert {s["id"] for s in payload["assertion_steps"]} >= {"status_is", "list_count"}
        add = next(s["index"] for s in payload["test"] if "initiator" in s["step"])
        return {"checks": [
            {"after": add, "id": "status_is", "params": {"text": "Added cpu0"}},        # vrai
            {"after": add, "id": "status_is", "params": {"text": "Added cpu9"}},        # inventé
            {"after": add, "id": "list_count", "params": {"list": "Initiators", "count": 1}},
            {"after": add, "id": "click_button", "params": {"button": "Validate"}},   # pas une assertion
            {"after": 99, "id": "status_is", "params": {"text": "x"}},                  # index invalide
        ]}

    checks = suggest(rec, result, "llm", ScriptedClient(responder))
    llm = [(c.step_id, c.params) for c in checks if c.origin == "llm"]
    assert ("status_is", {"text": "Added cpu0"}) in llm
    assert ("list_count", {"list": "Initiators", "count": 1}) in llm
    reasons = " | ".join(r["reason"] for r in result.llm_check_rejections)
    assert "does not match what was observed" in reasons
    assert "not an assertion step" in reasons and "invalid step index" in reasons


def test_llm_check_mode_degrades_to_checkpoints_on_error(recording):
    from demo2test.abstraction.assertions import suggest

    rec = recording("s06_ring_error")
    result = Pipeline().run(rec)

    def boom(system, user):
        raise TimeoutError("ollama not running")

    checks = suggest(rec, result, "llm", ScriptedClient(boom))
    assert checks and all(c.origin == "checkpoint" for c in checks)
    assert "llm error" in result.llm_check_rejections[0]["reason"]


def test_llm_proposal_is_trimmed_not_rejected_when_it_overreaches(recording):
    """Cas réel (démo enregistrée à la main) : la bonne réponse incluait une action de trop."""
    def responder(system, user):
        payload = json.loads(user)
        idx = [a["index"] for a in payload["actions"]]
        return {"steps": [{"id": "add_initiator", "params": {"name": "cpu0", "protocol": "AXI"},
                           "covers": [0] + idx + [999], "confidence": 0.9}]}

    result = Pipeline(llm=ScriptedClient(responder)).run(recording("s05_enter_key"))
    call = next(c for c in result.calls if c.step_id == "add_initiator")
    assert call.source == "llm" and "removed" in call.note
    assert 0 not in call.covered  # l'action déjà rattachée (le projet) n'a pas été volée


def test_abandoned_edit_is_ignored():
    """Cas réel : valeur tapée dans le mauvais champ puis effacée."""
    from pathlib import Path

    from demo2test.abstraction.actions import group_events
    from demo2test.recorder.trace import load_trace

    rec = group_events(load_trace(Path(__file__).resolve().parents[1] / "eval" / "user_traces"
                                  / "u02_ring_fix.jsonl"))
    edits = [a for a in rec.actions if a.widget == "initiatorName" and a.kind == "set"]
    assert [a.value for a in edits] == ["cpu0"]
