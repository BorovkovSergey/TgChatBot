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
rsync -az Dockerfile docker-compose.yml requirements.txt "$REMOTE:$REMOTE_DIR/"

echo "==> Building image"
ssh "$REMOTE" "cd $REMOTE_DIR && $DOCKER compose build --pull"

if ! ssh "$REMOTE" "test -f $REMOTE_DIR/.env"; then
    if [[ -f .env ]]; then
        echo "==> Copying local .env to the VPS"
        rsync -az .env "$REMOTE:$REMOTE_DIR/.env"
    else
        echo "ERROR: no .env on the VPS ($REMOTE_DIR/.env) and no local .env." >&2
        echo "Create one with BOT_TOKEN=... and rerun ./deploy.sh" >&2
        exit 1
    fi
fi

echo "==> Starting"
ssh "$REMOTE" "cd $REMOTE_DIR && $DOCKER compose up -d"

echo "==> Status"
ssh "$REMOTE" "cd $REMOTE_DIR && $DOCKER compose ps"
