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
# Compose v2 (fixes the old `KeyError: 'id'` crash; the deploy script prefers it)
apt-get update && apt-get install -y docker-compose-plugin

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

## Security notes

- The deploy key can log in to the droplet — keep it only in GitHub Secrets. To revoke it,
  remove its line from `~/.ssh/authorized_keys` on the droplet.
- Set a spend limit in the Anthropic Console and restrict the Google API key to the
  Generative Language API — a backstop if a key ever leaks.
- Droplet: SSH-key login only, firewall open on 22/80/443 only (`ufw`).
