#!/bin/sh
# as-app — run a command as the unprivileged app user instead of root.
#
# The image's ENTRYPOINT starts Streamlit through this, and maintenance commands should use it too:
#     docker compose exec quest-book as-app python3 scripts/regenerate_library.py
#
# Which user: the owner of /app (the bind-mounted repo), so files the app writes keep the same
# owner as the checkout. If the checkout belongs to root, the app runs as QUEST_UID:QUEST_GID
# (default 1000:1000) and only the two folders it writes to — state/ and stories/ — are handed
# to that user. Nothing to prepare on the server.
set -e
[ "$(id -u)" = "0" ] || exec "$@"                      # already unprivileged
if ! command -v setpriv >/dev/null 2>&1; then
    echo "as-app: setpriv not found — running as root" >&2
    exec "$@"
fi
uid=$(stat -c %u /app 2>/dev/null || echo 0)
gid=$(stat -c %g /app 2>/dev/null || echo 0)
if [ "$uid" = "0" ]; then
    uid=${QUEST_UID:-1000}
    gid=${QUEST_GID:-1000}
fi
mkdir -p /app/state /app/stories 2>/dev/null || true
chown -R "$uid:$gid" /app/state /app/stories 2>/dev/null || true
export HOME=/tmp/quest-home
mkdir -p "$HOME" && chown "$uid:$gid" "$HOME" 2>/dev/null || true
exec setpriv --reuid "$uid" --regid "$gid" --clear-groups "$@"
