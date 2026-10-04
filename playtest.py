#!/usr/bin/env python3
"""
playtest.py — Monte-Carlo balance harness for Quest Book.

Plays a story thousands of times with three player types and checks the results against the
target band for its difficulty. Challenges are resolved by game_rules.py — the SAME code the
game uses — so the simulation can't drift from the real rules:
  * every check / monster is one roll; failing still gets you through, but costs HP;
  * a run is lost by dying (HP 0) or by walking into a non-victory ending (e.g. a trap).

Player types
  random   — clicks anything.
  cautious — careful reader: heeds trap hints, avoids doom endings, minimises expected damage,
             heals when low.            → "cautious win %"  (should be high)
  heroic   — commits to danger: always fights, prefers risky checks, ignores hints.
                                        → "heroic death %"  (the stakes)

usage:  python3 playtest.py stories/<story>.json [easy|normal|hard]
import: analyze(story, difficulty, n) → {"metrics", "verdict", "flags", ...}
QUEST_PLAYTEST_N overrides the number of runs per player type (default 20000).
"""
import json
import os
import random
import sys
from collections import defaultdict, deque

import game_rules as R

# expected (cautious win %, heroic death %) bands per difficulty tier
BANDS = {
    "easy":   {"cautious_win": (93, 100), "heroic_death": (0, 12)},
    "normal": {"cautious_win": (85, 99),  "heroic_death": (12, 35)},
    "hard":   {"cautious_win": (60, 88),  "heroic_death": (30, 75)},
}
ATTRS = list(R.ATTRIBUTES)


def _bad_end(locs, t):
    """A deliberately-signposted non-victory ending — a reading player avoids it."""
    L = locs.get(t, {})
    return bool(L.get("is_end")) and not L.get("is_victory", True)


def _available(L, inv, encounter):
    """Choices the player can click: alternatives during an encounter, onward choices after."""
    out = []
    for c in L.get("choices", []):
        if bool(c.get("is_flee")) != encounter:
            continue
        if c.get("requires_item") and c["requires_item"] not in inv:
            continue
        out.append(("choice", c))
    return out


# ── one playthrough (mirrors app.py exactly, via game_rules) ──────────────────
def play(story, policy, rng, max_steps=400):
    locs, items = story["locations"], story.get("items", {})
    attr = {a: R.roll_dice("2d6", rng) for a in ATTRS}
    mhp = story["character_template"]["health"]
    hp, loc = mhp, story["start_location_id"]
    inv, looted, resolved, mn = [], set(), set(), mhp
    for _ in range(max_steps):
        L = locs.get(loc)
        if L is None:
            return "CRASH", loc, hp, mn
        if loc not in looted:
            for it in L.get("loot", []):
                if it not in inv:
                    inv.append(it)
            if L.get("loot"):
                looted.add(loc)
        if hp <= 0:
            return "DEATH", loc, hp, mn
        if L.get("is_end"):
            return ("WIN" if L.get("is_victory", True) else "BADEND"), loc, hp, mn
        heals = ([("use", it) for it in inv if items.get(it, {}).get("use", {}).get("heal")]
                 if hp < mhp else [])
        encounter = "monster" in L and loc not in resolved
        acts = ([("fight", None)] if encounter else []) + _available(L, inv, encounter) + heals
        if not acts:
            return "STUCK", loc, hp, mn
        kind, x = policy(loc, L, acts, hp, mhp, attr, inv)
        if kind == "use":
            hp = min(mhp, hp + items[x]["use"]["heal"])
            inv.remove(x)
        elif kind == "fight":
            hp -= R.resolve_monster(L["monster"], attr, rng=rng)["damage"]
            resolved.add(loc)                      # win or lose, the encounter is over
        else:
            c = x
            legacy = False
            dest = c.get("target_id")
            if "condition" in c:
                res = R.resolve_check(c["condition"], attr, inv, rng=rng)
                hp -= res["damage"]
                if hp <= 0:
                    return "DEATH", loc, hp, min(mn, hp)
                dest, legacy = R.check_destination(c, res["passed"])
            if not legacy:                         # got through → the choice's effects apply
                for it in R.as_list(c.get("gives_item")):
                    if it not in inv:
                        inv.append(it)
                if c.get("heals"):
                    hp = min(mhp, hp + c["heals"])
                for it in R.as_list(c.get("consumes_item")):
                    if it in inv:
                        inv.remove(it)
            loc = dest
        mn = min(mn, hp)
    return "LOOP", loc, hp, mn


# ── player types ──────────────────────────────────────────────────────────────
def _risk(a, L, attr, inv):
    """(pass probability, damage on failure) of an action."""
    if a[0] == "fight":
        m = L["monster"]
        return R.monster_odds(m, attr), m.get("fail_damage", R.DEFAULT_MONSTER_DAMAGE)
    cc = a[1].get("condition")
    if not cc:
        return 1.0, 0
    return R.check_odds(cc, attr, inv), cc.get("fail_damage", R.DEFAULT_CHECK_DAMAGE)


def make_random(story, rng):
    return lambda loc, L, acts, hp, mhp, attr, inv: rng.choice(acts)


def make_cautious(story, rng):
    locs, vis = story["locations"], defaultdict(int)

    def pol(loc, L, acts, hp, mhp, attr, inv):
        vis[loc] += 1
        heals = [a for a in acts if a[0] == "use"]
        if heals and hp <= 0.4 * mhp:
            return heals[0]

        def score(a):
            if a[0] == "use":
                return -50.0
            if a[0] == "choice" and (R.is_trap(a[1]) or _bad_end(locs, a[1].get("target_id"))):
                return -999.0                        # a careful reader heeds the hints
            p, dmg = _risk(a, L, attr, inv)
            s = -(1 - p) * dmg / max(hp, 1)          # expected share of remaining HP lost
            if dmg >= hp and p < 1:
                s -= 10 * (1 - p)                    # avoid rolls that could kill outright
            if a[0] == "choice":
                s -= 0.25 * vis.get(a[1].get("target_id"), 0)
            return s + rng.random() * 1e-3
        return max(acts, key=score)
    return pol


def make_heroic(story, rng):
    """Commits to the dangerous content: always fights, prefers risky and unexplored choices,
    ignores hints, and only accepts an ending once fresh options run out."""
    locs, vis = story["locations"], defaultdict(int)

    def pol(loc, L, acts, hp, mhp, attr, inv):
        vis[loc] += 1
        heals = [a for a in acts if a[0] == "use"]
        if heals and hp <= 0.45 * mhp:
            return heals[0]
        fights = [a for a in acts if a[0] == "fight"]
        if fights:
            return fights[0]
        choices = [a for a in acts if a[0] == "choice"]
        if not choices:
            return rng.choice(acts)

        def score(a):
            c = a[1]
            t = c.get("target_id", "")
            s = 2.0 * vis.get(t, 0)
            if "condition" not in c:
                s += 1.0                             # prefer risky over safe
            if locs.get(t, {}).get("is_end"):
                s += 3.0                             # delay endings, but not forever
            if _bad_end(locs, t):
                s += 100.0                           # a hero doesn't pick the doom ending
            return s + rng.random() * 0.01
        return min(choices, key=score)
    return pol


POLICIES = [("random", make_random), ("cautious", make_cautious), ("heroic", make_heroic)]


# ── analysis ──────────────────────────────────────────────────────────────────
def simulate(story, n, seed=None):
    """Run n games per player type. Returns {policy: {win, death, badend, loop, stuck, ...}}."""
    rng = random.Random(seed)
    metrics = {}
    for name, mk in POLICIES:
        res, endc = defaultdict(int), defaultdict(int)
        hpsum = mnsum = wins = 0
        for _ in range(n):
            out, loc, hp, mn = play(story, mk(story, rng), rng)
            res[out] += 1
            if out == "WIN":
                wins += 1
                hpsum += hp
                mnsum += mn
                endc[loc] += 1
        metrics[name] = {
            "win": res["WIN"] / n * 100, "death": res["DEATH"] / n * 100,
            "badend": res["BADEND"] / n * 100, "loop": res["LOOP"] / n * 100,
            "stuck": res["STUCK"] / n * 100, "crash": res["CRASH"] / n * 100,
            "avg_hp_win": hpsum / wins if wins else 0, "low_hp_win": mnsum / wins if wins else 0,
            "endings": dict(endc),
        }
    return metrics


def verdict(metrics, difficulty):
    """(ok, cw_ok, hd_ok, flags) against the band for `difficulty`."""
    flags = []
    if sum(metrics[p]["loop"] for p in ("random", "cautious", "heroic")) > 1.0:
        flags.append("LOOP>1% — possible safe cycle with no progress")
    if metrics["cautious"]["stuck"] + metrics["heroic"]["stuck"] > 0.2:
        flags.append("STUCK>0.2% — a location with no usable action (soft-lock)")
    if any(metrics[p]["crash"] for p in metrics):
        flags.append("CRASH — a choice leads to a location that doesn't exist")
    b = BANDS.get(difficulty)
    if not b:
        return None, None, None, flags
    cw, hd = metrics["cautious"]["win"], metrics["heroic"]["death"]
    cw_ok = b["cautious_win"][0] <= cw <= b["cautious_win"][1]
    hd_ok = b["heroic_death"][0] <= hd <= b["heroic_death"][1]
    return cw_ok and hd_ok and not flags, cw_ok, hd_ok, flags


def analyze(story, difficulty=None, n=None, out=print, seed=None):
    n = n or int(os.environ.get("QUEST_PLAYTEST_N", 20000))
    locs, tmpl, start = story["locations"], story["character_template"], story["start_location_id"]

    out("=" * 72)
    out("  CHALLENGES  (pass odds at average stat 7 · a failure still gets you through)")
    out("=" * 72)
    for lid, loc in locs.items():
        for ch in loc.get("choices", []):
            if "condition" in ch:
                c = ch["condition"]
                dt, cv = c.get("dice_type", R.DEFAULT_DICE), c["check_value"]
                ib = c.get("item_bonus")
                extra = (f"  (+{ib['bonus']} {ib['item']} -> {R.pass_probability(dt, cv - 7 - ib['bonus']):.0%})"
                         if ib else "")
                trap = "  [TRAP]" if R.is_trap(ch) else ""
                out(f"  {lid:18s} {c['attribute'][:3].upper()} DC{cv:<2} fail-{c.get('fail_damage', R.DEFAULT_CHECK_DAMAGE)}"
                    f"  ~{R.pass_probability(dt, cv - 7):.0%}{extra}{trap}  :: {ch['text'][:40]}")
        if "monster" in loc:
            m = loc["monster"]
            out(f"  {lid:18s} {m.get('attribute', 'strength')[:3].upper()} DC{m['strength']:<2} "
                f"fail-{m.get('fail_damage', R.DEFAULT_MONSTER_DAMAGE)}  "
                f"~{R.pass_probability(m.get('dice_type', R.DEFAULT_DICE), m['strength'] - 7):.0%}  :: MONSTER {m['name']}")

    # reachability over all transitions (incl. legacy fail_target)
    seen, q, broken = {start}, deque([start]), []
    while q:
        lid = q.popleft()
        L = locs.get(lid)
        if L is None:
            broken.append(lid)
            continue
        for ch in L.get("choices", []):
            for t in (ch.get("target_id"), R.legacy_fail_target(ch)):
                if t and t not in seen:
                    seen.add(t)
                    q.append(t)
    ends = {l for l, v in locs.items() if v.get("is_end")}
    out(f"\n  reachability: {len(seen & set(locs))}/{len(locs)} locs, "
        f"{len(seen & ends)}/{len(ends)} endings, broken={broken or 'none'}")

    metrics = simulate(story, n, seed)
    out("\n" + "=" * 72)
    out(f"  MONTE CARLO  n={n} per player type  (random 2d6 stats, random dice)")
    out("=" * 72)
    out("  player   |  WIN   DEATH  BAD   LOOP  STUCK |  avgHP@win  lowestHP@win | endings")
    for name in ("random", "cautious", "heroic"):
        m = metrics[name]
        top = sorted(m["endings"].items(), key=lambda x: -x[1])
        eshort = ", ".join(f"{k.replace('_ending', '').replace('_', ' ')}:{v * 100 // n}%" for k, v in top)
        out(f"  {name:8s} | {m['win']:5.1f}% {m['death']:5.1f}% {m['badend']:4.1f}% {m['loop']:4.1f}% "
            f"{m['stuck']:4.1f}% |   {m['avg_hp_win']:4.1f}/{tmpl['health']}    {m['low_hp_win']:5.1f}     | {eshort}")

    ok, cw_ok, hd_ok, flags = verdict(metrics, difficulty)
    if flags:
        out("\n  ⚠ structural flags: " + "; ".join(flags))
    result = {"metrics": metrics, "flags": flags, "verdict": None}
    if difficulty in BANDS:
        b = BANDS[difficulty]
        cw, hd = metrics["cautious"]["win"], metrics["heroic"]["death"]
        out("\n" + "=" * 72)
        out(f"  DIFFICULTY VERDICT  vs target '{difficulty}'")
        out("=" * 72)
        out(f"  cautious win   {cw:5.1f}%   target {b['cautious_win'][0]:>3}-{b['cautious_win'][1]:<3}%   {'OK' if cw_ok else 'ADJUST'}")
        out(f"  heroic death   {hd:5.1f}%   target {b['heroic_death'][0]:>3}-{b['heroic_death'][1]:<3}%   {'OK' if hd_ok else 'ADJUST'}")
        if not cw_ok and cw < b["cautious_win"][0]:
            out("   hint: too deadly for careful play — raise health, lower fail_damage on the main path, "
                "or add a heal item. (If careful players walk into dead ends, make the trap hints clearer.)")
        if not cw_ok and cw > b["cautious_win"][1]:
            out("   hint: too soft — lower health or raise fail_damage on the climactic checks/monsters.")
        if not hd_ok and hd < b["heroic_death"][0]:
            out("   hint: heroic routes lack stakes — a failed roll is the only way to lose HP, so raise "
                "fail_damage on risky checks and monsters (or DCs, so failures happen more often).")
        if not hd_ok and hd > b["heroic_death"][1]:
            out("   hint: heroic routes too lethal — lower fail_damage on the risky route, or add a heal item.")
        out(f"\n  >>> {'PASS — balance matches difficulty' if ok else 'ADJUST — nudge the knobs above and re-run'}")
        result["verdict"] = "PASS" if ok else "ADJUST"
    elif difficulty:
        out(f"\n  (unknown difficulty '{difficulty}'; use easy | normal | hard for a verdict)")
    return result


def main(argv):
    if len(argv) < 2:
        sys.exit("usage: playtest.py stories/<story>.json [easy|normal|hard]")
    with open(argv[1], encoding="utf-8") as f:
        story = json.load(f)
    diff = argv[2].lower() if len(argv) > 2 else None
    res = analyze(story, diff)
    if res["verdict"] is not None:
        sys.exit(0 if res["verdict"] == "PASS" else 2)


if __name__ == "__main__":
    main(sys.argv)
