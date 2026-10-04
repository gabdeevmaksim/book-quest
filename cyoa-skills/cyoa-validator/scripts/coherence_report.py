#!/usr/bin/env python3
"""
CYOA Coherence & Pre-history report.

Complements the other gates:
  - validate_story.py  -> correctness (links, reachability, can-reach-an-ending)
  - playtest.py        -> balance (difficulty band)
  - coherence_report.py-> connectivity / "does the map read like a place" + a real opening

It flags the two things players complained about: maps that feel chaotic / disconnected,
and thin pre-history. These are heuristics meant to focus a human/agent review, not hard law.
It also enforces the challenge rules: every check and monster has success/fail outcome texts
(failing still gets you through, at an HP cost), no retired fail_target, and the right number
of hinted dead-end branches ("traps") for the story's difficulty.

Usage:
    python3 coherence_report.py <story.json>
    (import: analyze(story) -> (issues, report_lines))

Exit codes: 0 = OK, 2 = REVIEW (address the listed items), 1 = load error.
"""
import json
import os
import sys
from collections import defaultdict, deque

# Shared rule numbers live in game_rules.py at the repo root; fall back to an identical copy
# when this skill script is used on its own.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
try:
    from game_rules import trap_band
except ImportError:                                   # standalone skill usage
    def trap_band(difficulty, n_locations):
        d, n = (difficulty or "normal").lower(), int(n_locations or 0)
        if d == "easy":
            return 0, 0
        if d == "hard":
            return 2, min(4, 2 + max(0, n - 12) // 5)
        return (1, 1) if n <= 14 else (1, 2)


def coerce(v):
    return [] if v is None else (v if isinstance(v, list) else [v])


def free_moves(loc):
    """Player-controlled, zero-cost transitions: no dice check, no item gate, not a flee."""
    out = []
    for c in loc.get("choices", []):
        if c.get("is_flee") or ("condition" in c) or c.get("requires_item"):
            continue
        t = c.get("target_id")
        if t:
            out.append(t)
    return out


def all_targets(loc):
    out = []
    for c in loc.get("choices", []):
        if c.get("target_id"):
            out.append(c["target_id"])
        ft = c.get("fail_target") or c.get("condition", {}).get("fail_target")
        if ft:
            out.append(ft)
    return out


_STOP = {"with", "that", "this", "your", "from", "into", "when", "have", "will",
         "restores", "grants", "gives", "bonus", "consuming", "using", "used"}


def _tokens(text, min_len=3):
    """Significant lowercase word tokens (works for any language)."""
    import re
    return [t for t in re.split(r"[^\w]+", (text or "").casefold())
            if len(t) >= min_len and t not in _STOP]


def item_grant_points(story):
    """Yield (item_id, loc_id, how, context_text) for every place an item is granted."""
    locs = story.get("locations", {})
    for lid, loc in locs.items():
        desc = loc.get("description", "") or ""
        for it in coerce(loc.get("loot")):
            yield it, lid, "loot", desc
        for c in loc.get("choices", []):
            if c.get("gives_item"):
                yield c["gives_item"], lid, "gives_item", desc + " " + (c.get("text") or "")


def corridor_runs(locs):
    """Longest chain of consecutive single-choice, non-end locations."""
    single = {n for n, l in locs.items()
              if not l.get("is_end") and len(l.get("choices", [])) == 1}
    best = 0
    for n in single:
        run, cur, seen = 0, n, set()
        while cur in single and cur not in seen:
            seen.add(cur); run += 1
            cur = locs[cur]["choices"][0].get("target_id")
        best = max(best, run)
    return single, best


def sccs_with_cycle(nodes, adj):
    """Tarjan SCCs; return components that contain a cycle (size>1, or a self-loop)."""
    sys.setrecursionlimit(10000)
    index, low, onstack, stack, idx, out = {}, {}, {}, [], [0], []

    def strong(v):
        index[v] = low[v] = idx[0]; idx[0] += 1
        stack.append(v); onstack[v] = True
        for w in adj.get(v, []):
            if w not in index:
                strong(w); low[v] = min(low[v], low[w])
            elif onstack.get(w):
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop(); onstack[w] = False; comp.append(w)
                if w == v:
                    break
            out.append(comp)

    for n in nodes:
        if n not in index:
            strong(n)
    cyclic = [c for c in out if len(c) > 1]
    cyclic += [[n] for n in nodes if n in adj.get(n, [])]   # self-loops
    return cyclic


def _reach_from(locs, roots):
    seen, q = set(roots), deque(roots)
    while q:
        n = q.popleft()
        for t in all_targets(locs.get(n, {})):
            if t in locs and t not in seen:
                seen.add(t)
                q.append(t)
    return seen


def challenge_issues(story):
    """Fail-forward rules: outcome texts on every check/monster, no fail_target, and a way
    onward after every monster encounter."""
    locs = story.get("locations", {})
    missing, legacy, stuck = [], [], []

    def has_texts(spec):
        return bool(str(spec.get("success_text") or "").strip()
                    and str(spec.get("fail_text") or "").strip())

    for lid, L in locs.items():
        for c in L.get("choices", []):
            cond = c.get("condition")
            if cond is not None and not has_texts(cond):
                missing.append(f"{lid}: '{(c.get('text') or '')[:30]}'")
            if c.get("fail_target") or (cond or {}).get("fail_target"):
                legacy.append(lid)
        m = L.get("monster")
        if m:
            if not has_texts(m):
                missing.append(f"{lid}: monster {m.get('name', '?')}")
            if not any(not c.get("is_flee") for c in L.get("choices", [])):
                stuck.append(lid)
    issues = []
    if missing:
        issues.append(("outcome", f"{len(missing)} challenge(s) without both success_text and fail_text: "
                       + "; ".join(missing[:6]) + " — every check and monster needs a short success text "
                       "and a realistic fail text: the hero still gets through, and the text says what it "
                       "cost, matching the approach (forcing a door hurts a shoulder, squeezing through "
                       "the splintered frame cuts an arm)"))
    if legacy:
        issues.append(("rules", f"fail_target used at {sorted(set(legacy))[:6]} — retired: a failed check "
                       "always continues to target_id with HP loss. Model bad outcomes as hinted dead-end "
                       "branches (trap_hint) entered by a wrong decision instead"))
    if stuck:
        issues.append(("flow", f"monster location(s) with no onward (non-flee) choice: {stuck[:6]} — after "
                       "the encounter (won or lost) the hero needs a way forward"))
    return issues, {"missing_texts": len(missing)}


def trap_issues(story, depth):
    """Hinted dead ends: how many per difficulty, that each is a real played-out dead end with
    its hint in the scene text, and that there are no untagged dead ends."""
    locs = story.get("locations", {})
    nodes = list(locs)
    diff = (story.get("difficulty") or "normal").lower()
    victories = [n for n in nodes if locs[n].get("is_end") and locs[n].get("is_victory", True)]
    rev = defaultdict(set)
    for n in nodes:
        for t in all_targets(locs[n]):
            if t in locs:
                rev[t].add(n)
    can_win, stack = set(victories), list(victories)
    while stack:
        x = stack.pop()
        for p in rev[x]:
            if p not in can_win:
                can_win.add(p)
                stack.append(p)

    traps = [(n, c, c.get("target_id")) for n in nodes for c in locs[n].get("choices", [])
             if str(c.get("trap_hint") or "").strip()]
    branches = {t for _, _, t in traps if t in locs}
    in_trap = _reach_from(locs, list(branches))
    dead = sorted(n for n in depth if n in locs and not locs[n].get("is_end") and n not in can_win)
    lo, hi = trap_band(diff, len(nodes))
    issues = []
    if diff == "easy":
        if traps:
            issues.append(("traps", f"easy stories have no dead ends, but {len(traps)} choice(s) carry "
                           "trap_hint — remove them"))
        if dead:
            issues.append(("traps", f"easy: {len(dead)} location(s) can no longer reach a victory: "
                           f"{dead[:6]} — on easy every path must stay winnable"))
        return issues, {"traps": len(branches), "band": (lo, hi)}

    if not lo <= len(branches) <= hi:
        want = f"{lo}" if lo == hi else f"{lo}–{hi}"
        issues.append(("traps", f"{len(branches)} hinted dead-end branch(es); a {diff} story of "
                       f"{len(nodes)} locations needs {want}: a choice with trap_hint leading into an "
                       "inescapable branch, played out over 2+ locations, that ends in a non-victory ending"))
    problems = []
    for src, c, t in traps:
        label = f"'{(c.get('text') or '')[:30]}' at {src}"
        if t in locs:
            if t in can_win:
                problems.append(f"{label} → {t} can still reach a victory (not a dead end)")
            elif locs[t].get("is_end"):
                problems.append(f"{label} jumps straight to an ending — play the doom out over 2+ locations")
        hint = str(c.get("trap_hint")).strip().casefold()
        scene = ((locs[src].get("description") or "") + " " + (c.get("text") or "")).casefold()
        if hint not in scene:
            problems.append(f"{label}: trap_hint '{c.get('trap_hint')}' doesn't appear in the scene text — "
                            "quote the exact phrase from the description that foreshadows the danger")
    if problems:
        issues.append(("traps", "; ".join(problems[:6])))
    untagged = [n for n in dead if n not in in_trap]
    if untagged:
        issues.append(("traps", f"dead-end location(s) not inside a tagged trap: {untagged[:6]} — tag the "
                       "entrance choice with trap_hint and foreshadow it, or give the branch a way back"))
    doom = [f"{n}→{c.get('target_id')}" for n in nodes if n in can_win and n not in in_trap
            for c in locs[n].get("choices", [])
            if locs.get(c.get("target_id"), {}).get("is_end")
            and not locs[c["target_id"]].get("is_victory", True)]
    if doom:
        issues.append(("traps", f"instant doom choice(s): {doom[:6]} — a wrong decision should lead into a "
                       "hinted dead-end branch played out over 2+ locations, not straight to a bad ending"))
    return issues, {"traps": len(branches), "band": (lo, hi)}


def analyze(story):
    """Run every coherence check. Returns (issues, report_lines); issues == [] means OK."""
    out = []
    locs = story.get("locations", {})
    start = story.get("start_location_id")
    nodes = list(locs)

    # depth (min hops) from start over all transitions
    depth = {}
    if start in locs:
        depth[start] = 0
        q = deque([start])
        while q:
            n = q.popleft()
            for t in all_targets(locs[n]):
                if t in locs and t not in depth:
                    depth[t] = depth[n] + 1
                    q.append(t)

    outdeg = {n: len({t for t in all_targets(locs[n]) if t in locs and t != n}) for n in nodes}
    indeg = defaultdict(int)
    for n in nodes:
        for t in {t for t in all_targets(locs[n]) if t in locs and t != n}:
            indeg[t] += 1

    free_adj = {n: [t for t in free_moves(locs[n]) if t in locs] for n in nodes}
    loops = sccs_with_cycle(nodes, free_adj)
    big_loops = [c for c in loops if len(c) >= 3]

    # backtrack ratio: non-flee forward choices that land on a strictly shallower room
    fwd = back = 0
    for n in nodes:
        if n not in depth:
            continue
        for c in locs[n].get("choices", []):
            if c.get("is_flee"):
                continue
            t = c.get("target_id")
            if t in depth:
                fwd += 1
                if depth[t] < depth[n]:
                    back += 1
    backratio = back / fwd if fwd else 0.0

    overloaded = [n for n in nodes
                  if len([c for c in locs[n].get("choices", []) if not c.get("is_flee")]) > 6]
    ends = [n for n in nodes if locs[n].get("is_end")]
    victories = [n for n in ends if locs[n].get("is_victory", True)]
    thin = [n for n in nodes if n != start and not locs[n].get("is_end") and indeg.get(n, 0) == 1]

    prologue = story.get("prologue") or ""
    goal = story.get("goal") or ""
    startdesc = locs.get(start, {}).get("description", "") if start in locs else ""

    issues = []
    if big_loops:
        issues.append(("loop", f"{len(big_loops)} free-movement loop region(s) — rooms you can "
                       f"circle endlessly at no cost: "
                       + "; ".join("{" + ", ".join(sorted(c)) + "}" for c in big_loops[:4])))
    if not prologue or len(prologue) < 120:
        issues.append(("intro", f"prologue missing/thin ({len(prologue)} chars) — add 3-6 sentences "
                       f"of pre-history: who the player is, the world, the inciting incident, the stakes"))
    if len(goal) < 40:
        issues.append(("intro", f"goal is thin ({len(goal)} chars) — state what winning means"))
    if len(startdesc) < 150:
        issues.append(("intro", f"start description thin ({len(startdesc)} chars) — open with stronger orientation"))
    if backratio > 0.35:
        issues.append(("flow", f"{backratio:.0%} of choices go backward — map may feel mazey/chaotic; "
                       f"prefer motivated forward transitions"))
    if overloaded:
        issues.append(("flow", f"locations with >6 choices (overwhelming): {overloaded}"))

    # --- linearity: the story must not read like a corridor ---
    mid = [n for n in nodes if not locs[n].get("is_end")]
    single, longest_run = corridor_runs(locs)
    single_ratio = len(single) / len(mid) if mid else 0.0
    avg_mid = sum(len(locs[n].get("choices", [])) for n in mid) / max(len(mid), 1)
    if single_ratio > 0.40:
        issues.append(("linear", f"{len(single)}/{len(mid)} ({single_ratio:.0%}) non-end locations "
                       f"have exactly ONE choice — the story is a corridor, not an adventure; "
                       f"give most locations 2-3 meaningful choices"))
    if avg_mid < 1.6 and len(mid) >= 6:
        issues.append(("linear", f"avg {avg_mid:.2f} choices per non-end location (< 1.6) — "
                       f"add real branching"))
    if longest_run > 3:
        issues.append(("linear", f"a chain of {longest_run} consecutive single-choice locations — "
                       f"break corridors up with decisions (max 2-3 in a row)"))

    # --- items: every grant must be grounded in the narrative ---
    items = story.get("items", {})
    ungrounded, grants_by_item = [], defaultdict(list)
    for it, lid, how, ctx in item_grant_points(story):
        grants_by_item[it].append(lid)
        idef = items.get(it, {}) or {}
        name = idef.get("name", "") or it.replace("_", " ")
        toks = (_tokens(name, 3) or [name.casefold()]) + _tokens(idef.get("description", ""), 5)
        if not any(t in ctx.casefold() for t in toks):
            ungrounded.append(f"'{it}' at '{lid}' ({how})")
    if ungrounded:
        issues.append(("items", f"item(s) granted but never mentioned in the location/choice text — "
                       f"they appear out of nowhere: " + "; ".join(ungrounded[:6])
                       + ". Weave each item into the description, or grant it via an explicit "
                       f"'take it' choice (gives_item)"))
    # duplicate grants are a problem only if the player can collect both copies
    dup = []
    for it, lids in grants_by_item.items():
        uniq = sorted(set(lids))
        if len(uniq) > 1:
            for i, a in enumerate(uniq):
                for b in uniq[i + 1:]:
                    seen, q = {a}, deque([a])
                    while q:
                        n = q.popleft()
                        for t in all_targets(locs.get(n, {})):
                            if t == b:
                                dup.append(f"'{it}' ({a} -> {b})"); q.clear(); break
                            if t in locs and t not in seen:
                                seen.add(t); q.append(t)
    if dup:
        issues.append(("items", f"same item collectable twice on one path: " + "; ".join(dup[:4])
                       + " — keep one grant per reachable path"))

    # --- challenges (fail-forward rules) + hinted dead ends ---
    ch_issues, ch_stats = challenge_issues(story)
    tr_issues, tr_stats = trap_issues(story, depth)
    issues += ch_issues + tr_issues

    avg_choices = sum(len(locs[n].get("choices", [])) for n in nodes) / max(len(nodes), 1)
    out.append(f"  locations {len(nodes)} | endings {len(ends)} (victory {len(victories)}) | start '{start}'")
    out.append(f"  avg choices/loc {avg_choices:.1f} | avg out-degree "
               f"{sum(outdeg.values())/max(len(nodes),1):.1f} | backtrack {backratio:.0%}")
    mx = max(depth.values()) if depth else 0
    unreached = [n for n in nodes if n not in depth]
    out.append(f"  max depth from start {mx}" + (f" | UNREACHED {unreached[:5]}" if unreached else ""))
    out.append(f"  single-entry mid locations (indeg 1): {len(thin)}")
    out.append(f"  free-movement loops: {len(loops)}"
               + (f" -> {[sorted(c) for c in loops][:4]}" if loops else ""))
    out.append(f"  pre-history: prologue {len(prologue)} | goal {len(goal)} | start-desc {len(startdesc)} chars")
    out.append(f"  linearity: {len(single)}/{len(mid)} single-choice mid locations "
               f"({single_ratio:.0%}) | avg mid choices {avg_mid:.2f} | longest corridor {longest_run}")
    out.append(f"  item grants: {sum(len(v) for v in grants_by_item.values())} "
               f"| ungrounded {len(ungrounded)} | double-collectable {len(dup)}")
    lo, hi = tr_stats["band"]
    out.append(f"  challenges: missing outcome texts {ch_stats['missing_texts']} | hinted dead ends "
               f"{tr_stats['traps']} (target {lo if lo == hi else f'{lo}-{hi}'} for "
               f"'{(story.get('difficulty') or 'normal').lower()}')")
    return issues, out


def main():
    if len(sys.argv) < 2:
        print("usage: coherence_report.py <story.json>")
        sys.exit(1)
    try:
        with open(sys.argv[1], encoding="utf-8") as f:
            story = json.load(f)
    except Exception as e:
        print("load error:", e)
        sys.exit(1)
    issues, lines = analyze(story)
    W = 66
    print("=" * W)
    print("  CYOA Coherence & Pre-history Report")
    print("=" * W)
    for ln in lines:
        print(ln)
    if issues:
        print(f"\n  REVIEW — {len(issues)} item(s) to address:")
        for tag, msg in issues:
            print(f"    [{tag}] {msg}")
        print("\n  >>> COHERENCE: REVIEW")
        print("=" * W)
        sys.exit(2)
    print("\n  >>> COHERENCE: OK")
    print("=" * W)
    sys.exit(0)


if __name__ == "__main__":
    main()
