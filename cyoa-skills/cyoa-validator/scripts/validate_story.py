#!/usr/bin/env python3
"""
CYOA Story Validator
Simulates all reachable game states (location × inventory), detects inconsistencies,
and can auto-correct them in-place with --fix.

Usage:
    python3 validate_story.py story.json
    python3 validate_story.py story.json --fix
"""

import json
import sys
import copy
from collections import defaultdict


# ── I/O ───────────────────────────────────────────────────────────────────────

def load(path):
    with open(path) as f:
        return json.load(f)


def save(story, path):
    with open(path, "w") as f:
        json.dump(story, f, indent=2)
    print(f"  Saved corrected story to {path}")


# ── simulation ────────────────────────────────────────────────────────────────

def simulate(story):
    """
    BFS over (location_id, frozenset(inventory)) states.
    Returns (reachable_locations, issues).
    Each issue is a dict with keys: type, location, message, fix (optional).
    """
    locs      = story["locations"]
    start     = story["start_location_id"]
    items_def = set(story.get("items", {}).keys())
    template  = story.get("character_template", {})

    issues  = []
    visited = set()           # (loc_id, frozen_inventory)
    reachable = set()
    all_given  = _collect_all_given_items(locs)

    queue = [(start, frozenset())]

    while queue:
        loc_id, inventory = queue.pop(0)
        state = (loc_id, inventory)
        if state in visited:
            continue
        visited.add(state)
        reachable.add(loc_id)

        if loc_id not in locs:
            issues.append({
                "type":     "broken_location",
                "location": loc_id,
                "message":  f"Location '{loc_id}' is referenced but does not exist.",
                "fix":      None,
            })
            continue

        loc     = locs[loc_id]
        choices = loc.get("choices", [])

        # ── monster checks ────────────────────────────────────────────────────
        if "monster" in loc:
            m = loc["monster"]
            if "strength" not in m:
                issues.append({
                    "type":     "monster_missing_strength",
                    "location": loc_id,
                    "message":  f"Monster in '{loc_id}' has no 'strength' (DC) field.",
                    "fix":      ("monster", "strength", 9),
                })
            if "fail_damage" not in m:
                issues.append({
                    "type":     "monster_missing_fail_damage",
                    "location": loc_id,
                    "message":  f"Monster in '{loc_id}' has no 'fail_damage' field.",
                    "fix":      ("monster", "fail_damage", 4),
                })

        # ── dead-end check ────────────────────────────────────────────────────
        if not loc.get("is_end") and not choices and "monster" not in loc:
            issues.append({
                "type":     "dead_end",
                "location": loc_id,
                "message":  f"'{loc_id}' has no choices and is not marked is_end.",
                "fix":      ("is_end", True),
            })
            continue

        # ── choice-level checks ───────────────────────────────────────────────
        for choice in choices:
            text   = choice.get("text", "<unnamed>")
            target = choice.get("target_id")
            fail_t = choice.get("fail_target") or choice.get("condition", {}).get("fail_target")

            if not target:
                issues.append({
                    "type":     "choice_missing_target",
                    "location": loc_id,
                    "message":  f"Choice '{text}' in '{loc_id}' has no target_id.",
                    "fix":      None,
                })
                continue

            if target not in locs:
                issues.append({
                    "type":     "broken_link",
                    "location": loc_id,
                    "message":  f"Choice '{text}' in '{loc_id}' leads to missing location '{target}'.",
                    "fix":      ("choice_target", text, loc_id),
                })

            if fail_t and fail_t not in locs:
                issues.append({
                    "type":     "broken_fail_target",
                    "location": loc_id,
                    "message":  f"Choice '{text}' in '{loc_id}' has missing fail_target '{fail_t}'.",
                    "fix":      ("remove_fail_target", text),
                })

            # attribute name check
            if "condition" in choice:
                attr = choice["condition"].get("attribute")
                if attr and attr not in template:
                    issues.append({
                        "type":     "unknown_attribute",
                        "location": loc_id,
                        "message":  (
                            f"Choice '{text}' in '{loc_id}' checks attribute '{attr}' "
                            f"which is not in character_template. "
                            f"Valid: {list(template.keys())}"
                        ),
                        "fix":      None,
                    })

            # requires_item — is it ever obtainable?
            req = choice.get("requires_item")
            if req:
                if req not in items_def:
                    issues.append({
                        "type":     "requires_unknown_item",
                        "location": loc_id,
                        "message":  (
                            f"Choice '{text}' in '{loc_id}' requires item '{req}' "
                            f"which is not defined in story['items']."
                        ),
                        "fix":      None,
                    })
                elif req not in all_given:
                    issues.append({
                        "type":     "item_never_obtainable",
                        "location": loc_id,
                        "message":  (
                            f"Choice '{text}' in '{loc_id}' requires item '{req}', "
                            f"but no choice or loot in the story ever grants it."
                        ),
                        "fix":      None,
                    })

            # enqueue next states
            if target in locs:
                new_inv = set(inventory)
                new_inv.update(_coerce_list(choice.get("gives_item")))
                new_inv.update(locs[target].get("loot", []))
                queue.append((target, frozenset(new_inv)))

            if fail_t and fail_t in locs:
                queue.append((fail_t, frozenset(inventory)))

    # ── unreachable locations ─────────────────────────────────────────────────
    for loc_id in locs:
        if loc_id not in reachable:
            issues.append({
                "type":     "unreachable",
                "location": loc_id,
                "message":  f"Location '{loc_id}' is never reachable from start.",
                "fix":      ("remove_location", loc_id),
            })

    # ── reachable locations with no path to any ending ────────────────────────
    can_end = _build_can_end_map(locs)
    for loc_id in reachable:
        if not can_end.get(loc_id, False):
            issues.append({
                "type":     "no_path_to_end",
                "location": loc_id,
                "message":  f"'{loc_id}' is reachable but no path from it leads to an is_end location.",
                "fix":      ("is_end", True),
            })

    return reachable, issues


def _collect_all_given_items(locs):
    given = set()
    for loc in locs.values():
        given.update(loc.get("loot", []))
        for choice in loc.get("choices", []):
            given.update(_coerce_list(choice.get("gives_item")))
    return given


def _build_can_end_map(locs):
    """Return dict loc_id → bool: can this location reach an is_end?

    Computed as reverse-reachability from every is_end location, which is
    correct in the presence of cycles. (A previous recursive version memoized
    False results produced by its own cycle-cutoff, yielding false positives
    for locations whose only path to an ending passed through a node that was
    temporarily on the recursion stack — e.g. when retreat/loop choices exist.)
    """
    # Reverse adjacency: rev[target] = {locations that can move to target}.
    rev = defaultdict(set)
    for loc_id, loc in locs.items():
        for choice in loc.get("choices", []):
            for tgt in (
                choice.get("target_id"),
                choice.get("fail_target"),
                choice.get("condition", {}).get("fail_target"),
            ):
                if tgt in locs:
                    rev[tgt].add(loc_id)

    can = {loc_id: False for loc_id in locs}
    stack = []
    for loc_id, loc in locs.items():
        if loc.get("is_end"):
            can[loc_id] = True
            stack.append(loc_id)

    while stack:
        node = stack.pop()
        for pred in rev[node]:
            if not can[pred]:
                can[pred] = True
                stack.append(pred)

    return can


def _coerce_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


# ── auto-fix ──────────────────────────────────────────────────────────────────

def auto_fix(story, issues):
    locs  = story["locations"]
    fixed = []

    for issue in issues:
        t   = issue["type"]
        fix = issue.get("fix")
        if not fix:
            continue
        loc_id = issue["location"]

        if t == "dead_end" or t == "no_path_to_end":
            if loc_id in locs:
                locs[loc_id]["is_end"]      = True
                locs[loc_id].setdefault("is_victory", False)
                fixed.append(f"Marked '{loc_id}' as is_end (non-victory dead-end).")

        elif t == "monster_missing_strength":
            if loc_id in locs and "monster" in locs[loc_id]:
                locs[loc_id]["monster"]["strength"] = fix[2]
                fixed.append(f"Set monster.strength={fix[2]} in '{loc_id}'.")

        elif t == "monster_missing_fail_damage":
            if loc_id in locs and "monster" in locs[loc_id]:
                locs[loc_id]["monster"]["fail_damage"] = fix[2]
                fixed.append(f"Set monster.fail_damage={fix[2]} in '{loc_id}'.")

        elif t == "broken_link":
            # Loop the broken target back to the current location
            choice_text = fix[1]
            if loc_id in locs:
                for c in locs[loc_id].get("choices", []):
                    if c.get("text") == choice_text:
                        broken = c["target_id"]
                        c["target_id"] = loc_id
                        fixed.append(
                            f"Broke-link in '{loc_id}': redirected '{broken}' → '{loc_id}' (loop)."
                        )

        elif t == "broken_fail_target":
            choice_text = fix[1]
            if loc_id in locs:
                for c in locs[loc_id].get("choices", []):
                    if c.get("text") == choice_text and "fail_target" in c:
                        del c["fail_target"]
                        fixed.append(f"Removed broken fail_target in '{loc_id}' choice '{choice_text}'.")

        elif t == "unreachable":
            # Remove the location entirely if it's never reachable
            removed_id = fix[1]
            if removed_id in locs:
                del locs[removed_id]
                fixed.append(f"Removed unreachable location '{removed_id}'.")

    return fixed


# ── report ────────────────────────────────────────────────────────────────────

def print_report(reachable, issues, fixed=None):
    W = 62
    print("\n" + "=" * W)
    print("  CYOA Story Validation Report")
    print("=" * W)
    print(f"  Reachable states explored: {len(reachable)} location(s)")

    if not issues:
        print("\n  ✅  No issues found — story is valid and complete.\n")
    else:
        by_type = defaultdict(list)
        for iss in issues:
            by_type[iss["type"]].append(iss)

        print(f"\n  ⚠️   Found {len(issues)} issue(s):\n")
        for t, group in sorted(by_type.items()):
            auto = "✔ auto-fixable" if any(g.get("fix") for g in group) else "✘ manual fix needed"
            print(f"  [{t}]  ×{len(group)}  ({auto})")
            for iss in group[:2]:
                print(f"    • {iss['message']}")
            if len(group) > 2:
                print(f"    … and {len(group) - 2} more.")

    if fixed:
        print(f"\n  🔧  Auto-fixed {len(fixed)} issue(s):")
        for f in fixed:
            print(f"    • {f}")
        print(f"\n  Re-run without --fix to confirm the story is now valid.")

    print("=" * W + "\n")


# ── entry ─────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: validate_story.py story.json [--fix]")
        sys.exit(1)

    path   = sys.argv[1]
    do_fix = "--fix" in sys.argv

    story = load(path)

    # basic schema check
    for field in ("title", "character_template", "start_location_id", "locations"):
        if field not in story:
            print(f"Error: missing required top-level field '{field}'")
            sys.exit(1)

    if story["start_location_id"] not in story["locations"]:
        print(f"Error: start_location_id '{story['start_location_id']}' not in locations")
        sys.exit(1)

    reachable, issues = simulate(story)

    fixed = []
    if do_fix and issues:
        story_copy = copy.deepcopy(story)
        fixed = auto_fix(story_copy, issues)
        if fixed:
            save(story_copy, path)
            # re-validate after fix
            reachable, issues = simulate(story_copy)

    print_report(reachable, issues, fixed)
    sys.exit(0 if not issues else 1)


if __name__ == "__main__":
    main()
