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

## Models: free-tier Gemini

Generation and the story review run on the Gemini API **free tier**. In the droplet's `.env`
(or the `DOTENV` secret) you only need:

```
GOOGLE_API_KEY=...
QUEST_GEN_PROVIDER=google
# QUEST_GOOGLE_TIER=free            # default — Gemini calls count as $0 in the budget ledger
```

Remove any `QUEST_GEN_MODEL=claude-…` / `QUEST_GEN_PROVIDER=anthropic` lines from earlier — a
pinned model overrides the defaults. Google may use free-tier prompts to improve its products.

**Free-tier limits and how the app stays inside them** (AI Studio → Rate limit, per project,
reset at midnight Pacific): every Flash model allows 5 requests/min and **20/day**; Flash Lite
3.5/3.1 allow 15/min and 500/day. So:
- stories are written by rotating through the Flash models (3.8 → 3.7 → 3.6 → 3.5 → 3 → 2.5,
  ≈120 calls/day ≈ 40 stories at ~3 calls each), and reviewed by Flash Lite;
- `quota.py` counts every call, waits briefly when a per-minute window is full, skips a model
  once its day is used up, and learns from real 429s;
- only one story is generated at a time — other players queue for a couple of minutes;
- each player can create `QUEST_STORIES_PER_PLAYER` stories per day (default 3);
- the Create page shows "≈ N stories can still be created today · resets in X", and pauses
  creation (library stays playable) when it reaches 0.

First run after deploying, check that your key sees every model in the chains, then watch usage:

```bash
docker compose exec quest-book python3 quota.py check-models
docker compose exec quest-book python3 quota.py          # today's usage + capacity
```

If a model shows `✗ NOT AVAILABLE`, it is skipped automatically (and marked off for the day the
first time it's tried); you can also drop it with `QUEST_GEN_MODELS=...`. If Google changes the
limits, update the table in `quota.py` or set `QUEST_MODEL_LIMITS='{"gemini-3.8-flash":
{"rpm": 5, "tpm": 250000, "rpd": 20}}'`. To write with a lower model, e.g.
`QUEST_GEN_MODELS=gemini-3.5-flash,gemini-2.5-flash`.

## Regenerating the library (after the Phase 3 deploy)

Stories created before the fail-forward rules still play (old `fail_target` routes are
honoured) but have no outcome texts or hinted dead ends. Rebuild them once, on the droplet:

```bash
cd /path/to/book-quest
# (wrap in sh -c "…": some docker compose versions swallow --flags meant for the script)
docker compose exec quest-book sh -c "python3 scripts/regenerate_library.py --dry-run"   # the plan
docker compose exec quest-book sh -c "python3 scripts/regenerate_library.py"            # do it
docker compose exec quest-book sh -c "python3 scripts/regenerate_library.py --only dust_and_rust.json"
```

On the free tier the script checks today's capacity before each story; when it runs out it
stops and prints the exact `--only …` command to resume after midnight Pacific (7 stories ≈
20–30 writer calls, so it usually fits in one day). It also waits its turn if a player is
generating a story in the app at the same moment.

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

## Security notes

- The deploy key can log in to the droplet — keep it only in GitHub Secrets. To revoke it,
  remove its line from `~/.ssh/authorized_keys` on the droplet.
- Set a spend limit in the Anthropic Console and restrict the Google API key to the
  Generative Language API — a backstop if a key ever leaks.
- Droplet: SSH-key login only, firewall open on 22/80/443 only (`ufw`).
