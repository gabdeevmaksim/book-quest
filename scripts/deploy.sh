#!/usr/bin/env bash
# Quest Book deploy — runs ON the droplet.
#
# Normally invoked by .github/workflows/deploy.yml, which pipes the latest version of this
# script over SSH (so the droplet always runs the newest deploy logic):
#     ssh user@host "DEPLOY_PATH=/path/to/book-quest bash -s" < scripts/deploy.sh
# You can also run it by hand on the droplet:
#     DEPLOY_PATH=$PWD bash scripts/deploy.sh
#
# Steps: update code (keeping stories generated on this server) → install a new .env if the
# workflow uploaded one → rebuild + restart the container → wait until the app is healthy.
# Safe to re-run. Exits non-zero (and the GitHub run turns red) if anything fails.
set -euo pipefail

cd "${DEPLOY_PATH:?DEPLOY_PATH is not set}"
BRANCH="${DEPLOY_BRANCH:-master}"
git_() { git -c safe.directory='*' "$@"; }

echo "==> Updating code ($BRANCH)"
git_ checkout --quiet "$BRANCH"
# The app commits + pushes new stories from this server. If one of those commits hasn't reached
# GitHub yet, rebase keeps it on top of the new code instead of throwing it away.
if ! git_ pull --rebase --autostash --quiet origin "$BRANCH"; then
    git_ rebase --abort 2>/dev/null || true
    echo "!! git pull failed (conflict?) — the running app was left untouched." >&2
    exit 1
fi
ahead=$(git_ rev-list --count "origin/$BRANCH..HEAD")
if [ "$ahead" -gt 0 ]; then
    echo "   note: $ahead local story commit(s) not on GitHub yet — kept (the app pushes them)."
fi
echo "   now at $(git_ log -1 --format='%h %s')"

if [ -f .env.incoming ]; then
    echo "==> Installing .env from the DOTENV secret"
    chmod 600 .env.incoming
    mv -f .env.incoming .env
fi
[ -f .env ] || { echo "!! no .env on the server and no DOTENV secret set" >&2; exit 1; }
chmod 600 .env

# Prefer Compose v2 (`docker compose`); fall back to the legacy v1 binary if that's all there is.
if docker compose version >/dev/null 2>&1; then
    echo "==> Rebuilding + restarting (docker compose v2)"
    DC=(docker compose)
    "${DC[@]}" up -d --build --force-recreate --remove-orphans
else
    # Legacy docker-compose 1.x crashes with KeyError 'ContainerConfig' when it RECREATES a
    # container from an image built by a modern Docker Engine (and leaves the site down). So:
    # build first (old container keeps serving), then remove the old container and start fresh.
    echo "==> Rebuilding + restarting (legacy docker-compose v1 — please install Compose v2, see DEPLOY.md)"
    DC=(docker-compose)
    "${DC[@]}" build
    "${DC[@]}" down --remove-orphans
    "${DC[@]}" up -d
fi
docker image prune -f >/dev/null 2>&1 || true

echo "==> Waiting for the app to become healthy"
for _ in $(seq 1 45); do
    if "${DC[@]}" exec -T quest-book curl -fsS http://localhost:8501/_stcore/health >/dev/null 2>&1; then
        echo "==> Healthy — deploy complete."
        exit 0
    fi
    sleep 2
done
echo "!! The app did not become healthy within 90 s. Recent logs:" >&2
"${DC[@]}" logs --tail 60 quest-book >&2 || true
exit 1
