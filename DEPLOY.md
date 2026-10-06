# Deploying Quest Book (CI/CD)

Push to `master` → GitHub Actions runs the tests → if green, it SSHes into the droplet,
pulls the code, rebuilds and restarts the container, and waits until the app is healthy.
No more logging in to pull and re-run.

- Workflow: `.github/workflows/deploy.yml` · droplet-side script: `scripts/deploy.sh`
- Pushes that only touch `stories/`, `docs/`, `*.md` or `FUNDING.yml` do **not** redeploy
  (stories are committed by the app itself on the droplet — redeploying would restart the game
  for everyone playing).
- Manual redeploy: GitHub → **Actions → CI / Deploy → Run workflow**.
- A failed test or failed health check turns the run red; the droplet keeps running the
  previous version if the pull or build fails.
- A deploy restarts the app, so anyone mid-game loses their run. Deploy when it's quiet.

## One-time setup

### 1. Prepare the droplet (SSH in once more — the last time)

```bash
# Compose v2 (the old docker-compose 1.x crashes with KeyError 'id' / 'ContainerConfig';
# the deploy script prefers v2 and only falls back to a slower build → down → up with 1.x).
# Package name depends on where Docker came from: Docker's repo → docker-compose-plugin,
# Ubuntu's docker.io → docker-compose-v2.
apt-get update && (apt-get install -y docker-compose-plugin || apt-get install -y docker-compose-v2)
docker compose version          # must print v2.x

cd /path/to/book-quest          # the folder the app runs from — this is DEPLOY_PATH
docker-compose down             # stop the v1-managed container once; CI starts it with v2
pwd                             # note this path
```

### 2. Create a deploy key (on your laptop)

A dedicated key that only GitHub Actions uses — not your personal SSH key.

```bash
ssh-keygen -t ed25519 -f ~/.ssh/questbook_deploy -N "" -C "github-actions-deploy"
ssh-copy-id -i ~/.ssh/questbook_deploy.pub root@134.122.120.45   # use your droplet user
ssh-keyscan -H 134.122.120.45                                    # copy the output for step 3
```

### 3. Add the secrets in GitHub

Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Value |
|---|---|
| `DEPLOY_HOST` | `134.122.120.45` |
| `DEPLOY_USER` | the droplet user (e.g. `root`) |
| `DEPLOY_PATH` | the path from step 1 |
| `DEPLOY_SSH_KEY` | the **private** key: contents of `~/.ssh/questbook_deploy` |
| `DEPLOY_KNOWN_HOSTS` | output of `ssh-keyscan` from step 2 (pins the droplet's identity) |
| `DOTENV` | *(optional)* the full contents of the droplet's `.env` |

**About `DOTENV`:** if set, every deploy writes it to the droplet as `.env` (permissions 600),
so GitHub becomes the single place where keys and settings live — change a key or
`QUEST_MONTHLY_BUDGET_USD` in GitHub, re-run the workflow, done. If you leave it unset, the
droplet's existing `.env` is kept as-is. Once you use it, edit settings **only** in GitHub —
manual edits on the droplet get overwritten by the next deploy.

### 4. First deploy

Push to `master` (or Actions → Run workflow) and watch the **Actions** tab. The first run
rebuilds the image from scratch (Python 3.12), so it takes a few minutes.

## Models: Gemini (paid Tier 1, with a monthly cap)

Generation and the story review run on Gemini Flash / Flash Lite. The book-quest project has
billing linked (**Tier 1**), which is the app's default. In the droplet's `.env` (or the
`DOTENV` secret):

```
GOOGLE_API_KEY=...
QUEST_GEN_PROVIDER=google
QUEST_GOOGLE_TIER=paid              # default; "free" = free-tier limits and $0 in the ledger
QUEST_BUDGET_CURRENCY=SEK           # show and set the budget in kronor
QUEST_USD_RATE=12.6                 # kr per US dollar — 10.07 (Oct 2026) × 1.25 VAT
QUEST_MONTHLY_BUDGET=150            # the app's own spend cap per calendar month, in kr (0 = none)
QUEST_GOOGLE_FREE_API_KEY=...       # key from a SECOND Google project WITHOUT billing (see below)
# QUEST_OVERLOAD_PATIENCE=60        # s the app waits out Google 503s on one model (scripts: 300)
```

Google prices models in USD and bills you in SEK at its own rate, so the app's figures are
estimates: keep the rate current-ish, and include VAT in it if your invoice has VAT on top.
(`QUEST_MONTHLY_BUDGET_USD` still works if you'd rather set dollars.)

**Free backup after the cap.** Billing is per *project*: a key from the billed project is never
free. So for the fallback create a second project in AI Studio (Get API key → Create API key in
a new project), don't link billing to it, and put its key in `QUEST_GOOGLE_FREE_API_KEY`. Once
the month's spend reaches the cap, new stories are written with that key on the free tier
(20 requests/day per Flash model, one story at a time); the Create page tells players stories
take longer and may be a little less polished until next month. Without that key, creation
pauses at the cap instead.

Remove any `QUEST_GEN_MODEL=claude-…` / `QUEST_GEN_PROVIDER=anthropic` lines from earlier — a
pinned model overrides the defaults.

**Cost.** Gemini 3.8 Flash costs $0.75 / $3.75 per million input / output tokens (doubling to
$1.50 / $7.50 on 1 Jan 2027 — update `MODEL_PRICING` in `story_engine.py` then). One story is
≈ $0.03–0.10 including repairs and the review. Every generation is added to the monthly ledger
(`state/usage.json`). When the month's spend reaches `QUEST_MONTHLY_BUDGET`, creation moves to
the free backup project (or pauses without one); the library stays playable. Google adds its
own Tier 1 ceiling of $250/month — also set a budget alert in Google Cloud Billing (in SEK) as a
backstop.

**Limits** (Tier 1, per project, daily reset at midnight Pacific): Flash 3.8/3.7/3.6/3.5 —
1000 req/min, 10 000/day each; Flash Lite — 4000/min, 150 000/day. In practice the limit you
hit is Google's own capacity: **503 "model overloaded"** answers. So:
- the app retries a 503/500 on the same model with growing pauses (≈5 → 10 → 20 s, up to
  `QUEST_OVERLOAD_PATIENCE`, 60 s) before stepping down the chain 3.8 → 3.7 → 3.6 → 3.5 → 2.5;
  `regenerate_library.py` / `story_agent.py` wait up to 5 min, since nobody is waiting on them;
- after 3 overload errors within 5 min a model is tried **last** for 3 min, so the next player
  starts on a healthy model instead of sitting through the same retries;
- players can generate in parallel; each can create `QUEST_STORIES_PER_PLAYER` stories per day
  (default 3), which also keeps one person from spending the budget.

Back on the free tier (`QUEST_GOOGLE_TIER=free`): 20 requests/day per Flash model, one
generation at a time, and the free chain keeps working after the budget cap.

First run after deploying, check that your key sees every model in the chains, then watch usage:

```bash
docker compose exec quest-book python3 quota.py check-models
docker compose exec quest-book python3 quota.py          # today's usage, budget, capacity
```

If a model shows `✗ NOT AVAILABLE`, it is skipped automatically (and marked off for the day the
first time it's tried); you can also drop it with `QUEST_GEN_MODELS=...`. If Google changes the
limits, update the tables in `quota.py` or set `QUEST_MODEL_LIMITS='{"gemini-3.8-flash":
{"rpm": 1000, "tpm": 2000000, "rpd": 10000}}'`. To write with a cheaper model, e.g.
`QUEST_GEN_MODELS=gemini-3.6-flash,gemini-2.5-flash`.

## Regenerating the library (after the Phase 3 deploy)

Stories created before the fail-forward rules still play (old `fail_target` routes are
honoured) but have no outcome texts or hinted dead ends. Rebuild them once, on the droplet:

```bash
cd /path/to/book-quest
# (wrap in sh -c "…": some docker compose versions swallow --flags meant for the script)
docker compose exec quest-book sh -c "python3 scripts/regenerate_library.py --dry-run"   # the plan
docker compose exec quest-book sh -c "python3 -u scripts/regenerate_library.py"         # do it (-u: live output)
docker compose exec quest-book sh -c "python3 scripts/regenerate_library.py --only dust_and_rust.json"
```

Before each story the script checks the monthly budget and today's request quota; if either
runs out it stops and prints the exact `--only …` command to resume. 7 stories cost roughly
$0.25–0.70 on Tier 1. It also waits its turn if a player is generating a story in the app.

Each story keeps its title, theme, difficulty, language and filename (shared links keep
working); the old version goes to `stories/_archive/`, and stays live if the new one fails a
gate — including the story review (a cheap-model continuity check; `QUEST_REVIEW=0` turns it
off). Cost is printed per story and counted in the monthly budget. New stories appear in the
running app immediately and are uploaded to S3; nothing is pushed to git.

## Player feedback (Telegram)

Feedback from the in-app form is always saved on the droplet in `state/feedback.jsonl`
(gitignored, survives deploys). To also get each message on Telegram instantly, add to `.env`
(or the `DOTENV` secret):

```
QUEST_TG_BOT_TOKEN=123456:ABC...     # from @BotFather
QUEST_TG_CHAT_ID=123456789           # from https://api.telegram.org/bot<TOKEN>/getUpdates
# QUEST_FEEDBACK_NOTIFY_PER_HOUR=30  # optional cap; extra feedback is still saved to the file
```

Read saved feedback on the droplet:

```bash
cd /path/to/book-quest
docker compose exec quest-book python3 feedback.py            # latest 20
docker compose exec quest-book sh -c "python3 feedback.py --kind bug -n 50"
```

## Visitor statistics

The app counts visits (one per browser session) and unique visitors (salted IP hash — no raw
IPs are stored) in `state/visits.db`. A small counter shows in the library footer
(`QUEST_SHOW_VISITS=0` hides it). Daily table:

```bash
docker-compose exec quest-book python3 visits.py              # last 14 days
docker-compose exec quest-book sh -c "python3 visits.py 60"   # last 60 days
```

## Security notes

- The deploy key can log in to the droplet — keep it only in GitHub Secrets. To revoke it,
  remove its line from `~/.ssh/authorized_keys` on the droplet.
- Set a spend limit in the Anthropic Console and restrict the Google API key to the
  Generative Language API — a backstop if a key ever leaks.
- Droplet: SSH-key login only, firewall open on 22/80/443 only (`ufw`).
