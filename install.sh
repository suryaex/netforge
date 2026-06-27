#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# NetForge — one-shot Docker installer (mirrors StorageHub / SecureOps)
# Auto-installs Docker (resilient on Fedora/WSL), generates .env, detects the
# LAN/Tailscale/public address, builds + starts the stack, opens the host
# firewall for the entry port (LAN + VPN), waits for health, and prints the
# reachable URLs. The compose files live in infra/, so this wrapper
# always invokes compose with the right -f paths from the repo root.
#
# Usage:
#   ./install.sh              # install Docker if needed, build + start (DEV + LAN gateway)
#   ./install.sh --prod       # use the production stack (immutable images, nginx, scale)
#   ./install.sh --rebuild    # force rebuild images (no cache)
#   ./install.sh --no-build   # start without rebuilding
#   ./install.sh --down       # stop the stack
#   ./install.sh --reset      # stop and DELETE all data (volumes)
#   ./install.sh --tailscale  # install + join Tailscale, use its VPN IP
#   ./install.sh --public     # auto-detect public IP and add it to CORS
# Env: HTTP_PORT=8090         (LAN/public HTTP entry — 8090 avoids SecureOps :80
#                              and StorageHub :8080 on a shared host)
#      PUBLIC_HOST=netforge.example.com   (public domain for CORS)
#      PUBLIC_IP=1.2.3.4                  (advertise a fixed public IP)
#
# Stack (infra/docker-compose.yml): postgres:5432 · redis:6379 ·
#   backend FastAPI:8000 · frontend Vite:5180. The installer adds an nginx
#   gateway (infra/docker-compose.lan.yml) so the whole app is reachable on one
#   port (HTTP_PORT). --prod uses infra/docker-compose.prod.yml instead.
#
# Docker install is resilient: if get.docker.com mirrors fail (common on Fedora)
# it falls back to the distro engine (Fedora 'moby-engine', Debian 'docker.io',
# last resort podman+podman-docker). On WSL it handles a missing systemd.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { echo -e "${BLUE}▸${NC} $*"; }
ok()    { echo -e "${GREEN}✓${NC} $*"; }
warn()  { echo -e "${YELLOW}!${NC} $*"; }
err()   { echo -e "${RED}✗${NC} $*" >&2; }

# ── Args ─────────────────────────────────────────────────────────────────────
ACTION="up"; PROD=0; TAILSCALE=0; PUBLIC_DETECT=0
for a in "$@"; do case "$a" in
  --down) ACTION="down" ;; --reset) ACTION="reset" ;;
  --rebuild) ACTION="rebuild" ;; --no-build) ACTION="nobuild" ;;
  --prod) PROD=1 ;;
  --tailscale) TAILSCALE=1 ;;
  --public) PUBLIC_DETECT=1 ;;
  -h|--help) sed -n '8,21p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
esac; done

# Host HTTP port — 8090 so NetForge does NOT collide with SecureOps (:80)
# or StorageHub (:8080) on a shared host.
HTTP_PORT="${HTTP_PORT:-8090}"
DOCKER_SUDO=""
COMPOSE=""

# Compose file paths (relative to repo root — we run from there).
DEV_CF="infra/docker-compose.yml"
LAN_CF="infra/docker-compose.lan.yml"
PROD_CF="infra/docker-compose.prod.yml"
ENV_FILE="infra/.env.prod"   # only used for --prod

is_wsl() { grep -qiE 'microsoft|wsl' /proc/version 2>/dev/null; }

pkgmgr() {
  if   command -v dnf     >/dev/null 2>&1; then echo dnf
  elif command -v apt-get >/dev/null 2>&1; then echo apt
  elif command -v zypper  >/dev/null 2>&1; then echo zypper
  elif command -v pacman  >/dev/null 2>&1; then echo pacman
  elif command -v yum     >/dev/null 2>&1; then echo yum
  else echo ""; fi
}

start_docker_daemon() {
  # systemd → sysv service → background dockerd (WSL without systemd)
  sudo systemctl enable --now docker >/dev/null 2>&1 && return 0
  sudo service docker start >/dev/null 2>&1 && return 0
  if command -v dockerd >/dev/null 2>&1 && ! pgrep -x dockerd >/dev/null 2>&1; then
    info "Starting dockerd in background (no systemd)…"
    sudo sh -c 'nohup dockerd >/tmp/dockerd.log 2>&1 &'
    sleep 4
  fi
  return 0
}

install_docker() {
  local pm; pm="$(pkgmgr)"
  # 1) upstream convenience script — best when download.docker.com mirrors are healthy
  info "Installing Docker via get.docker.com…"
  if curl -fsSL https://get.docker.com | sudo sh >/dev/null 2>&1 && command -v docker >/dev/null 2>&1; then
    return 0
  fi
  warn "get.docker.com failed (mirror/network) — falling back to distro packages…"
  # 2) distro-native engine. On Fedora/RHEL 'moby-engine' lives in the main repos.
  case "$pm" in
    dnf|yum)
      sudo "$pm" install -y --setopt=retries=10 --skip-broken moby-engine 2>/dev/null \
        || sudo "$pm" install -y --setopt=retries=10 --skip-broken docker 2>/dev/null || true
      sudo "$pm" install -y --skip-broken docker-compose 2>/dev/null \
        || sudo "$pm" install -y --skip-broken moby-compose 2>/dev/null || true
      ;;
    apt)
      sudo apt-get update -y || true
      sudo apt-get install -y docker.io 2>/dev/null || true
      sudo apt-get install -y docker-compose-v2 2>/dev/null \
        || sudo apt-get install -y docker-compose 2>/dev/null || true
      ;;
    zypper)  sudo zypper --non-interactive install docker docker-compose 2>/dev/null || true ;;
    pacman)  sudo pacman -Sy --noconfirm docker docker-compose 2>/dev/null || true ;;
  esac
  command -v docker >/dev/null 2>&1 && return 0
  # 3) last resort: podman with the docker shim (Fedora ships these)
  case "$pm" in
    dnf|yum) sudo "$pm" install -y podman podman-docker 2>/dev/null || true ;;
  esac
  command -v docker >/dev/null 2>&1
}

ensure_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    if [ "$(uname -s)" != "Linux" ]; then
      err "Docker is not installed. Install Docker Desktop: https://docs.docker.com/get-docker/"; exit 1
    fi
    if is_wsl; then
      warn "WSL detected — the smoothest path is Docker Desktop with WSL integration"
      warn "  (Docker Desktop → Settings → Resources → WSL integration → enable this distro)."
      warn "Trying to install a Docker engine inside WSL as a fallback…"
    fi
    if ! install_docker; then
      err "Could not install Docker automatically (mirror/network issue). Choose one:"
      err "  1) Install Docker Desktop + enable WSL integration, then re-run ./install.sh"
      err "  2) Install Docker manually: https://docs.docker.com/engine/install/"
      exit 1
    fi
    sudo usermod -aG docker "$(id -un)" 2>/dev/null || true
  fi

  start_docker_daemon
  if docker info >/dev/null 2>&1; then DOCKER_SUDO="";
  elif sudo docker info >/dev/null 2>&1; then DOCKER_SUDO="sudo";
  else
    start_docker_daemon
    if docker info >/dev/null 2>&1; then DOCKER_SUDO="";
    elif sudo docker info >/dev/null 2>&1; then DOCKER_SUDO="sudo";
    else
      err "Docker daemon not available."
      if is_wsl; then
        err "WSL without systemd — enable it: add to /etc/wsl.conf →  [boot]\\n    systemd=true"
        err "then run 'wsl --shutdown' in Windows and reopen. Or use Docker Desktop integration."
      fi
      exit 1
    fi
  fi
}

detect_compose() {
  if $DOCKER_SUDO docker compose version >/dev/null 2>&1; then COMPOSE="$DOCKER_SUDO docker compose"; return 0; fi
  if command -v docker-compose >/dev/null 2>&1; then COMPOSE="$DOCKER_SUDO docker-compose"; return 0; fi
  warn "Docker Compose not found — attempting install…"
  case "$(pkgmgr)" in
    apt)     sudo apt-get update -y && sudo apt-get install -y docker-compose-plugin 2>/dev/null || sudo apt-get install -y docker-compose 2>/dev/null || true ;;
    dnf|yum) sudo "$(pkgmgr)" install -y --skip-broken docker-compose moby-compose 2>/dev/null || true ;;
    zypper)  sudo zypper --non-interactive install docker-compose 2>/dev/null || true ;;
    pacman)  sudo pacman -Sy --noconfirm docker-compose 2>/dev/null || true ;;
  esac
  if $DOCKER_SUDO docker compose version >/dev/null 2>&1; then COMPOSE="$DOCKER_SUDO docker compose"
  elif command -v docker-compose >/dev/null 2>&1; then COMPOSE="$DOCKER_SUDO docker-compose"
  else err "Could not get Docker Compose. Install it and retry."; exit 1; fi
}

rand() {
  if command -v openssl >/dev/null 2>&1; then openssl rand -hex "${1:-24}";
  else head -c "${1:-24}" /dev/urandom | od -An -tx1 | tr -d ' \n'; fi
}
# ── Windows-host network (only meaningful under WSL) ─────────────────────────
# Under WSL the address other devices can actually reach is the *Windows host's*,
# not WSL's internal NAT (172.x) or the distro's own tailscale node. Ask Windows
# for the truth via interop (powershell.exe / tailscale.exe).
win_default_ip() {
  command -v powershell.exe >/dev/null 2>&1 || return 0
  powershell.exe -NoProfile -Command "(Get-NetIPConfiguration | Where-Object { \$_.IPv4DefaultGateway -ne \$null } | Select-Object -First 1 -ExpandProperty IPv4Address).IPAddress" 2>/dev/null | tr -d '\r\n '
}
win_ts_ip() {
  if command -v tailscale.exe >/dev/null 2>&1; then
    tailscale.exe ip -4 2>/dev/null | head -n1 | tr -d '\r\n '; return 0
  fi
  command -v powershell.exe >/dev/null 2>&1 || return 0
  powershell.exe -NoProfile -Command "(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { \$_.IPAddress -like '100.*' } | Select-Object -First 1 -ExpandProperty IPAddress)" 2>/dev/null | tr -d '\r\n '
}
wsl_eth0_ip() { ip -4 -o addr show eth0 2>/dev/null | awk '{sub(/\/.*/,"",$4); print $4; exit}'; }

lan_ip() {
  local ip=""
  # In WSL, the reachable LAN IP is the Windows host's default-route address.
  if is_wsl; then ip="$(win_default_ip)"; [ -n "$ip" ] && { echo "$ip"; return; }; fi
  if command -v ip >/dev/null 2>&1; then ip="$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}')"; fi
  [ -z "$ip" ] && command -v hostname >/dev/null 2>&1 && ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  [ -z "$ip" ] && command -v ipconfig >/dev/null 2>&1 && ip="$(ipconfig getifaddr en0 2>/dev/null || true)"
  echo "${ip:-127.0.0.1}"
}
# Tailscale (VPN) IPv4. In WSL mirrored networking the *Windows host* runs its own
# tailscaled and its 100.64/10 address is mirrored onto the WSL NIC (eth0); remote
# peers reach services running in WSL via THAT Windows-host node. The distro's own
# tailscale0 node is a second peer on the same physical uplink that peers can't
# hairpin to (it shows reachable only from inside WSL). So in WSL prefer a
# 100.64/10 address that is NOT on tailscale0; otherwise fall back to this node's
# own tailscale IP.
ts_ip() {
  if is_wsl; then
    # Prefer the *Windows host* tailscale node — that's the peer remote devices
    # reach; the distro's own tailscale0 (a second node on the same machine)
    # only answers from inside WSL and must not be advertised.
    local w; w="$(win_ts_ip)"; [ -n "$w" ] && { echo "$w"; return 0; }
    local m
    m="$(ip -4 -o addr show 2>/dev/null | awk '$2!="tailscale0" && $4 ~ /^100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\./ {sub(/\/.*/,"",$4); print $4; exit}')"
    [ -n "$m" ] && { echo "$m"; return 0; }
  fi
  command -v tailscale >/dev/null 2>&1 && tailscale ip -4 2>/dev/null | head -n1 || true
}
pub_ip() { curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || curl -fsS --max-time 5 https://ifconfig.me 2>/dev/null || true; }

# Open the host firewall for the HTTP entry port so other devices reach NetForge
# over the LAN *and* the VPN (tailscale0) interface. Without this, a healthy
# stack still times out from a phone/PC because firewalld/ufw drops the SYN.
# Best-effort and idempotent: handles firewalld (Fedora/RHEL), ufw (Debian/
# Ubuntu), then nftables/iptables. Silent no-op if no active firewall or no sudo.
open_firewall() {
  local port="$1" opened=""
  if command -v firewall-cmd >/dev/null 2>&1 && sudo firewall-cmd --state >/dev/null 2>&1; then
    sudo firewall-cmd --permanent --add-port="${port}/tcp" >/dev/null 2>&1 || true
    sudo firewall-cmd --reload >/dev/null 2>&1 || true
    opened="firewalld"
  elif command -v ufw >/dev/null 2>&1 && sudo ufw status 2>/dev/null | grep -qi active; then
    sudo ufw allow "${port}/tcp" >/dev/null 2>&1 || true
    opened="ufw"
  elif command -v nft >/dev/null 2>&1 && sudo nft list ruleset >/dev/null 2>&1; then
    sudo nft add rule inet filter input tcp dport "${port}" accept >/dev/null 2>&1 || true
    opened="nftables"
  elif command -v iptables >/dev/null 2>&1; then
    sudo iptables -C INPUT -p tcp --dport "${port}" -j ACCEPT >/dev/null 2>&1 \
      || sudo iptables -I INPUT -p tcp --dport "${port}" -j ACCEPT >/dev/null 2>&1 || true
    opened="iptables"
  fi
  [ -n "$opened" ] && ok "Opened TCP ${port} for LAN + VPN in the host firewall (${opened})"
}

# WSL2 + mirrored networking: the stack is reachable on the *Windows* host's LAN
# IP, but the WSL Hyper-V firewall blocks inbound by default — so phones/PCs on
# the LAN time out even though the app is healthy. Add a one-time Windows firewall
# rule for HTTP_PORT (Hyper-V rule for the WSL vNIC + a host rule), the same
# mechanism the sibling apps rely on. Needs one UAC approval; no-op outside WSL,
# outside mirrored mode, or if the rule already exists. (NAT-mode WSL would need a
# netsh portproxy instead — out of scope; use --tailscale for remote access there.)
WSL_VMCREATOR='{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}'   # fixed WSL VM creator id
setup_wsl_firewall() {
  is_wsl || return 0
  command -v powershell.exe >/dev/null 2>&1 || { warn "WSL detected but powershell.exe not on PATH — open TCP ${1} on Windows manually"; return 0; }
  local port="$1"
  # Branch on networking mode. Mirrored: WSL shares the host's IPs, so a Hyper-V
  # firewall rule is enough. NAT (the default): the stack sits behind WSL's NAT,
  # so the Windows host also needs a netsh portproxy into WSL's eth0 — without it
  # the host LAN/Tailscale IP has no path in and times out (the bug this fixes).
  local mirrored=0
  powershell.exe -NoProfile -Command "if((Get-Content \$env:USERPROFILE\\.wslconfig -ErrorAction SilentlyContinue) -match 'networkingMode\\s*=\\s*mirrored'){exit 0}else{exit 1}" >/dev/null 2>&1 && mirrored=1

  if [ "$mirrored" = "1" ]; then
    if powershell.exe -NoProfile -Command "if(Get-NetFirewallHyperVRule -Name 'NetForge-${port}' -ErrorAction SilentlyContinue){exit 0}else{exit 1}" >/dev/null 2>&1; then
      ok "Windows firewall already allows TCP ${port} into WSL (LAN ready)"; return 0
    fi
    info "WSL mirrored networking — adding a Windows firewall rule for TCP ${port} (approve the UAC prompt)…"
    local ps enc
    ps="New-NetFirewallHyperVRule -Name 'NetForge-${port}' -DisplayName 'NetForge ${port} (WSL LAN)' -Direction Inbound -VMCreatorId '${WSL_VMCREATOR}' -Protocol TCP -LocalPorts ${port} -Action Allow -ErrorAction SilentlyContinue; New-NetFirewallRule -DisplayName 'NetForge ${port}' -Direction Inbound -Action Allow -Protocol TCP -LocalPort ${port} -Profile Any -ErrorAction SilentlyContinue"
    enc="$(powershell.exe -NoProfile -Command "[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes('${ps}'))" 2>/dev/null | tr -d '\r')"
    if [ -n "$enc" ] && powershell.exe -NoProfile -Command "Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile','-EncodedCommand','${enc}'" >/dev/null 2>&1; then
      ok "Windows firewall rule added — NetForge reachable from the LAN on the host IP:${port}"
    else
      warn "Could not add the Windows firewall rule automatically (UAC declined?). Run this in an elevated PowerShell:"
      warn "  New-NetFirewallHyperVRule -Name 'NetForge-${port}' -DisplayName 'NetForge ${port}' -Direction Inbound -VMCreatorId '${WSL_VMCREATOR}' -Protocol TCP -LocalPorts ${port} -Action Allow"
    fi
    return 0
  fi

  # NAT mode (default): forward Windows :port → WSL eth0:port, then open the
  # Windows firewall. Re-created each run because WSL's NAT IP can change.
  local wsl_ip; wsl_ip="$(wsl_eth0_ip)"
  [ -z "$wsl_ip" ] && { warn "WSL NAT mode but couldn't read eth0 IP — add a portproxy + open TCP ${port} on Windows manually."; return 0; }
  info "WSL NAT networking — forwarding Windows :${port} → WSL ${wsl_ip}:${port} (approve the UAC prompt)…"
  local ps enc
  ps="netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=${port} 2>\$null | Out-Null; netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=${port} connectaddress=${wsl_ip} connectport=${port}; New-NetFirewallRule -DisplayName 'NetForge ${port}' -Direction Inbound -Action Allow -Protocol TCP -LocalPort ${port} -Profile Any -ErrorAction SilentlyContinue"
  enc="$(powershell.exe -NoProfile -Command "[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes('${ps}'))" 2>/dev/null | tr -d '\r')"
  if [ -n "$enc" ] && powershell.exe -NoProfile -Command "Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile','-EncodedCommand','${enc}'" >/dev/null 2>&1; then
    ok "Windows portproxy + firewall set — NetForge reachable on the host LAN/VPN IP:${port}"
    warn "WSL's NAT IP can change after a reboot — re-run ./install.sh to refresh the portproxy."
  else
    warn "Could not set the portproxy automatically (UAC declined?). Run this in an elevated PowerShell:"
    warn "  netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=${port} connectaddress=${wsl_ip} connectport=${port}"
    warn "  New-NetFirewallRule -DisplayName 'NetForge ${port}' -Direction Inbound -Action Allow -Protocol TCP -LocalPort ${port} -Profile Any"
  fi
}

# Comma-join http origins for every non-empty host on :HTTP_PORT (+ localhost dev ports).
build_origins() {
  local p=":${HTTP_PORT}" out h
  out="http://localhost${p},http://localhost:5180,http://localhost:3000"
  for h in "$IP" "$TSIP" "$PUBIP"; do
    [ -n "$h" ] && out="${out},http://${h}${p}"
  done
  if [ -n "$PUBLIC_HOST" ]; then
    out="${out},http://${PUBLIC_HOST}${p},http://${PUBLIC_HOST},https://${PUBLIC_HOST}"
  fi
  echo "$out"
}

# In-place sed against an arbitrary file (GNU + BSD compatible).
sed_if() { if sed --version >/dev/null 2>&1; then sed -i "$1" "$2"; else sed -i '' "$1" "$2"; fi; }

# Compose file selection: --prod uses the production stack, otherwise DEV + LAN gateway.
if [ "$PROD" = "1" ]; then
  CF="-f ${PROD_CF}"
else
  CF="-f ${DEV_CF} -f ${LAN_CF}"
fi
# --env-file for prod (POSTGRES_PASSWORD/SECRET_KEY live there).
ENVOPT=""
[ "$PROD" = "1" ] && [ -f "$ENV_FILE" ] && ENVOPT="--env-file ${ENV_FILE}"

# ── Subcommands ──────────────────────────────────────────────────────────────
if [ "$ACTION" = "down" ]; then
  ensure_docker; detect_compose; info "Stopping…"
  HTTP_PORT="$HTTP_PORT" $COMPOSE $ENVOPT $CF down; ok "Stopped."; exit 0
fi
if [ "$ACTION" = "reset" ]; then
  ensure_docker; detect_compose; warn "This deletes ALL data (Postgres + Redis volumes)!"
  read -r -p "Type 'yes' to continue: " c
  if [ "$c" = "yes" ]; then HTTP_PORT="$HTTP_PORT" $COMPOSE $ENVOPT $CF down -v && ok "Reset done."; else echo "Aborted."; fi
  exit 0
fi

echo ""
echo "  ╭───────────────────────────────────────────────╮"
echo "  │  NetForge · network simulation & emulation     │"
echo "  ╰───────────────────────────────────────────────╯"
echo ""

ensure_docker
detect_compose
ok "Docker ready  ($COMPOSE)"
[ "$PROD" = "1" ] && ok "Production stack enabled (docker-compose.prod.yml)" \
                  || ok "Development stack + LAN gateway (nginx on :${HTTP_PORT})"

IP="$(lan_ip)"
ok "Detected LAN address: ${IP}"

# VPN (Tailscale) — install on --tailscale, then use its IP (like the siblings)
if [ "$TAILSCALE" = "1" ] && ! command -v tailscale >/dev/null 2>&1; then
  info "Installing Tailscale…"; curl -fsSL https://tailscale.com/install.sh | sh || warn "Tailscale install failed (continuing)"
  command -v tailscale >/dev/null 2>&1 && { sudo tailscale up 2>/dev/null || warn "Run 'sudo tailscale up' then re-run with --tailscale"; }
fi
TSIP="$(ts_ip)";   [ -n "$TSIP" ] && ok "Tailscale IP: ${TSIP}"
PUBIP=""; [ "$PUBLIC_DETECT" = "1" ] && { PUBIP="$(pub_ip)"; [ -n "$PUBIP" ] && ok "Public IP: ${PUBIP}"; }
[ -n "${PUBLIC_IP:-}" ] && PUBIP="$PUBLIC_IP"     # explicit override
PUBLIC_HOST="${PUBLIC_HOST:-}"                    # optional public domain

CORS="$(build_origins)"

# ── 1. Environment files ─────────────────────────────────────────────────────
# Backend .env (used when running the backend outside Docker; harmless to keep
# aligned). Generated from backend/.env.example with a fresh SECRET_KEY.
if [ -f backend/.env.example ]; then
  if [ -f backend/.env ]; then
    ok "backend/.env exists — keeping secrets, aligning CORS/URLs"
  else
    info "Creating backend/.env with a generated SECRET_KEY…"
    cp backend/.env.example backend/.env
    sed_if "s|^SECRET_KEY=.*|SECRET_KEY=$(rand 32)|" backend/.env
    ok "backend/.env created (SECRET_KEY generated)"
  fi
  grep -q '^CORS_ORIGINS=' backend/.env && sed_if "s|^CORS_ORIGINS=.*|CORS_ORIGINS=${CORS}|" backend/.env \
                                        || echo "CORS_ORIGINS=${CORS}" >> backend/.env
fi

# Frontend .env.local (single-origin via the gateway in dev; usually unset).
if [ -f frontend/.env.example ] && [ ! -f frontend/.env.local ]; then
  cp frontend/.env.example frontend/.env.local
  ok "frontend/.env.local created from example"
fi

# Production env-file (only for --prod): generate secrets once from the example.
if [ "$PROD" = "1" ]; then
  if [ ! -f "$ENV_FILE" ] && [ -f infra/.env.prod.example ]; then
    info "Creating ${ENV_FILE} with generated secrets…"
    cp infra/.env.prod.example "$ENV_FILE"
    sed_if "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(rand 18)|" "$ENV_FILE"
    sed_if "s|^SECRET_KEY=.*|SECRET_KEY=$(rand 32)|" "$ENV_FILE"
    ok "${ENV_FILE} created (POSTGRES_PASSWORD + SECRET_KEY generated)"
  fi
  if [ -f "$ENV_FILE" ]; then
    grep -q '^HTTP_PORT=' "$ENV_FILE" && sed_if "s|^HTTP_PORT=.*|HTTP_PORT=${HTTP_PORT}|" "$ENV_FILE" \
                                      || echo "HTTP_PORT=${HTTP_PORT}" >> "$ENV_FILE"
    grep -q '^CORS_ORIGINS=' "$ENV_FILE" && sed_if "s|^CORS_ORIGINS=.*|CORS_ORIGINS=${CORS}|" "$ENV_FILE" \
                                         || echo "CORS_ORIGINS=${CORS}" >> "$ENV_FILE"
    ENVOPT="--env-file ${ENV_FILE}"
  fi
fi
ok "Reachable via: localhost / LAN ${IP}${TSIP:+ / Tailscale ${TSIP}}${PUBIP:+ / public ${PUBIP}}"

# ── 2. Build & start ─────────────────────────────────────────────────────────
case "$ACTION" in
  rebuild) HTTP_PORT="$HTTP_PORT" $COMPOSE $ENVOPT $CF build --no-cache; BUILD="--build" ;;
  nobuild) BUILD="" ;;
  *)       BUILD="--build" ;;
esac
info "Building & starting containers (HTTP entry on port ${HTTP_PORT})…"
HTTP_PORT="$HTTP_PORT" $COMPOSE $ENVOPT $CF up -d $BUILD

# Make the entry port reachable from other devices (LAN + Tailscale VPN).
open_firewall "$HTTP_PORT"
setup_wsl_firewall "$HTTP_PORT"

# ── 3. Wait for backend health (via the single-origin HTTP entry) ────────────
info "Waiting for backend to become healthy…"
HEALTHY=0
for _ in $(seq 1 60); do
  if curl -fsS "http://localhost:${HTTP_PORT}/api/health" >/dev/null 2>&1; then ok "Backend is healthy"; HEALTHY=1; break; fi
  sleep 3; printf "."
done
echo ""
[ "$HEALTHY" = "1" ] || warn "Backend not healthy yet — check logs: $COMPOSE $CF logs -f backend"

# ── 4. Done ──────────────────────────────────────────────────────────────────
echo ""
ok "NetForge is up!"
echo ""
echo -e "  ${GREEN}On this machine${NC}     →  http://localhost:${HTTP_PORT}"
echo -e "  ${GREEN}On the network${NC}      →  http://${IP}:${HTTP_PORT}   (open from phone/other PCs)"
[ -n "$TSIP" ]  && echo -e "  ${GREEN}Over Tailscale VPN${NC}  →  http://${TSIP}:${HTTP_PORT}"
[ -n "$PUBIP" ] && echo -e "  ${GREEN}Public IP${NC}           →  http://${PUBIP}:${HTTP_PORT}   (open the port in your firewall/router)"
echo -e "  ${GREEN}API docs${NC}            →  http://${IP}:${HTTP_PORT}/docs"
echo -e "  ${GREEN}Health${NC}              →  http://${IP}:${HTTP_PORT}/api/health"
echo ""
echo "  TCP ${HTTP_PORT} is auto-opened in the host firewall; if a device still can't"
echo "  reach it, check your router/cloud security group allows TCP ${HTTP_PORT}."
echo "  Logs: $COMPOSE $CF logs -f   |   Stop: ./install.sh --down${PROD:+  (--prod)}"
echo ""
