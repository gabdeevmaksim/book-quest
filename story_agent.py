#!/usr/bin/env python3
"""
story_agent.py — standalone Story-Smith for Quest Book.

Same orchestration as the `.claude/agents/story-smith.md` Claude Code agent, but as a plain
Python program you can run on any server with a **free Google Gemini API key** — no Claude
Code, no Anthropic, no paid API required.

It drafts a story with the model, then runs the project's own gates and feeds any failures
back to the model, looping until everything is green:

    draft  →  validate (links/reachability)  →  coherence (connectivity + pre-history)
           →  balance (difficulty band)  →  repair & repeat  →  save to stories/

If a model hits its free-tier limit mid-run, the agent automatically switches to the next
model in the chain (see --models / QUEST_GEN_MODELS).

Setup (once):
    pip install google-genai            # the only dependency the agent itself needs
    export GOOGLE_API_KEY=your_free_key # from https://aistudio.google.com/apikey

Usage:
    python3 story_agent.py "haunted circus" --difficulty hard
    python3 story_agent.py "cyberpunk heist" -d normal -n 16 -t "Neon Debt"
    python3 story_agent.py "norse myth" --models gemini-2.5-flash,gemini-2.5-flash-lite
    python3 story_agent.py --audit stories/the_banshee_s_wail.json -d hard   # gate an existing story

Run from the repository root. Exit code 0 = a fully game-ready story was produced / passed.
"""
import sys
import argparse

import story_engine as E


def audit(path, difficulty):
    print(f"Auditing {path} against '{difficulty}' …")
    ok, feedback, summary = E.gate_report(path, difficulty)
    print(f"  validate:{'OK' if summary['correctness'] else 'FAIL'}  "
          f"coherence:{'OK' if summary['coherence'] else 'REVIEW'}  balance:{summary['balance']}")
    for ln in summary["bal_lines"]:
        print("    " + ln)
    if ok:
        print("  >>> PASS — this story is game-ready.")
    else:
        print("  >>> NEEDS WORK:")
        for f in feedback:
            print("    - " + f)
    return ok


def main():
    ap = argparse.ArgumentParser(
        description="Generate (or audit) a fully game-ready Quest Book story using a free Gemini key.")
    ap.add_argument("theme", nargs="?", help="the setting, e.g. \"pirate ghost ship\"")
    ap.add_argument("-d", "--difficulty", default="normal", choices=E.DIFFICULTIES)
    ap.add_argument("-n", "--length", type=int, default=14, help="approx. number of locations")
    ap.add_argument("-t", "--title", default="", help="preferred title (optional)")
    ap.add_argument("-l", "--lang", default="English",
                    help='language of all story text, e.g. "Italian" (default: English)')
    ap.add_argument("--level", default="C2", choices=E.CEFR_LEVELS,
                    help="CEFR language level of the prose (default: C2 = native richness; "
                         "pick A2/B1 for language learning)")
    ap.add_argument("--provider", default=None, help="google | anthropic (default: auto-detect)")
    ap.add_argument("--models", default=None,
                    help="comma-separated fallback chain, e.g. gemini-3.5-flash,gemini-2.5-flash "
                         "(default: provider chain / QUEST_GEN_MODELS)")
    ap.add_argument("--max-attempts", type=int, default=6)
    ap.add_argument("--out", default=None, help="explicit output path (default: stories/<slug>.json)")
    ap.add_argument("--push", action="store_true",
                    help="after saving, git commit + push the story to the remote "
                         "(headless auth: set QUEST_GIT_TOKEN / GITHUB_TOKEN)")
    ap.add_argument("--save-draft", action="store_true",
                    help="if it can't pass all gates / a model limit is hit, save the best draft anyway (marked DRAFT)")
    ap.add_argument("--audit", default=None, metavar="STORY.json",
                    help="don't generate — just run the gates on an existing story and report")
    ap.add_argument("--s3-sync", action="store_true",
                    help="don't generate — two-way sync with the S3 bucket (QUEST_S3_BUCKET): "
                         "pull missing/newer stories down, upload local stories the bucket lacks")
    args = ap.parse_args()

    if args.s3_sync:
        if not E.s3_enabled():
            print("S3 storage is not configured — set QUEST_S3_BUCKET (and AWS credentials).")
            sys.exit(1)
        down, derr = E.sync_stories_from_s3()
        up, uerr = E.seed_s3_from_local()
        print(f"S3 sync: downloaded {down}, uploaded {up}")
        for e in derr + uerr:
            print("  ! " + e)
        sys.exit(0 if not (derr + uerr) else 2)

    if args.audit:
        sys.exit(0 if audit(args.audit, args.difficulty) else 2)

    if not args.theme:
        ap.error("a theme is required (or use --audit STORY.json)")

    provider = (args.provider or E.gen_provider()).lower()
    models = [m.strip() for m in args.models.split(",") if m.strip()] if args.models else E.gen_models(provider)
    api_key = E.env_api_key(provider)
    if not api_key:
        need = "GOOGLE_API_KEY (free tier)" if provider == "google" else "ANTHROPIC_API_KEY"
        print(f"No API key found for provider '{provider}'. Set {need} in the environment.")
        print("Free Gemini keys: https://aistudio.google.com/apikey")
        sys.exit(1)

    print(f"Story-Smith → theme={args.theme!r}  difficulty={args.difficulty}  "
          f"language={args.lang} ({args.level})  "
          f"provider={E.PROVIDER_LABEL.get(provider, provider)}")
    print(f"  model chain (auto-fallback on limit): {' → '.join(models)}")
    ok, path, summary = E.create_story(
        args.theme, args.difficulty, args.length, args.title, api_key,
        provider=provider, models=models, out_path=args.out,
        max_attempts=args.max_attempts, keep_best=args.save_draft, log=lambda *a: print(*a),
        language=args.lang, language_level=args.level)

    print()
    if path and E.s3_enabled():
        s3_ok, s3_detail = E.push_story_to_s3(path)
        print(("✓ s3: " if s3_ok else "✗ s3: ") + s3_detail)
    if path and args.push:
        pushed, detail = E.push_story_to_git(path)
        print(("✓ git: " if pushed else "✗ git: ") + detail)
    if ok:
        n = len(E.load_story_file(path).get("locations", {}))
        bal = "  ".join(summary["bal_lines"][:2])
        print(f"✓ DONE — {path}  ({n} locations)")
        print(f"  gates: validate OK · coherence OK · balance PASS   {bal}")
        print("  It now appears in the library on the main screen (streamlit run app.py).")
        sys.exit(0)
    elif path:   # --save-draft kept the best attempt
        n = len(E.load_story_file(path).get("locations", {}))
        print(f"~ DRAFT saved — {path}  ({n} locations) — did NOT pass every gate")
        print(f"  validate:{'OK' if summary['correctness'] else 'FAIL'}  "
              f"coherence:{'OK' if summary['coherence'] else 'REVIEW'}  balance:{summary['balance']}")
        if summary.get("limit_error"):
            print(f"  (stopped early — model limit: {str(summary['limit_error'])[:100]})")
        print("  It appears in the library marked DRAFT. Regenerate later for a clean version.")
        sys.exit(2)
    else:
        print("✗ Could not reach all-green within the attempt budget (and --save-draft was not set).")
        if summary:
            print(f"  last state: validate:{'OK' if summary['correctness'] else 'FAIL'}  "
                  f"coherence:{'OK' if summary['coherence'] else 'REVIEW'}  balance:{summary['balance']}")
        print("  Try again, raise --max-attempts, simplify the theme, or pass --save-draft to keep the best attempt.")
        sys.exit(2)


if __name__ == "__main__":
    main()
