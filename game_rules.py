"""
game_rules.py — the single source of truth for Quest Book's challenge mechanics.

Used by app.py (the game) AND playtest.py (the balance simulator), so the two can never drift
apart. Streamlit-free and deterministic when a roll is passed in, so it's unit-testable.

Rules
-----
* A challenge is an attribute **check** on a choice, or a **monster** in a location. Each is
  resolved by ONE roll:   roll(dice) + attribute (+ item bonus) >= DC.
* **Success** — the hero gets through cleanly; `success_text` describes how.
* **Failure** — the hero STILL gets through, but takes `fail_damage` HP; `fail_text` describes
  the (realistic, approach-specific) injury. Nothing ever blocks or loops; a run only ends early
  when HP reaches 0.
* A monster encounter is a single roll too; win or lose, the encounter is over and the
  location's onward choices open up. `is_flee` choices are alternative approaches (sneak past,
  outrun, ...) that lead somewhere else, with their own check and outcome texts.
* **Dead ends ("traps")**: a choice carrying `trap_hint` leads into an inescapable branch that is
  played out over 2+ locations before a non-victory ending. The hint phrase must appear in the
  scene text so a careful reader can avoid it. How many per story: see `trap_band()`.
* **Legacy**: older stories may still route a failed check to `fail_target`; that is honoured
  so they keep working until regenerated. New stories must not use it.
"""
import random
from functools import lru_cache

ATTRIBUTES = ("strength", "agility", "stamina")
DEFAULT_DICE = "1d6"
DEFAULT_CHECK_DAMAGE = 2
DEFAULT_MONSTER_DAMAGE = 4

DEFAULT_TEXTS = {
    "check":   ("You make it through.", "You get through — but it costs you."),
    "monster": ("You overcome {name} and press on.", "You get past {name}, but not unscathed."),
}


# ── dice ──────────────────────────────────────────────────────────────────────
def parse_dice(dice):
    try:
        n, s = (int(x) for x in str(dice or DEFAULT_DICE).lower().split("d"))
        if n > 0 and s > 0:
            return n, s
    except ValueError:
        pass
    return 1, 6


def roll_dice(dice=DEFAULT_DICE, rng=random):
    n, s = parse_dice(dice)
    return sum(rng.randint(1, s) for _ in range(n))


@lru_cache(maxsize=None)
def _dice_totals(dice):
    n, s = parse_dice(dice)
    totals = [0]
    for _ in range(n):
        totals = [t + f for t in totals for f in range(1, s + 1)]
    return tuple(totals)


def pass_probability(dice, need):
    """P(roll(dice) >= need), where need = DC - attribute - bonus."""
    totals = _dice_totals(dice or DEFAULT_DICE)
    return sum(1 for t in totals if t >= need) / len(totals)


def min_roll(dice):
    n, _ = parse_dice(dice)
    return n


def max_roll(dice):
    n, s = parse_dice(dice)
    return n * s


# ── helpers ───────────────────────────────────────────────────────────────────
def as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def item_bonus(cond, inventory=()):
    """(bonus, item_id) if the player holds the condition's bonus item, else (0, None)."""
    ib = (cond or {}).get("item_bonus") or {}
    if ib.get("item") and ib["item"] in (inventory or ()):
        return int(ib.get("bonus", 0) or 0), ib["item"]
    return 0, None


def check_odds(cond, attributes, inventory=()):
    bonus, _ = item_bonus(cond, inventory)
    a = (attributes or {}).get(cond.get("attribute", "strength"), 0)
    return pass_probability(cond.get("dice_type", DEFAULT_DICE), cond.get("check_value", 0) - a - bonus)


def monster_odds(monster, attributes):
    a = (attributes or {}).get(monster.get("attribute", "strength"), 0)
    return pass_probability(monster.get("dice_type", DEFAULT_DICE), monster.get("strength", 0) - a)


def check_is_sure(cond, attributes, inventory=()):
    """True when the hero passes even with the lowest possible roll — no dice needed."""
    bonus, _ = item_bonus(cond, inventory)
    a = (attributes or {}).get(cond.get("attribute", "strength"), 0)
    return min_roll(cond.get("dice_type", DEFAULT_DICE)) + a + bonus >= cond.get("check_value", 0)


def monster_is_sure(monster, attributes):
    a = (attributes or {}).get(monster.get("attribute", "strength"), 0)
    return min_roll(monster.get("dice_type", DEFAULT_DICE)) + a >= monster.get("strength", 0)


def legacy_fail_target(choice):
    """Old stories only: where a failed check used to send the hero (None for new stories)."""
    return choice.get("fail_target") or (choice.get("condition") or {}).get("fail_target")


def is_trap(choice):
    return bool(str(choice.get("trap_hint") or "").strip())


# ── resolution ────────────────────────────────────────────────────────────────
def _text(spec, passed, kind, name=""):
    t = (spec.get("success_text") if passed else spec.get("fail_text")) or ""
    t = t.strip()
    if not t:
        t = DEFAULT_TEXTS[kind][0 if passed else 1]
    return t.replace("{name}", name or "the enemy")


def resolve_check(cond, attributes, inventory=(), roll=None, rng=random):
    """Resolve one attribute check. Returns a result dict; the caller applies the damage and
    moves the hero (see check_destination)."""
    dice = cond.get("dice_type", DEFAULT_DICE)
    attr = cond.get("attribute", "strength")
    a = (attributes or {}).get(attr, 0)
    bonus, bitem = item_bonus(cond, inventory)
    auto = check_is_sure(cond, attributes, inventory)    # strong enough: no roll at all
    r = roll if roll is not None else (min_roll(dice) if auto else roll_dice(dice, rng))
    total = r + a + bonus
    dc = cond.get("check_value", 0)
    passed = total >= dc
    return {
        "kind": "check", "passed": passed, "roll": r, "dice": dice, "auto": auto,
        "attribute": attr, "attr_value": a, "bonus": bonus, "bonus_item": bitem,
        "total": total, "dc": dc,
        "damage": 0 if passed else int(cond.get("fail_damage", DEFAULT_CHECK_DAMAGE) or 0),
        "text": _text(cond, passed, "check"),
    }


def check_destination(choice, passed):
    """Where the hero goes after a check: always onward to target_id, except legacy stories
    that still route failures to fail_target."""
    if not passed:
        ft = legacy_fail_target(choice)
        if ft:
            return ft, True
    return choice.get("target_id"), False


def resolve_monster(monster, attributes, roll=None, rng=random):
    """Resolve a whole monster encounter with one roll. Win or lose, the encounter ends."""
    dice = monster.get("dice_type", DEFAULT_DICE)
    attr = monster.get("attribute", "strength")
    a = (attributes or {}).get(attr, 0)
    auto = monster_is_sure(monster, attributes)
    r = roll if roll is not None else (min_roll(dice) if auto else roll_dice(dice, rng))
    total = r + a
    dc = monster.get("strength", 0)
    passed = total >= dc
    return {
        "kind": "monster", "passed": passed, "roll": r, "dice": dice, "auto": auto,
        "attribute": attr, "attr_value": a, "bonus": 0, "bonus_item": None,
        "total": total, "dc": dc, "name": monster.get("name", ""),
        "damage": 0 if passed else int(monster.get("fail_damage", DEFAULT_MONSTER_DAMAGE) or 0),
        "text": _text(monster, passed, "monster", monster.get("name", "")),
    }


# ── dead ends per difficulty ──────────────────────────────────────────────────
def trap_band(difficulty, n_locations):
    """(min, max) hinted dead-end branches a story should contain.
    easy: none (and the game offers Go Back) · normal: 1, or 1–2 above ~14 locations ·
    hard: 2–4, growing with length."""
    d = (difficulty or "normal").lower()
    n = int(n_locations or 0)
    if d == "easy":
        return 0, 0
    if d == "hard":
        return 2, min(4, 2 + max(0, n - 12) // 5)
    return (1, 1) if n <= 14 else (1, 2)
