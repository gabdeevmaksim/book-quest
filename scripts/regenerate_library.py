#!/usr/bin/env python3
"""
regenerate_library.py — rebuild existing library stories under the current rules
(every challenge passable with outcome texts, hinted dead ends, calibrated difficulty presets).

Each story is regenerated with the SAME title, theme, difficulty, language/level and FILENAME,
so shared `?story=` links keep working. It goes through the full gated pipeline
(story_engine.create_story: draft → validate → coherence → balance, with repair). Before that,
the old version is copied to stories/_archive/<name>.<date>.json. If a story can't pass every
gate, the old version stays in place untouched.

Run it ON THE DROPLET, inside the app container (it has the API keys and the git push config):

    docker compose exec quest-book python3 scripts/regenerate_library.py --dry-run
    docker compose exec quest-book python3 scripts/regenerate_library.py --push
    docker compose exec quest-book python3 scripts/regenerate_library.py --only dust_and_rust.json --push

The running app picks up regenerated stories immediately (it reads stories/ from disk).
Story commits don't trigger a redeploy (stories/ is ignored by the CI/CD workflow).
"""
import argparse
import json
import os
import shutil
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)                               # story_engine uses repo-relative paths

import story_engine as E  # noqa: E402

ARCHIVE_DIR = os.path.join(E.STORIES_DIR, "_archive")


def plan(paths, length_override=None):
    out = []
    for p in paths:
        with open(p, encoding="utf-8") as f:
            s = json.load(f)
        n = len(s.get("locations", {}))
        out.append({
            "path": p, "file": os.path.basename(p),
            "title": s.get("title") or os.path.basename(p),
            "theme": s.get("theme") or s.get("title") or "adventure",
            "difficulty": (s.get("difficulty") or "normal").lower(),
            "language": s.get("language") or "English",
            "level": s.get("language_level") or "C2",
            "length": length_override or max(10, min(24, n)),
            "old_locations": n,
        })
    return out


def archive(path):
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    stem = os.path.splitext(os.path.basename(path))[0]
    dest = os.path.join(ARCHIVE_DIR, f"{stem}.{time.strftime('%Y%m%d-%H%M%S')}.json")
    shutil.copy2(path, dest)
    return dest


def keep_identity(path, item):
    """The model may tweak the title/theme; restore them so the library card stays the same."""
    with open(path, encoding="utf-8") as f:
        s = json.load(f)
    s["title"], s["theme"] = item["title"], item["theme"]
    E.save_story_file(s, path)


def main():
    ap = argparse.ArgumentParser(description="Regenerate library stories under the current rules.")
    ap.add_argument("--only", nargs="+", metavar="FILE", help="only these story files (basename)")
    ap.add_argument("--dry-run", action="store_true", help="show the plan, generate nothing")
    ap.add_argument("--push", action="store_true", help="git commit + push each regenerated story")
    ap.add_argument("--max-attempts", type=int, default=5)
    ap.add_argument("--length", type=int, default=None, help="override target size (locations)")
    ap.add_argument("--ignore-budget", action="store_true",
                    help="run even if this month's QUEST_MONTHLY_BUDGET_USD is already used up")
    args = ap.parse_args()

    paths = [s["path"] for s in E.list_stories() if not s.get("error")]
    if args.only:
        wanted = {os.path.basename(x) for x in args.only}
        paths = [p for p in paths if os.path.basename(p) in wanted]
        missing = wanted - {os.path.basename(p) for p in paths}
        if missing:
            sys.exit(f"not in the library: {', '.join(sorted(missing))}")
    if not paths:
        sys.exit("no stories to regenerate")

    items = plan(paths, args.length)
    provider = E.gen_provider()
    models = E.gen_models(provider)
    print(f"Regenerating {len(items)} stor{'y' if len(items) == 1 else 'ies'} with "
          f"{E.PROVIDER_LABEL.get(provider, provider)} — models: {' → '.join(models)}")
    for it in items:
        print(f"  • {it['file']:44s} {it['difficulty']:6s} {it['language']} ({it['level']}) "
              f"· {it['old_locations']} → ~{it['length']} locations · “{it['title']}”")
    if args.dry_run:
        print("\n(dry run — nothing generated)")
        return

    key = E.env_api_key(provider)
    if not key:
        sys.exit(f"No API key for provider '{provider}' in the environment.")
    if E.budget_exceeded() and not args.ignore_budget:
        sys.exit(f"This month's generation budget (${E.monthly_budget():.2f}) is already used up "
                 f"(${E.month_spend():.2f}). Raise QUEST_MONTHLY_BUDGET_USD or pass --ignore-budget.")

    results, total, not_started = [], 0.0, []
    for i, it in enumerate(items, 1):
        cap = E.Q.capacity(models, E.review_models(provider))
        if provider == "google" and cap["stories"] < 1:   # free tier: stop before wasting calls
            not_started = items[i - 1:]
            print(f"\n■ Today's free-tier quota is used up ({cap['writer_left']} writer calls left, "
                  f"≈ {cap['avg_writer']} needed per story). It resets in {cap['resets_in_text']} "
                  f"(midnight Pacific).")
            break
        print(f"\n[{i}/{len(items)}] {it['title']}  ({it['difficulty']}, {it['language']})"
              + (f"  · free tier: ≈ {cap['stories']} stories left today" if provider == "google" else ""))
        with E.Q.generation_slot(timeout=1800) as got:   # wait if a player is generating in the app
            if not got:
                print("    ✗ another generation has held the slot for 30 min — stopping")
                not_started = items[i - 1:]
                break
            backup = archive(it["path"])
            print(f"    old version archived → {backup}")
            try:
                ok, path, summary = E.create_story(
                    it["theme"], it["difficulty"], it["length"], it["title"], key,
                    provider=provider, models=models, out_path=it["path"],
                    max_attempts=args.max_attempts, keep_best=False, log=print,
                    language=it["language"], language_level=it["level"])
            except Exception as e:                      # API down / every model failed
                print(f"    ✗ generation stopped: {str(e)[:200]} — old version kept")
                results.append((it, False, 0.0))
                continue
        summary = summary or {}
        cost = float(summary.get("cost_usd") or 0.0)
        total += cost
        E.record_spend(cost, summary.get("model_used", ""),
                       summary.get("tokens_in", 0), summary.get("tokens_out", 0))
        if ok:
            keep_identity(path, it)
            print(f"    ✓ regenerated — {summary.get('attempts', '?')} model call(s), ≈ ${cost:.3f}")
            if args.push:
                pushed, detail = E.push_story_to_git(path)
                print(("    ✓ git: " if pushed else "    ✗ git: ") + detail)
            if E.s3_enabled():
                s3_ok, detail = E.push_story_to_s3(path)
                print(("    ✓ s3: " if s3_ok else "    ✗ s3: ") + detail)
        else:
            print(f"    ✗ didn't pass every gate (validate:{summary.get('correctness')} "
                  f"coherence:{summary.get('coherence')} balance:{summary.get('balance')} "
                  f"story-review:{summary.get('review')}) — old version kept, ≈ ${cost:.3f} spent")
        results.append((it, ok, cost))

    print("\n" + "=" * 70)
    for it, ok, cost in results:
        print(f"  {'✓' if ok else '✗'} {it['file']:44s} ≈ ${cost:.3f}")
    done = sum(1 for _, ok, _ in results if ok)
    print(f"  {done}/{len(results)} regenerated · total ≈ ${total:.2f}")
    failed = [it["file"] for it, ok, _ in results if not ok]
    if failed:
        print("  Failed (old version kept): " + ", ".join(failed))
    if not_started:
        print(f"  Not started today: {', '.join(x['file'] for x in not_started)}")
    rest = failed + [x["file"] for x in not_started]
    if rest:
        print(f"  Resume (after the reset if the quota ran out):\n"
              f"    python3 scripts/regenerate_library.py --only {' '.join(rest)}"
              + (" --push" if args.push else ""))
    sys.exit(0 if not rest else 2)


if __name__ == "__main__":
    main()
