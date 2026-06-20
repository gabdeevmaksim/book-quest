#!/usr/bin/env python3
"""compare_models.py — cost-effectiveness benchmark for Quest Book story generation.

Generates the SAME theme with each model, R times each, running the full
draft -> validate -> coherence -> balance pipeline, and tabulates which model gives the
best $ per *successful* story (not just $ per token) — the number that actually decides
which model is most cost-effective, because a cheap model that needs extra repair passes
can cost more than a strong one that passes first try.

Needs the relevant API keys in the environment (ANTHROPIC_API_KEY and/or GOOGLE_API_KEY).
This calls the real APIs and costs real money on paid models — keep --runs small.
It does NOT count toward the app's monthly budget ledger (this is a benchmark).

Run from the repo root:

    python3 compare_models.py "haunted circus" -d hard \
        --models claude-sonnet-4-6,claude-opus-4-8,gemini-3.5-flash --runs 3
"""
import argparse
import time

import story_engine as E


def provider_for(model):
    return "anthropic" if model.startswith("claude") else "google"


def run_once(theme, difficulty, length, model, max_attempts):
    """One full generation with a single pinned model. Returns a metrics dict."""
    provider = provider_for(model)
    key = E.env_api_key(provider)
    if not key:
        need = "ANTHROPIC_API_KEY" if provider == "anthropic" else "GOOGLE_API_KEY"
        return {"pre_error": f"no API key for provider '{provider}' (set {need})"}
    t0 = time.time()
    try:
        ok, path, summary = E.create_story(
            theme, difficulty, length, "", key, provider=provider, models=[model],
            max_attempts=max_attempts, keep_best=False)
    except Exception as e:
        return {"ok": False, "secs": time.time() - t0, "attempts": 0,
                "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "err": str(e)[:120]}
    s = summary or {}
    return {"ok": bool(ok), "secs": time.time() - t0,
            "attempts": s.get("attempts", 0),
            "tokens_in": s.get("tokens_in", 0), "tokens_out": s.get("tokens_out", 0),
            "cost_usd": s.get("cost_usd", 0.0), "balance": s.get("balance", "—")}


def main():
    ap = argparse.ArgumentParser(
        description="Benchmark model cost-effectiveness for Quest Book story generation.")
    ap.add_argument("theme", help='the setting, e.g. "haunted circus"')
    ap.add_argument("-d", "--difficulty", default="normal", choices=E.DIFFICULTIES)
    ap.add_argument("-n", "--length", type=int, default=14, help="approx. number of locations")
    ap.add_argument("--models", required=True,
                    help="comma-separated model list, e.g. claude-sonnet-4-6,gemini-3.5-flash")
    ap.add_argument("--runs", type=int, default=3, help="generations per model (default 3)")
    ap.add_argument("--max-attempts", type=int, default=5)
    args = ap.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    print(f"Benchmark: theme={args.theme!r}  difficulty={args.difficulty}  "
          f"length~{args.length}  runs/model={args.runs}\n")

    rows = []
    for model in models:
        print(f"=== {model} ===")
        runs = []
        for i in range(args.runs):
            r = run_once(args.theme, args.difficulty, args.length, model, args.max_attempts)
            if "pre_error" in r:
                print(f"  skipped: {r['pre_error']}")
                break
            tag = "PASS" if r["ok"] else "fail"
            extra = f"  ! {r['err']}" if r.get("err") else ""
            print(f"  run {i + 1}: {tag}  {r['attempts']} call(s)  "
                  f"{r['tokens_in']}+{r['tokens_out']} tok  ${r['cost_usd']:.4f}  "
                  f"{r['secs']:.0f}s{extra}")
            runs.append(r)
        if runs:
            rows.append((model, runs))
        print()

    if not rows:
        print("No runs completed — check that the API keys for your chosen models are set.")
        return

    # ── summary table ──
    W = 100
    print("=" * W)
    print(f"  {'model':28s} {'runs':>4} {'pass%':>6} {'avg calls':>9} "
          f"{'avg in/out tok':>16} {'$/run':>9} {'$/success':>11} {'avg s':>6}")
    print("-" * W)
    best = None
    for model, runs in rows:
        n = len(runs)
        succ = [r for r in runs if r["ok"]]
        total_cost = sum(r["cost_usd"] for r in runs)
        passpct = 100.0 * len(succ) / n
        avg_calls = sum(r["attempts"] for r in runs) / n
        avg_in = sum(r["tokens_in"] for r in runs) / n
        avg_out = sum(r["tokens_out"] for r in runs) / n
        per_run = total_cost / n
        per_succ = (total_cost / len(succ)) if succ else None
        avg_s = sum(r["secs"] for r in runs) / n
        per_succ_str = f"${per_succ:.4f}" if per_succ is not None else "n/a"
        print(f"  {model:28s} {n:>4} {passpct:>5.0f}% {avg_calls:>9.1f} "
              f"{int(avg_in):>7}/{int(avg_out):<8} ${per_run:>8.4f} {per_succ_str:>11} {avg_s:>6.0f}")
        if per_succ is not None and (best is None or per_succ < best[1]):
            best = (model, per_succ)
    print("=" * W)
    if best:
        print(f"  Most cost-effective (lowest $/successful story): {best[0]} at ${best[1]:.4f}/story.")
    print("  Tip: weigh $/success against pass% and speed — a model that never passes has no $/success.")


if __name__ == "__main__":
    main()
