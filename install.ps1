# ─────────────────────────────────────────────────────────────────────────────
# NetForge — one-shot installer for Windows (Docker, LAN-ready, single origin)
# The compose files live in infra/, so this wrapper invokes compose with the
# right -f paths from the repo root.
#
# Usage (PowerShell):
#   .\install.ps1            # build + start the DEV stack + LAN gateway (:8090)
#   .\install.ps1 -Prod      # use the production stack (immutable images, nginx)
#   .\install.ps1 -Rebuild   # force rebuild images (no cache)
#   .\install.ps1 -NoBuild   # start without rebuilding
#   .\install.ps1 -Down      # stop the stack
#   .\install.ps1 -Reset     # stop and DELETE all data (volumes)
# Env: $env:HTTP_PORT (default 8090 — avoids SecureOps :80 / StorageHub :8080)
# ─────────────────────────────────────────────────────────────────────────────
[CmdletBinding()]
param([switch]$Rebuild, [switch]$Down, [switch]$Reset, [switch]$NoBuild, [switch]$Prod)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Info($m){ Write-Host "> $m" -ForegroundColor Blue }
function Ok($m)  { Write-Host "+ $m" -ForegroundColor Green }
function Warn($m){ Write-Host "! $m" -ForegroundColor Yellow }
function Fail($m){ Write-Host "x $m" -ForegroundColor Red; exit 1 }

# Host HTTP port — 8090 so NetForge does not collide with SecureOps (:80) or
# StorageHub (:8080) on a shared host.
$HttpPort = if ($env:HTTP_PORT) { $env:HTTP_PORT } else { "8090" }
$env:HTTP_PORT = $HttpPort

# ── Ensure Docker (auto-install Docker Desktop via winget if missing) ────────
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Warn "Docker not found"
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Info "Installing Docker Desktop via winget…"
        winget install -e --id Docker.DockerDesktop --silent --accept-package-agreements --accept-source-agreements
    }
    Fail "Docker Desktop installed/needed — start Docker Desktop, then re-run .\install.ps1"
}
try { docker info *> $null } catch { Fail "Docker daemon is not running. Start Docker Desktop and retry." }

$Compose = "docker compose"
try { docker compose version *> $null } catch {
    if (Get-Command docker-compose -ErrorAction SilentlyContinue) { $Compose = "docker-compose" } else { Fail "Docker Compose not found." }
}

# Compose file selection: -Prod uses the production stack, else DEV + LAN gateway.
if ($Prod) {
    $Cf = "-f infra/docker-compose.prod.yml"
    if (Test-Path "infra/.env.prod") { $Cf = "$Cf --env-file infra/.env.prod" }
} else {
    $Cf = "-f infra/docker-compose.yml -f infra/docker-compose.lan.yml"
}
function Invoke-Compose([string]$ArgString) { Invoke-Expression "$Compose $Cf $ArgString" }

if ($Down)  { Info "Stopping NetForge…"; Invoke-Compose "down"; Ok "Stopped."; exit 0 }
if ($Reset) {
    Warn "This deletes ALL data (Postgres + Redis volumes)!"
    if ((Read-Host "Type 'yes' to continue") -eq "yes") { Invoke-Compose "down -v"; Ok "Reset done." } else { Write-Host "Aborted." }
    exit 0
}

Write-Host ""
Write-Host "  +-----------------------------------------------+"
Write-Host "  |  NetForge - network simulation & emulation    |"
Write-Host "  +-----------------------------------------------+"
Write-Host ""
Ok "Docker ready  ($Compose)"
if ($Prod) { Ok "Production stack enabled (docker-compose.prod.yml)" }
else       { Ok "Development stack + LAN gateway (nginx on :$HttpPort)" }

function New-Secret([int]$Bytes = 24) {
    $b = New-Object 'System.Byte[]' $Bytes
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
    return -join ($b | ForEach-Object { $_.ToString('x2') })
}
function Get-LanIp {
    try {
        $ip = (Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -ne $null -and $_.NetAdapter.Status -eq 'Up' } |
               Select-Object -First 1).IPv4Address.IPAddress
        if ($ip) { return $ip }
    } catch {}
    try {
        $ip = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
               Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.)' } |
               Select-Object -First 1).IPAddress
        if ($ip) { return $ip }
    } catch {}
    return "127.0.0.1"
}

$Ip = Get-LanIp
Ok "Detected LAN address: $Ip"
$Cors = "http://localhost:$HttpPort,http://localhost:5180,http://localhost:3000,http://${Ip}:$HttpPort"

# ── 1. Environment files ─────────────────────────────────────────────────────
if (Test-Path "backend/.env.example") {
    if (-not (Test-Path "backend/.env")) {
        Info "Creating backend/.env with a generated SECRET_KEY…"
        Copy-Item "backend/.env.example" "backend/.env"
        $c = Get-Content "backend/.env" -Raw
        $c = $c -replace '(?m)^SECRET_KEY=.*', "SECRET_KEY=$(New-Secret 32)"
    } else {
        Ok "backend/.env exists — keeping secrets, aligning CORS"
        $c = Get-Content "backend/.env" -Raw
    }
    $c = $c -replace '(?m)^CORS_ORIGINS=.*', "CORS_ORIGINS=$Cors"
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText((Join-Path $PSScriptRoot "backend\.env"), $c, $utf8NoBom)
}
if ((Test-Path "frontend/.env.example") -and (-not (Test-Path "frontend/.env.local"))) {
    Copy-Item "frontend/.env.example" "frontend/.env.local"
    Ok "frontend/.env.local created from example"
}

# Production env-file (only for -Prod): generate secrets once from the example.
if ($Prod) {
    if ((-not (Test-Path "infra/.env.prod")) -and (Test-Path "infra/.env.prod.example")) {
        Info "Creating infra/.env.prod with generated secrets…"
        Copy-Item "infra/.env.prod.example" "infra/.env.prod"
        $p = Get-Content "infra/.env.prod" -Raw
        $p = $p -replace '(?m)^POSTGRES_PASSWORD=.*', "POSTGRES_PASSWORD=$(New-Secret 18)"
        $p = $p -replace '(?m)^SECRET_KEY=.*',        "SECRET_KEY=$(New-Secret 32)"
        $p = $p -replace '(?m)^HTTP_PORT=.*',         "HTTP_PORT=$HttpPort"
        $p = $p -replace '(?m)^CORS_ORIGINS=.*',      "CORS_ORIGINS=$Cors"
        $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::WriteAllText((Join-Path $PSScriptRoot "infra\.env.prod"), $p, $utf8NoBom)
        Ok "infra/.env.prod created (POSTGRES_PASSWORD + SECRET_KEY generated)"
    }
}

# ── 2. Build & start ─────────────────────────────────────────────────────────
if ($Rebuild) { Info "Rebuilding images (no cache)…"; Invoke-Compose "build --no-cache" }
$buildFlag = if ($NoBuild) { "" } else { "--build" }
Info "Building & starting containers (HTTP entry on port $HttpPort)…"
Invoke-Compose "up -d $buildFlag"

# ── 3. Wait for backend health ───────────────────────────────────────────────
Info "Waiting for backend to become healthy…"
$healthy = $false
for ($i = 0; $i -lt 60; $i++) {
    try { Invoke-RestMethod -Uri "http://localhost:$HttpPort/api/health" -TimeoutSec 3 *> $null; $healthy = $true; break }
    catch { Start-Sleep -Seconds 3; Write-Host "." -NoNewline }
}
Write-Host ""
if ($healthy) { Ok "Backend is healthy" } else { Warn "Backend not healthy yet — run: $Compose $Cf logs -f backend" }

# ── 4. Done ──────────────────────────────────────────────────────────────────
Write-Host ""
Ok "NetForge is up!"
Write-Host ""
Write-Host "  On this machine  ->  http://localhost:$HttpPort"                    -ForegroundColor Green
Write-Host "  On the network   ->  http://${Ip}:$HttpPort        (phone/other PCs)" -ForegroundColor Green
Write-Host "  API docs         ->  http://${Ip}:$HttpPort/docs"                   -ForegroundColor Green
Write-Host "  Health           ->  http://${Ip}:$HttpPort/api/health"            -ForegroundColor Green
Write-Host ""
Write-Host "  If other devices can't reach it, allow TCP port $HttpPort in Windows Firewall:"
Write-Host "    New-NetFirewallRule -DisplayName 'NetForge' -Direction Inbound -LocalPort $HttpPort -Protocol TCP -Action Allow"
Write-Host "  Logs: $Compose $Cf logs -f   |   Stop: .\install.ps1 -Down"
Write-Host ""
