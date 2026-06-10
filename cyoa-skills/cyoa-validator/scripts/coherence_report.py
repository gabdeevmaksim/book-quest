#!/usr/bin/env python3
"""
CYOA Coherence & Pre-history report.

Complements the other gates:
  - validate_story.py  -> correctness (links, reachability, can-reach-an-ending)
  - playtest.py        -> balance (difficulty band)
  - coherence_report.py-> connectivity / "does the map read like a place" + a real opening

It flags the two things players complained about: maps that feel chaotic / disconnected,
and thin pre-history. These are heuristics meant to focus a human/agent review, not hard law.

Usage:
    python3 coherence_report.py <story.json>

Exit codes: 0 = OK, 2 = REVIEW (address the listed items), 1 = load error.
"""
import json
import sys
from collections import defaultdict, deque


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


def main():
    if len(sys.argv) < 2:
        print("usage: coherence_report.py <story.json>")
        sys.exit(1)
    path = sys.argv[1]
    try:
        story = json.load(open(path))
    except Exception as e:
        print("load error:", e)
        sys.exit(1)

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

    W = 66
    print("=" * W)
    print("  CYOA Coherence & Pre-history Report")
    print("=" * W)
    avg_choices = sum(len(locs[n].get("choices", [])) for n in nodes) / max(len(nodes), 1)
    print(f"  locations {len(nodes)} | endings {len(ends)} (victory {len(victories)}) | start '{start}'")
    print(f"  avg choices/loc {avg_choices:.1f} | avg out-degree "
          f"{sum(outdeg.values())/max(len(nodes),1):.1f} | backtrack {backratio:.0%}")
    mx = max(depth.values()) if depth else 0
    unreached = [n for n in nodes if n not in depth]
    print(f"  max depth from start {mx}" + (f" | UNREACHED {unreached[:5]}" if unreached else ""))
    print(f"  single-entry mid locations (indeg 1): {len(thin)}")
    print(f"  free-movement loops: {len(loops)}"
          + (f" -> {[sorted(c) for c in loops][:4]}" if loops else ""))
    print(f"  pre-history: prologue {len(prologue)} | goal {len(goal)} | start-desc {len(startdesc)} chars")
    print(f"  linearity: {len(single)}/{len(mid)} single-choice mid locations "
          f"({single_ratio:.0%}) | avg mid choices {avg_mid:.2f} | longest corridor {longest_run}")
    print(f"  item grants: {sum(len(v) for v in grants_by_item.values())} "
          f"| ungrounded {len(ungrounded)} | double-collectable {len(dup)}")

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
