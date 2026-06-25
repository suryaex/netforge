<div align="center">

# 🛠️ NetForge

**Platform open-source simulasi & emulasi jaringan skala besar**

*Kemudahan Cisco Packet Tracer · kedalaman GNS3/EVE-NG · manajemen visual ala Ubiquiti UISP —*
*dengan UI desktop-class (rasa macOS / Windows 11) yang tetap seringan aplikasi Linux native.*

[![CI](https://github.com/suryaex/netforge/actions/workflows/backend.yml/badge.svg)](https://github.com/suryaex/netforge/actions)
![Lisensi](https://img.shields.io/badge/license-Apache--2.0-blue)
![Python](https://img.shields.io/badge/python-3.12-blue)
![React](https://img.shields.io/badge/react-18-61dafb)

</div>

---

## ✨ Apa itu NetForge?

NetForge mensimulasikan jaringan **ribuan node** (router, switch, host, AP, OLT, firewall) memakai
**engine hybrid**: *discrete-event simulation* (DES) yang ringan untuk skala, plus *container
emulation* (containerlab/Docker) untuk akurasi NOS nyata — mode bisa diatur **per-node** (`sim` ↔ `emul`).

Outputnya **konfigurasi nyata siap pakai** untuk banyak NOS. Dan pembeda utamanya: **ForgeOS** —
NOS deklaratif *intent-based* baru. Anda mendeskripsikan *maksud* sekali (YAML), NetForge
meng-compile-nya menjadi konfigurasi untuk **7 vendor sekaligus** — dan memverifikasinya di
simulasi sebelum deploy.

> **Satu intent → banyak vendor config**, terverifikasi di simulasi.

## 🚀 Fitur Inti

| | |
|---|---|
| 🌐 **Simulasi skala besar** | Engine DES deterministik (seeded), target ribuan–puluhan ribu node mode `sim` |
| 🧩 **Multi-skenario** | Campus, ISP/FTTH, datacenter spine-leaf EVPN-VXLAN, backbone metro-E/DWDM, MPLS L3VPN, DCI SR-MPLS |
| ⚙️ **Config-gen multi-vendor** | Cisco IOS/IOS-XR/NX-OS · Juniper Junos · Arista EOS · MikroTik RouterOS · VyOS · FRRouting · **ForgeOS** |
| 🧠 **ForgeOS intent-based** | Satu intent YAML → konfigurasi banyak vendor + verifikasi simulasi |
| 🖥️ **UI desktop-class** | Window manager + dock + glassmorphism ala macOS/Win11, kanvas topologi React Flow, ringan (<200MB idle) |
| 🔌 **Realtime** | WebSocket untuk topologi, telemetry, dan konsol per-perangkat |

## 🧱 Arsitektur

```
┌───────────────────────────────────────────────────────────────┐
│  Frontend  React 18 + Vite + Tailwind + React Flow             │
│  window manager · dock · kanvas topologi · konsol · config view│
└───────────────▲───────────────────────────────▲───────────────┘
       REST /api │                     WS /ws/*  │
┌───────────────┴───────────────────────────────┴───────────────┐
│  Backend   FastAPI (async)                                     │
│   ├─ API §4 : projects · nodes · links · scenarios · simulate  │
│   │           · configs                                        │
│   ├─ engine : DES kernel (event queue · scheduler · runtimes)  │
│   │           + emulation adaptor (containerlab/Docker)        │
│   └─ config-gen : Jinja2 per-vendor + ForgeOS compiler         │
└───────────────▲───────────────────────────────▲───────────────┘
                │ PostgreSQL (topologi/config)   │ Redis (state/PubSub/queue)
                └────────────────────────────────┘
```

## 📂 Struktur Repositori

| Folder | Isi |
|---|---|
| [`backend/`](backend/) | FastAPI app + engine DES + service config-gen/sim (`pytest`: 20 hijau) |
| [`frontend/`](frontend/) | UI React desktop-class (shell, kanvas, panel, store) |
| [`config-gen/`](config-gen/) | Template Jinja2 7 vendor + skema & contoh intent **ForgeOS** |
| [`network/devices/library/`](network/devices/library/) | Pustaka perangkat (router, switch, OLT/ONU, firewall, AP, optical) sebagai data |
| [`infra/`](infra/) | Skema PostgreSQL, Redis, Docker Compose, CI |
| [`scripts/`](scripts/) | Utilitas operasional — mis. `self-update.sh` (update dari aplikasi) |

## ⚡ Mulai Cepat

### Satu perintah (direkomendasikan)

```bash
./install.sh
```

Installer ini meng-install Docker bila belum ada (tahan-banting di Fedora/WSL),
membuat `.env` berisi secret, mendeteksi alamat LAN, build + start seluruh stack
(postgres · redis · backend FastAPI · frontend Vite) di belakang satu gateway
nginx, menunggu `/api/health`, lalu mencetak URL yang bisa dibuka:

```
On this machine     →  http://localhost:8090
On the network      →  http://<LAN-IP>:8090     (buka dari HP/PC lain)
API docs            →  http://<LAN-IP>:8090/docs
```

> Port **8090** dipilih agar tidak bentrok dengan project saudara di host yang
> sama (SecureOps `:80`, StorageHub `:8080`). Override: `HTTP_PORT=9000 ./install.sh`.

Flag lain: `--prod` (stack produksi: image immutable, nginx, scale) ·
`--rebuild` · `--no-build` · `--down` (stop) · `--reset` (stop + HAPUS data) ·
`--tailscale` · `--public`. Windows: `./install.ps1`. Uninstall: `./uninstall.sh`
(`--purge` untuk menghapus volume). Target Make: `make help`.

### Manual (per komponen)

<details>
<summary>Backend · Frontend · Docker Compose mentah</summary>

```bash
# Backend
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000        # http://localhost:8000/docs
pytest -q                                         # 20 passed

# Frontend
cd frontend
npm install
npm run dev                                       # http://localhost:5173

# Semuanya (Docker Compose mentah, tanpa gateway LAN)
docker compose -f infra/docker-compose.yml up --build   # postgres + redis + backend + frontend
```

</details>

### Contoh: satu intent → banyak vendor
```bash
cd backend
python - <<'PY'
from app.models import Node, Interface
from app.services import configgen
node = Node(id="n1", project_id="p1", name="PE1", nos="forgeos",
    interfaces=[Interface(id="i1", node_id="n1", name="Gi0/0", ip=["10.0.0.1/24"])],
    intent={"bgp":{"asn":65001,"router_id":"1.1.1.1",
                   "neighbors":[{"ip":"10.0.0.2","remote_as":65002}]}})
for v in ("ios","junos","eos","routeros","vyos","frr","forgeos"):
    print(f"\n===== {v} =====\n{configgen.render(node, v)}")
PY
```

## 🔄 Update dari aplikasi

NetForge bisa **cek & pasang update langsung dari aplikasi** — ikon unduh di menu bar atas
membandingkan versi yang berjalan dengan rilis terbaru di GitHub, lalu (opsional)
menerapkannya: *pull → rebuild → restart*.

- `GET /api/update/check` — bandingkan versi (read-only)
- `POST /api/update/apply` — jalankan upgrade (dijaga `UPDATE_TOKEN`; nonaktif bila kosong)
- [`scripts/self-update.sh`](scripts/self-update.sh) — satu-satunya skrip yang dijalankan
  backend: checkout tag rilis terbaru + `docker compose up -d --build`

Manual: `./scripts/self-update.sh --check` · `--apply` · `--watch`.

## 🗺️ Roadmap (ringkas)

- **MVP** — kanvas + DES dasar + config-gen + ForgeOS compiler (≤ ~1.000 node)
- **v1** — emulasi containerlab, verifikasi intent, skenario besar (≤ ~10.000 node)
- **v2** — sharding terdistribusi, digital twin, AI-assisted topology

## 🤝 Kontribusi

Kontribusi memakai DCO & SemVer — buka issue / pull request di GitHub.

## 📜 Lisensi

[Apache-2.0](LICENSE) © Muhammad Surya Ragasin — Politeknik Negeri Sriwijaya, D4 Teknik Telekomunikasi.
