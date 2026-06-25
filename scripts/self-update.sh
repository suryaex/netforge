#!/usr/bin/env bash
#
# NetForge self-update — the single, auditable script the in-app updater runs.
#
# It pulls the latest released tag (or the configured branch), rebuilds the
# Docker images, and restarts the stack. The backend never executes anything
# else: POST /api/update/apply only triggers *this* file.
#
#   scripts/self-update.sh --check     # print current vs latest, exit
#   scripts/self-update.sh --apply     # pull + rebuild + restart (default)
#   scripts/self-update.sh --watch     # poll for the trigger file, then --apply
#
# Env:
#   GITHUB_REPO         owner/name to compare releases against (default: suryaex/netforge)
#   UPDATE_BRANCH       branch to fast-forward when no tag is targeted (default: main)
#   UPDATE_TRIGGER_FILE sentinel written by the backend (default: /var/lib/netforge/update.request)
#   UPDATE_STATUS_FILE  progress file the UI reads     (default: /var/lib/netforge/update.status)
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GITHUB_REPO="${GITHUB_REPO:-suryaex/netforge}"
UPDATE_BRANCH="${UPDATE_BRANCH:-main}"
UPDATE_TRIGGER_FILE="${UPDATE_TRIGGER_FILE:-/var/lib/netforge/update.request}"
UPDATE_STATUS_FILE="${UPDATE_STATUS_FILE:-/var/lib/netforge/update.status}"

log()    { printf '[self-update] %s\n' "$*" >&2; }
status() { # state, message
  mkdir -p "$(dirname "$UPDATE_STATUS_FILE")" 2>/dev/null || true
  printf '{"state":"%s","message":"%s","at":%s}\n' "$1" "${2:-}" "$(date +%s)" \
    > "$UPDATE_STATUS_FILE" 2>/dev/null || true
}

# Pick the compose invocation this host supports.
compose() {
  if docker compose version >/dev/null 2>&1; then docker compose "$@";
  elif command -v docker-compose >/dev/null 2>&1; then docker-compose "$@";
  else log "Docker Compose not found"; return 127; fi
}

# Locate the right compose file (prod preferred), relative to the repo root.
compose_file() {
  for f in infra/docker-compose.prod.yml docker-compose.prod.yml \
           infra/docker-compose.yml docker-compose.yml; do
    [ -f "$REPO_DIR/$f" ] && { echo "$f"; return 0; }
  done
  return 1
}

latest_tag() {
  # Newest release tag from GitHub; empty on failure.
  curl -fsSL -H 'Accept: application/vnd.github+json' \
    "https://api.github.com/repos/${GITHUB_REPO}/releases/latest" 2>/dev/null \
    | sed -n 's/.*"tag_name":[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1
}

do_check() {
  local current latest
  current="$(git -C "$REPO_DIR" describe --tags --abbrev=0 2>/dev/null || echo "unknown")"
  latest="$(latest_tag)"
  printf 'current=%s latest=%s\n' "$current" "${latest:-<unreachable>}"
}

do_apply() {
  cd "$REPO_DIR"
  status "updating" "Fetching latest source"
  log "Fetching from origin…"
  git fetch --tags --prune origin

  local tag cf
  tag="$(latest_tag 2>/dev/null || true)"
  if [ -n "${tag:-}" ] && git rev-parse "refs/tags/${tag}" >/dev/null 2>&1; then
    log "Checking out release ${tag}"
    git checkout -q "tags/${tag}"
  else
    log "No release tag reachable; fast-forwarding ${UPDATE_BRANCH}"
    git checkout -q "${UPDATE_BRANCH}"
    git merge --ff-only "origin/${UPDATE_BRANCH}"
  fi

  cf="$(compose_file)" || { status "error" "No compose file found"; log "No compose file"; exit 1; }
  log "Rebuilding images via ${cf}…"
  status "rebuilding" "Building updated images"
  compose -f "$cf" build

  log "Restarting stack…"
  status "restarting" "Recreating containers"
  compose -f "$cf" up -d

  status "done" "Updated to ${tag:-${UPDATE_BRANCH}} and restarted"
  log "Update complete."
  # Consume the trigger so we don't loop.
  rm -f "$UPDATE_TRIGGER_FILE" 2>/dev/null || true
}

do_watch() {
  log "Watching ${UPDATE_TRIGGER_FILE} for update requests… (Ctrl-C to stop)"
  while true; do
    if [ -f "$UPDATE_TRIGGER_FILE" ]; then
      log "Trigger detected."
      do_apply || status "error" "Update failed — see logs"
    fi
    sleep 15
  done
}

case "${1:---apply}" in
  --check) do_check ;;
  --apply) do_apply ;;
  --watch) do_watch ;;
  *) echo "usage: $0 [--check|--apply|--watch]" >&2; exit 2 ;;
esac
