#!/usr/bin/env bash
# Deploy TgChatBot to the VPS: sync sources, rebuild the image, restart the
# container. Requires an ssh alias (default "vps") and docker on the remote.
# The container has restart: unless-stopped, and the docker daemon is enabled,
# so the bot comes back up on VPS reboots by itself.
set -euo pipefail

REMOTE="${REMOTE:-vps}"
REMOTE_DIR="tgchatbot"
DOCKER="sudo docker"

cd "$(dirname "$0")"

echo "==> Syncing sources to $REMOTE:$REMOTE_DIR"
# data/ must exist before compose bind-mounts it, otherwise docker creates it
# root-owned and the non-root container user cannot write settings
ssh "$REMOTE" "mkdir -p $REMOTE_DIR/data"
rsync -az --delete --exclude '__pycache__' bot "$REMOTE:$REMOTE_DIR/"
# .dockerignore keeps data/ and .env out of the remote build context
rsync -az Dockerfile docker-compose.yml requirements.lock .dockerignore "$REMOTE:$REMOTE_DIR/"

# The VPS .env is the source of truth: a local .env is copied ONCE as a
# bootstrap and never synced afterwards — edit the token on the VPS.
# .env must exist before any compose command: compose validates env_file
# while loading the config, so even `build` fails without it.
# Distinguish "file missing" from "ssh failed": the command itself always
# succeeds, set -e aborts only on a transport error.
env_state=$(ssh "$REMOTE" "if test -f $REMOTE_DIR/.env; then echo present; else echo missing; fi")
if [[ "$env_state" == "missing" ]]; then
    if [[ -f .env ]]; then
        echo "==> Copying local .env to the VPS"
        rsync -az .env "$REMOTE:$REMOTE_DIR/.env"
    else
        echo "ERROR: no .env on the VPS ($REMOTE_DIR/.env) and no local .env." >&2
        echo "Create one with BOT_TOKEN=... and rerun ./deploy.sh" >&2
        exit 1
    fi
fi

echo "==> Building image"
ssh "$REMOTE" "cd $REMOTE_DIR && $DOCKER compose build --pull"

echo "==> Starting"
ssh "$REMOTE" "cd $REMOTE_DIR && $DOCKER compose up -d"

# Drop dangling (untagged) image layers left behind by rebuilds. Does not
# touch tagged or in-use images of other projects.
ssh "$REMOTE" "$DOCKER image prune -f >/dev/null"

echo "==> Status"
ssh "$REMOTE" "cd $REMOTE_DIR && $DOCKER compose ps"
