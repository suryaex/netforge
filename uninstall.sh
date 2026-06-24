#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# NetForge — uninstaller (Docker stack)
#
# Run before a major update or to switch versions.
#
# Usage:
#   bash uninstall.sh           # stop + remove containers, KEEP data (volumes)
#   bash uninstall.sh --purge   # ALSO delete Postgres + Redis data (volumes/images)
#   bash uninstall.sh --yes     # no confirmation prompt
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail
cd "$(dirname "$0")"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
say()  { echo -e "${GREEN}==> $*${NC}"; }
warn() { echo -e "${YELLOW}!! $*${NC}"; }

PURGE=0; ASSUME_YES=0
for a in "$@"; do case "$a" in
  --purge) PURGE=1 ;;
  --yes|-y) ASSUME_YES=1 ;;
esac; done

if [[ "$ASSUME_YES" != "1" ]]; then
  echo "This will stop and remove NetForge from this machine."
  [[ "$PURGE" == "1" ]] && echo -e "${RED}--purge: the database (Postgres), Redis data and Docker volumes will be DELETED.${NC}"
  read -r -p "Type 'yes' to continue: " c; [[ "$c" == "yes" ]] || { echo "Aborted."; exit 0; }
fi

# Compose files live in infra/ — cover dev (+LAN gateway) and prod stacks.
DEV_CF="infra/docker-compose.yml"
LAN_CF="infra/docker-compose.lan.yml"
PROD_CF="infra/docker-compose.prod.yml"
HTTP_PORT="${HTTP_PORT:-8090}"

COMPOSE=""
if docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"
elif sudo docker compose version >/dev/null 2>&1; then COMPOSE="sudo docker compose"
elif command -v docker-compose >/dev/null 2>&1; then COMPOSE="docker-compose"; fi

if [[ -z "$COMPOSE" ]]; then warn "Docker Compose not found — nothing to stop."; say "NetForge uninstall complete."; exit 0; fi

DOWN_FLAGS="--remove-orphans"
[[ "$PURGE" == "1" ]] && DOWN_FLAGS="$DOWN_FLAGS -v"

# Production stack (uses infra/.env.prod if present).
if [[ -f "$PROD_CF" ]]; then
  say "Stopping production stack (if running)…"
  ENVOPT=""; [[ -f infra/.env.prod ]] && ENVOPT="--env-file infra/.env.prod"
  HTTP_PORT="$HTTP_PORT" $COMPOSE $ENVOPT -f "$PROD_CF" down $DOWN_FLAGS 2>/dev/null || true
fi

# Development stack + LAN gateway overlay.
if [[ -f "$DEV_CF" ]]; then
  say "Stopping development stack + LAN gateway (if running)…"
  CF="-f $DEV_CF"; [[ -f "$LAN_CF" ]] && CF="$CF -f $LAN_CF"
  HTTP_PORT="$HTTP_PORT" $COMPOSE $CF down $DOWN_FLAGS 2>/dev/null || true
fi

if [[ "$PURGE" == "1" ]]; then
  warn "Docker volumes (pgdata, redisdata, frontend_node_modules) deleted."
else
  say "Volumes kept (pgdata, redisdata). Use --purge to delete them."
fi

say "NetForge uninstall complete."
