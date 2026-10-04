"""game_rules.py — the shared challenge mechanics (one roll, fail-forward, outcome texts)."""
import random

import game_rules as R

ATTRS = {"strength": 7, "agility": 5, "stamina": 9}


def test_check_success_and_failure_damage_and_texts():
    cond = {"attribute": "strength", "check_value": 10, "fail_damage": 5,
            "success_text": "The door bursts open.", "fail_text": "Your shoulder takes the blow."}
    ok = R.resolve_check(cond, ATTRS, roll=3)               # 3 + 7 = 10 ≥ 10
    bad = R.resolve_check(cond, ATTRS, roll=2)              # 9 < 10
    assert ok["passed"] and ok["damage"] == 0 and ok["text"] == "The door bursts open."
    assert not bad["passed"] and bad["damage"] == 5 and bad["text"] == "Your shoulder takes the blow."


def test_default_texts_and_damage_for_old_stories():
    bad = R.resolve_check({"attribute": "agility", "check_value": 99}, ATTRS, roll=6)
    assert bad["damage"] == R.DEFAULT_CHECK_DAMAGE and bad["text"] == R.DEFAULT_TEXTS["check"][1]
    m = R.resolve_monster({"name": "Ghoul", "strength": 99}, ATTRS, roll=6)
    assert m["damage"] == R.DEFAULT_MONSTER_DAMAGE and "Ghoul" in m["text"]


def test_item_bonus_counts_only_when_held():
    cond = {"attribute": "agility", "check_value": 10, "item_bonus": {"item": "charm", "bonus": 3}}
    assert not R.resolve_check(cond, ATTRS, inventory=[], roll=4)["passed"]          # 4+5 = 9
    assert R.resolve_check(cond, ATTRS, inventory=["charm"], roll=4)["passed"]       # 4+5+3 = 12


def test_failure_moves_forward_but_legacy_fail_target_is_honoured():
    new = {"target_id": "far_side", "condition": {"attribute": "agility", "check_value": 9}}
    old = {"target_id": "far_side", "condition": {"attribute": "agility", "check_value": 9,
                                                   "fail_target": "pit"}}
    assert R.check_destination(new, passed=False) == ("far_side", False)
    assert R.check_destination(old, passed=False) == ("pit", True)
    assert R.check_destination(old, passed=True) == ("far_side", False)


def test_monster_is_one_roll():
    m = {"name": "Bone Sentinel", "strength": 9, "fail_damage": 6, "attribute": "stamina",
         "success_text": "It shatters.", "fail_text": "A fist cracks your ribs as you shove past."}
    assert R.resolve_monster(m, ATTRS, roll=1)["passed"]                              # 1+9 ≥ 9
    lost = R.resolve_monster({**m, "attribute": "agility"}, ATTRS, roll=1)             # 1+5 < 9
    assert not lost["passed"] and lost["damage"] == 6 and "ribs" in lost["text"]


def test_odds_and_random_rolls():
    assert R.pass_probability("1d6", 4) == 0.5
    assert R.pass_probability("2d6", 13) == 0.0
    rng = random.Random(1)
    assert all(1 <= R.roll_dice("1d6", rng) <= 6 for _ in range(200))


def test_trap_band():
    assert R.trap_band("easy", 30) == (0, 0)
    assert R.trap_band("normal", 14) == (1, 1) and R.trap_band("normal", 15) == (1, 2)
    assert R.trap_band("hard", 12) == (2, 2) and R.trap_band("hard", 17) == (2, 3)
    assert R.trap_band("hard", 30) == (2, 4)
