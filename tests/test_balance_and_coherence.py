"""Simulator (playtest.py) and coherence gate on the new rules, plus the full gate pipeline."""
import copy
import importlib.util
import json
import os

import playtest as P
import story_engine as E

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = os.path.join(ROOT, "cyoa-skills", "cyoa-generator", "references", "sample_story.json")


def _load_coherence():
    spec = importlib.util.spec_from_file_location("coherence_report", E.COHERENCE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


C = _load_coherence()


def _story(locs, hp=10, difficulty="normal"):
    return {"difficulty": difficulty, "character_template": {"health": hp},
            "start_location_id": "start", "locations": locs}


WIN = {"description": "won", "is_end": True, "is_victory": True, "choices": []}
BAD = {"description": "lost", "is_end": True, "is_victory": False, "choices": []}


# ── simulator ────────────────────────────────────────────────────────────────
def test_failed_check_still_gets_through():
    s = _story({"start": {"description": "x", "choices": [
        {"text": "jump", "target_id": "win",
         "condition": {"attribute": "agility", "check_value": 99, "fail_damage": 3}}]},
        "win": WIN})
    m = P.simulate(s, 300, seed=1)
    assert m["cautious"]["win"] == 100 and m["heroic"]["death"] == 0


def test_damage_can_still_kill():
    s = _story({"start": {"description": "x", "choices": [
        {"text": "jump", "target_id": "win",
         "condition": {"attribute": "agility", "check_value": 99, "fail_damage": 10}}]},
        "win": WIN}, hp=10)
    assert P.simulate(s, 300, seed=1)["cautious"]["death"] == 100


def test_monster_is_one_roll_then_onward():
    s = _story({"start": {"description": "x", "monster": {"name": "m", "strength": 99, "fail_damage": 2},
                          "choices": [{"text": "on", "target_id": "win"}]},
                "win": WIN})
    m = P.simulate(s, 300, seed=1)
    assert m["heroic"]["win"] == 100 and m["heroic"]["loop"] == 0


def test_careful_player_heeds_trap_hints():
    s = _story({"start": {"description": "The ice groans underfoot.", "choices": [
                    {"text": "Cross the ice", "target_id": "t1", "trap_hint": "The ice groans"},
                    {"text": "Take the bridge", "target_id": "win"}]},
                "t1": {"description": "x", "choices": [{"text": "on", "target_id": "bad"}]},
                "win": WIN, "bad": BAD})
    m = P.simulate(s, 600, seed=1)
    assert m["cautious"]["badend"] == 0 and m["random"]["badend"] > 0


# ── coherence: challenge texts + dead ends ───────────────────────────────────
def _trap_tags(story):
    reach = C._reach_from(story["locations"], [story["start_location_id"]])
    return [tag for tag, _ in C.trap_issues(story, {n: 0 for n in reach})[0]]


def _normal_with_trap(hint="The ice groans"):
    return _story({
        "start": {"description": "The ice groans underfoot. A bridge spans the gorge.", "choices": [
            {"text": "Cross the ice", "target_id": "t1", "trap_hint": hint},
            {"text": "Take the bridge", "target_id": "win"}]},
        "t1": {"description": "Cracks race ahead of you.", "choices": [{"text": "run", "target_id": "t2"}]},
        "t2": {"description": "The ice gives way.", "choices": [{"text": "sink", "target_id": "bad"}]},
        "win": WIN, "bad": BAD})


def test_valid_hinted_dead_end_passes():
    assert _trap_tags(_normal_with_trap()) == []


def test_missing_hint_wrong_count_and_easy_are_flagged():
    assert _trap_tags(_normal_with_trap(hint="the wolves howl")) == ["traps"]   # hint not in text
    no_trap = _normal_with_trap()
    no_trap["locations"]["start"]["choices"][0].pop("trap_hint")
    assert "traps" in _trap_tags(no_trap)                                      # untagged + count 0
    easy = _normal_with_trap()
    easy["difficulty"] = "easy"
    assert "traps" in _trap_tags(easy)


def test_outcome_texts_and_retired_fail_target_are_flagged():
    s = _story({"start": {"description": "x", "monster": {"name": "m", "strength": 9, "fail_damage": 4},
                          "choices": [{"text": "jump", "target_id": "win",
                                       "condition": {"attribute": "agility", "check_value": 9,
                                                     "fail_target": "win"}}]},
                "win": WIN})
    tags = [t for t, _ in C.challenge_issues(s)[0]]
    assert "outcome" in tags and "rules" in tags


# ── the reference sample passes every gate (the in-app pipeline's gate_report) ─
def test_sample_story_passes_all_gates(monkeypatch):
    monkeypatch.setenv("QUEST_PLAYTEST_N", "3000")
    ok, feedback, summary = E.gate_report(SAMPLE, "easy")
    assert ok, feedback
    issues, _ = C.analyze(json.load(open(SAMPLE, encoding="utf-8")))
    assert issues == []
