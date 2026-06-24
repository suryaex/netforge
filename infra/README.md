# NetForge — Infra (Database, Redis, DevOps)

Area ini milik **db-devops-architect**. Berisi lapisan data & deployment
NetForge: skema PostgreSQL, migrasi, desain Redis, Docker Compose (dev + prod),
image Docker, dan workflow CI/CD. Mengacu pada **MASTER_SPEC.md** (§2 stack,
§4 model data).

> Aturan tabrakan: file di sini HANYA ditulis oleh agent infra. Kebutuhan dari
> area lain (mis. backend butuh tabel baru) dicatat sebagai `NEEDS.md`.

## Isi direktori

```
infra/
├── README.md                 ← dokumen ini
├── .env.prod.example         ← contoh variabel produksi (salin -> .env.prod)
├── docker-compose.yml        ← stack DEV (hot-reload, port di-expose)
├── docker-compose.lan.yml    ← overlay gateway nginx :8090 (dipakai ../install.sh)
├── docker-compose.prod.yml   ← stack PROD (nginx, secret, resource limit, scale)
├── docker/
│   ├── backend.Dockerfile    ← image FastAPI (multi-stage, non-root, multi-arch)
│   ├── frontend.Dockerfile   ← image Vite build -> nginx
│   ├── nginx.conf            ← SPA fallback + reverse-proxy /api & /ws (prod)
│   └── nginx.lan.conf        ← gateway dev: proxy / -> Vite, /api & /ws -> backend
├── db/
│   ├── schema.sql            ← skema penuh (sumber-kebenaran, idempotent)
│   ├── ERD.md                ← entity-relationship diagram (Mermaid + as-text)
│   └── migrations/           ← migrasi SQL bernomor (0001 up/down + README)
├── redis-design.md           ← state realtime, pub/sub WS, job queue
└── ci/                       ← GitHub Actions (backend, frontend, images)
```

## Arsitektur data & deployment (as-text)

```
                        ┌──────────────────────────────────────┐
        Browser ──────► │  frontend (nginx :80, prod)           │
        (React 18)      │  /  -> static SPA                     │
                        │  /api -> proxy                        │
                        │  /ws  -> proxy (WebSocket upgrade)     │
                        └───────────────┬───────────────────────┘
                                        │  internal network
                         ┌──────────────▼───────────────┐
                         │  backend (FastAPI :8000)      │  (prod: replicas=2)
                         │  app.main:app (uvicorn)       │
                         │  REST /api/* + WS /ws/*        │
                         └───┬───────────────────┬───────┘
            asyncpg (truth)  │                   │  redis-py (hot/ephemeral)
                             ▼                   ▼
                   ┌──────────────────┐  ┌────────────────────────────────┐
                   │  PostgreSQL 16   │  │  Redis 7                        │
                   │  project/node/   │  │  rt: state node/link (Hash+TTL) │
                   │  iface/link/     │  │  ev: pub/sub fan-out WS         │
                   │  scenario/config │  │  q:  job queue sim/emul (Stream)│
                   │  simulation_run  │  │  lock: koordinasi               │
                   └──────────────────┘  └───────────────┬────────────────┘
                                                         │ XREADGROUP
                                          ┌──────────────▼───────────────┐
                                          │ (opsional) containerlab runner │
                                          │ mode 'emul' — boot NOS nyata   │
                                          └────────────────────────────────┘
```

Pembagian peran:
- **PostgreSQL** = sumber-kebenaran persisten (topologi, project, user, config,
  audit run). Lihat `db/schema.sql` & `db/ERD.md`.
- **Redis** = state realtime + bus pub/sub WS + antrian job. Lihat
  `redis-design.md`. (Backend WS saat ini in-process; Redis pub/sub adalah jalur
  fan-out saat di-scale ke banyak replica.)
- **Backend** = FastAPI async; tulis kebenaran ke Postgres, dorong state hot ke
  Redis, publish event ke WS.

## Model data (ringkas, sesuai §4)

| Entitas | Tabel | Catatan kunci |
|---|---|---|
| User | `app_user` | auth + RBAC; pemilik project |
| Project | `project` | `version` optimistic-lock, `topology_ref` JSONB |
| Node | `node` | kind/nos/mode/status enum, `config_ref`→artifact aktif |
| Interface | `iface` | `ip INET[]` (v4+v6), `peer_link_id`→link |
| Link | `link` | point-to-point 2 iface, bandwidth/delay/loss utk engine |
| Scenario | `scenario` | `steps`/`expected_outcomes` JSONB array |
| ConfigArtifact | `config_artifact` | append-only, 1 `is_active`/node, `source_intent` ForgeOS |
| (pendukung) | `simulation_run` | audit `/api/simulate`, state live di Redis |
| (pendukung) | `project_member` | kolaborasi multi-user + role |

## Menjalankan — satu perintah (direkomendasikan)

```bash
# Dari root repo netforge/ — install Docker bila perlu, build, start, tunggu health
./install.sh
```

Installer menambah gateway nginx (`docker-compose.lan.yml`) di depan stack DEV
agar seluruh app (frontend + `/api` + `/ws`) dapat diakses dari **satu origin**:

```
http://localhost:8090            (mesin ini)
http://<LAN-IP>:8090             (HP/PC lain di jaringan)
http://<LAN-IP>:8090/docs        (API docs)
http://<LAN-IP>:8090/api/health  (health)
```

Port **8090** dipilih agar tidak bentrok dengan SecureOps (`:80`) & StorageHub
(`:8080`) pada host yang sama. Override dengan `HTTP_PORT=9000 ./install.sh`.
Flag: `--prod` · `--rebuild` · `--down` · `--reset` · `--tailscale` · `--public`.
Uninstall: `./uninstall.sh` (`--purge` menghapus volume). Make: `make help`.

## Menjalankan — DEV (compose mentah)

```bash
# Dari root repo netforge/ (tanpa gateway LAN — port di-expose langsung)
docker compose -f infra/docker-compose.yml up -d

# Layanan:
#   frontend  http://localhost:5180   (Vite dev, hot-reload)
#   backend   http://localhost:8000   (FastAPI --reload)
#   postgres  localhost:5432          (netforge/netforge)
#   redis     localhost:6379

# Logs
docker compose -f infra/docker-compose.yml logs -f backend

# Stop
docker compose -f infra/docker-compose.yml down            # data tetap (volume)
docker compose -f infra/docker-compose.yml down -v         # HAPUS data (hati-hati)
```

Schema otomatis di-bootstrap dari `db/schema.sql` saat volume Postgres pertama
kali kosong. Untuk database existing, jalankan migrasi:

```bash
docker compose -f infra/docker-compose.yml exec -T postgres \
  psql -U netforge -d netforge -v ON_ERROR_STOP=1 < infra/db/migrations/0001_init.up.sql
```

## Menjalankan — PROD

```bash
cp infra/.env.prod.example infra/.env.prod      # lalu isi password & secret
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod up -d

# Hanya HTTP_PORT (default 80) yang di-expose; Postgres & Redis internal-only.
# Frontend nginx mem-proxy /api & /ws ke backend (single origin).
```

Mode emulasi (containerlab) opsional:

```bash
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod \
  --profile emul up -d
```

## Backup & restore (Postgres)

```bash
# Backup
docker compose -f infra/docker-compose.prod.yml exec -T postgres \
  pg_dump -U netforge -Fc netforge > netforge_$(date +%F).dump

# Restore (DESTRUKTIF — pastikan DB kosong/baru)
docker compose -f infra/docker-compose.prod.yml exec -T postgres \
  pg_restore -U netforge -d netforge --clean --if-exists < netforge_YYYY-MM-DD.dump
```

## Keputusan & asumsi

- **UUID v4** sebagai PK (server-side `gen_random_uuid()`) — aman terdistribusi,
  ramah client optimistik di canvas.
- **JSONB + GIN** untuk data graph/intent yang berevolusi (`topology_ref`,
  `attributes`, `steps`, `source_intent`).
- **Dua FK siklik** (`iface.peer_link_id`↔`link`, `node.config_ref`↔
  `config_artifact`) ditutup setelah kedua tabel ada; backend buat induk dulu
  lalu update pointer.
- **ConfigArtifact append-only** menjaga riwayat "satu intent → banyak target
  NOS" (ForgeOS, §5) untuk audit.
- **Healthcheck backend** diasumsikan `GET /api/health`. Bila berbeda, sesuaikan
  di `docker/backend.Dockerfile` dan compose.
- **Dockerfile** diletakkan di `infra/docker/` (bukan `backend/`,`frontend/`)
  karena area ini hanya boleh menulis di `infra/`; compose menunjuk ke sana via
  `build.dockerfile`.
- **CI** ada di `ci/`; orchestrator menautkannya ke `.github/workflows/`
  (GitHub hanya membaca workflow dari sana). Lihat `ci/README.md`.
