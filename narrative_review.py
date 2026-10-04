#!/usr/bin/env python3
"""
narrative_review.py — the story-review agent: a continuity editor for Quest Book stories.

The other gates are mechanical (links, map shape, balance). This one READS the story, the way a
player would, and catches what scripts can't:
  • transitions  — does the scene you arrive in follow from the choice you made and the scene
                   you came from? (no teleports, no "you climb the tower" → a cellar)
  • outcomes     — do the success/fail texts fit the challenge and the scene they lead to?
                   (a fail text must not stop the hero; the next scene must not contradict it)
  • introduced   — is anyone/anything referred to as already known before the player could
                   have met it on that path? (scenes reachable from several places must work
                   for every way in)
  • contradictions — facts that clash with earlier scenes (the dead guard reappears, night → noon)
  • endings      — do victories pay off the goal, and do dead-end branches follow from their hint?

One model call reviews the whole story (a compact outline, not the raw JSON). Problems come back
as JSON with a severity; any "major" problem fails the gate and is fed into the generator's repair
loop. Minor problems are reported but don't block.

Streamlit-free and API-agnostic: pass `call(system, messages) -> text`. story_engine.py wires it
to a cheap model (see QUEST_REVIEW_* in story_engine) and runs it as the 4th gate of create_story.

CLI (needs the model key in the environment):
    python3 narrative_review.py stories/<story>.json
"""
import json
import re
import sys
from collections import defaultdict

TYPES = ("transition", "outcome", "introduced", "contradiction", "ending")

SYSTEM = """You are a meticulous continuity editor for branching choose-your-own-adventure stories.
You review the whole story map and report only CONCRETE problems that would confuse or jar a reader.

How the game works (do not report these as problems):
- Every challenge (a check on a choice, or a monster) is resolved by one dice roll. On SUCCESS the
  success text is shown; on FAILURE the hero STILL gets through to the same next scene, but is hurt,
  and the fail text describes the injury. So BOTH outcome texts must lead naturally into the same
  next scene.
- A scene can be reached from several earlier scenes ("reached from"); its description must make
  sense for EVERY way in.
- Choices marked TRAP lead into a deliberate dead end that ends badly; the hint quoted with them is
  supposed to foreshadow it. Bad endings at the end of a trap branch are intended.
- Items are granted by "gives"/"loot"; a choice marked "needs" only appears when the item is held.

Check for:
1. transition — the destination scene does not follow from the choice text and the source scene
   (teleport, wrong place, ignores what the player just did).
2. outcome — a success/fail text that doesn't fit its challenge, that has the hero stopped, turned
   back or captured (failure always continues), or that the next scene contradicts.
3. introduced — a person, object, place or event referred to as already known ("the key", "Marta",
   "the second door") before the player can have encountered it on some path into that scene.
4. contradiction — facts that clash with earlier scenes (who is alive, time of day, what was
   destroyed, what the hero carries).
5. ending — a victory ending that doesn't pay off the goal, or a dead-end branch whose ending
   doesn't follow from the trap it starts with.

Severity: "major" = a reader would notice and be confused or pulled out of the story;
"minor" = small roughness. Do NOT report style, prose quality, spelling, balance or difficulty.
The story may be in any language; write your findings in English.

Reply with ONLY a JSON object, no prose:
{"issues": [{"type": "transition|outcome|introduced|contradiction|ending",
             "severity": "major|minor",
             "location": "<location id>",
             "choice": "<choice text, or null>",
             "problem": "<what is wrong, briefly>",
             "fix": "<a concrete fix>"}]}
Return {"issues": []} if you find nothing worth reporting."""


def _short(text, n=700):
    t = " ".join(str(text or "").split())
    return t if len(t) <= n else t[:n] + "…"


def outline(story):
    """Compact, model-friendly rendering of the story map (much smaller than the raw JSON)."""
    locs = story.get("locations", {})
    items = story.get("items", {})
    incoming = defaultdict(list)
    for lid, L in locs.items():
        for c in L.get("choices", []):
            t = c.get("target_id")
            if t in locs and lid not in incoming[t]:
                incoming[t].append(lid)

    def item_name(i):
        return (items.get(i) or {}).get("name") or i

    lines = [f"TITLE: {story.get('title', '')}",
             f"LANGUAGE: {story.get('language', 'English')}",
             f"GOAL: {_short(story.get('goal'), 400)}",
             f"PROLOGUE: {_short(story.get('prologue'), 1200)}",
             f"START: {story.get('start_location_id')}"]
    if items:
        lines.append("ITEMS: " + "; ".join(f"{k} = {item_name(k)}" for k in items))
    lines.append("")
    for lid, L in locs.items():
        tag = ""
        if L.get("is_end"):
            tag = "  [ENDING: " + ("victory" if L.get("is_victory", True) else "BAD") + "]"
        lines.append(f"## {lid}{tag}")
        frm = incoming.get(lid) or (["(start)"] if lid == story.get("start_location_id") else ["(unreached)"])
        lines.append(f"reached from: {', '.join(frm)}")
        lines.append(f"scene: {_short(L.get('description'))}")
        if L.get("loot"):
            lines.append("loot: " + ", ".join(item_name(i) for i in L["loot"]))
        m = L.get("monster")
        if m:
            lines.append(f"MONSTER {m.get('name', '?')} ({m.get('attribute', 'strength')}) "
                         f"| win: {_short(m.get('success_text'), 240)} | lose: {_short(m.get('fail_text'), 240)}")
        for c in L.get("choices", []):
            bits = [f'- "{_short(c.get("text"), 200)}" -> {c.get("target_id")}']
            if c.get("is_flee"):
                bits.append("[alternative to the monster]")
            if c.get("trap_hint"):
                bits.append(f'[TRAP — hint: "{c["trap_hint"]}"]')
            cond = c.get("condition")
            if cond:
                bits.append(f"[{cond.get('attribute', '?')} check | success: {_short(cond.get('success_text'), 240)}"
                            f" | fail: {_short(cond.get('fail_text'), 240)}]")
            if c.get("requires_item"):
                bits.append(f"[needs {item_name(c['requires_item'])}]")
            gives = c.get("gives_item")
            if gives:
                gives = gives if isinstance(gives, list) else [gives]
                bits.append("[gives " + ", ".join(item_name(i) for i in gives) + "]")
            lines.append(" ".join(bits))
        lines.append("")
    return "\n".join(lines)


def build_messages(story):
    return SYSTEM, [{"role": "user", "content":
                     "Review this story map for continuity problems.\n\n" + outline(story)}]


def _extract_json(text):
    t = (text or "").strip()
    t = re.sub(r"^```[a-zA-Z0-9]*\n?", "", t)
    t = re.sub(r"\n?```$", "", t).strip()
    a, b = t.find("{"), t.rfind("}")
    if a == -1 or b <= a:
        return None
    try:
        return json.loads(t[a:b + 1])
    except ValueError:
        return None


def parse(text, story=None):
    """Model reply → normalised list of issues, or None if the reply is unusable."""
    data = _extract_json(text)
    if not isinstance(data, dict) or not isinstance(data.get("issues"), list):
        return None
    locs = (story or {}).get("locations", {})
    out = []
    for it in data["issues"]:
        if not isinstance(it, dict) or not str(it.get("problem") or "").strip():
            continue
        sev = str(it.get("severity") or "minor").lower()
        typ = str(it.get("type") or "transition").lower()
        loc = str(it.get("location") or "")
        out.append({
            "type": typ if typ in TYPES else "transition",
            "severity": "major" if sev == "major" else "minor",
            "location": loc if (not locs or loc in locs) else f"{loc} (?)",
            "choice": it.get("choice") or None,
            "problem": str(it["problem"]).strip(),
            "fix": str(it.get("fix") or "").strip(),
        })
    return out


def review_story(story, call, log=None):
    """Run the review. `call(system, messages) -> text`.
    Returns {"status": "OK" | "REVIEW" | "skipped", "issues": [...], "majors": n, "minors": n,
             "detail": str}. Never raises: an unusable reply or a failed call → "skipped"."""
    log = log or (lambda *a: None)
    system, messages = build_messages(story)
    try:
        text = call(system, messages)
    except Exception as e:
        log(f"    ! story review unavailable — skipped: {str(e)[:120]}")
        return {"status": "skipped", "issues": [], "majors": 0, "minors": 0,
                "detail": f"review call failed: {str(e)[:200]}"}
    issues = parse(text, story)
    if issues is None:
        log("    ! story review returned an unreadable reply — skipped")
        return {"status": "skipped", "issues": [], "majors": 0, "minors": 0,
                "detail": "unreadable review reply"}
    majors = sum(1 for i in issues if i["severity"] == "major")
    return {"status": "REVIEW" if majors else "OK", "issues": issues, "majors": majors,
            "minors": len(issues) - majors, "detail": f"{majors} major, {len(issues) - majors} minor"}


def feedback_lines(result, limit=15):
    """Repair-loop feedback for the generator (major issues first)."""
    issues = sorted(result.get("issues", []), key=lambda i: i["severity"] != "major")
    out = []
    for i in issues[:limit]:
        where = i["location"] + (f' / "{i["choice"]}"' if i.get("choice") else "")
        out.append(f"[{i['severity']}/{i['type']}] {where}: {i['problem']}"
                   + (f" → fix: {i['fix']}" if i.get("fix") else ""))
    return out


def main(argv):
    if len(argv) < 2:
        sys.exit("usage: narrative_review.py <story.json>")
    import story_engine as E                    # lazy: story_engine imports this module
    with open(argv[1], encoding="utf-8") as f:
        story = json.load(f)
    usage = []
    res = E.run_review(story, usage_sink=usage, log=print)
    cost = sum(u["cost_usd"] for u in usage)
    print("=" * 66)
    print(f"  STORY REVIEW — {story.get('title', argv[1])}")
    print("=" * 66)
    for ln in feedback_lines(res, limit=50):
        print("  " + ln)
    print(f"\n  >>> REVIEW: {res['status']} ({res['detail']})  · ≈ ${cost:.4f}")
    sys.exit(0 if res["status"] in ("OK", "skipped") else 2)


if __name__ == "__main__":
    main(sys.argv)
