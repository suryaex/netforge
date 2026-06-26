# Backend — Kebutuhan Lintas-Area (NEEDS)

Backend menulis HANYA di `backend/`. Berikut yang dibutuhkan dari area agent
lain agar integrasi penuh berjalan. Orchestrator yang menyatukan.

## 1. `config-gen/` — template Jinja2 per-vendor  → `network-engineer`
- **Dipakai oleh**: `app/services/configgen.py` (memuat dari
  `config-gen/templates/<vendor>.j2`).
- **Status**: template baseline SUDAH ADA dan teruji (ios, junos, eos,
  routeros, vyos, frr, forgeos) — test `tests/test_configgen.py` hijau.
- **Kontrak konteks render** (key yang dibaca template, lihat `_context()`):
  `hostname, kind, nos, interfaces[], bgp, ospf, isis, vrfs[], vlans[], evpn,
  fhrp, static_routes[], intent`.
  - Catatan: template memakai `StrictUndefined` — bila sub-tree disertakan,
    field wajibnya harus lengkap (mis. `ospf` butuh `router_id`).
- **Diminta**: template untuk NOS sisa (iosxr, nxos, sros, vrp) + skema intent
  ForgeOS final (`config-gen/forgeos/schema.md`) sebagai sumber kebenaran key
  konteks.

## 2. `infra/db/schema.sql` — DDL PostgreSQL  → `db-devops-architect`
- **Dipakai oleh**: `app/store/postgres.py` (sketsa ORM saat ini).
- **Diminta**: DDL kanonik (tabel projects/nodes/links/scenarios/
  config_artifacts) + index, FK `ON DELETE CASCADE`, tipe JSONB untuk
  `interfaces`/`intent`/`steps`. Nama kolom WAJIB cocok dengan `models/schemas.py`
  (§4). Sketsa ORM kami mengikuti, bukan mendefinisikan, schema produksi.
- **Diminta**: pola koneksi Redis (state realtime / pub-sub WS / job queue)
  bila ada konvensi bersama (`infra/redis-design.md`).

## 3. Spec protokol & skenario  → `network-engineer` / `network-backbone-datacenter-advisor`
- **Dipakai oleh**: `engine/protocols/` (subclass `NodeRuntime`).
- **Diminta**: daftar protokol prioritas (OSPFv3, IS-IS, BGP, EVPN-VXLAN) +
  skenario uji skala besar (spine-leaf, ISP/FTTH, backbone) untuk validasi
  engine pada ribuan node.

## 4. Kontrak tipe frontend  → `frontend-architecture-advisor`
- **Acuan**: `frontend/src/api/types.ts` + `client.ts` harus tetap selaras
  dengan `models/schemas.py` (§4). Bila frontend mengubah bentuk payload,
  koordinasikan agar enum/field tetap identik di kedua sisi.

## 5. Emulasi  → orchestrator / `db-devops-architect`
- **Dipakai oleh**: `engine/emulation/` (`EmulationAdaptor` ABC).
- **Diminta**: ketersediaan runtime containerlab/Docker di lingkungan dev/prod
  + image NOS, agar adaptor konkret (mis. `containerlab.py`) bisa dibangun.
  Default saat ini `NullEmulationAdaptor` (run murni-sim, import-able tanpa
  Docker).

## 6. Map mode — kontrak geo + wireless  → `frontend-architecture-advisor`
Engine RF otoritatif ada di backend (`engine/wireless.py`); frontend boleh tetap
menghitung FSPL ringan untuk feedback instan saat drag, tapi nilai yang
dipersist + di-broadcast berasal dari backend agar semua klien sepakat.

- **Node sekarang punya field geo (opsional, WGS84)** — selaraskan
  `frontend/src/api/types.ts` `NodeModel`:
  - `lat: number | null`, `lon: number | null`
  - `radio: Radio | null` dengan field **identik**:
    `tx_power_dbm, frequency_ghz, antenna_gain_dbi, bandwidth_mhz,
     rx_sensitivity_dbm, misc_loss_db, max_range_m`
  - Map device = Node biasa (`kind` `ap`/`host`/`olt`) + `lat/lon/radio`.
    Tower dibedakan via `intent.map_role = "tower"`.
- **Endpoint baru** (`app/api/wireless.py`, prefix `/api/wireless`):
  - `POST /link-budget` → `{distance_m, fspl_db, rssi_dbm, margin_db,
     noise_floor_dbm, snr_db, quality, feasible}`. Body: `{tx: Radio, rx?: Radio,
     distance_m? | a_lat/a_lon/b_lat/b_lon, rain_rate_mm_hr?}`.
  - `GET  /plan/{project_id}` → `{project_id, links[], coverage[]}` — link plan
     (RSSI/quality per asosiasi) + lingkaran coverage per AP/tower.
  - `GET  /coverage/{node_id}` → `{node_id, radius_m}`.
  - `GET  /elevation?a_lat&a_lon&b_lat&b_lon&samples` → profil elevasi
     (proxy open-elevation; 503 bila provider tak terjangkau).
  - `POST /los-check` → `{los_clear, fresnel_clear, worst_obstruction_m,
     min_clearance_ratio, distance_m, profile?}`. Boleh kirim `profile` sendiri
     untuk mode offline (tanpa panggilan jaringan).
- **WebSocket `/ws/topology?project=<id>`** kini event-driven (bukan tick):
  - on-connect kirim `{"type":"snapshot","topology":{...}}` lalu
    `{"type":"wireless.plan", project_id, links[], coverage[]}`.
  - tiap node/link berubah → broadcast `node.updated` / `link.updated` /
    `node.deleted` / `link.deleted` + `wireless.plan` baru (recompute server-side).
  - balas `pong` untuk frame teks `ping` (heartbeat). Tambahkan tipe-tipe ini ke
    union `TopologyEvent`.
- **Catatan integrasi**: dua endpoint sinyal sekarang hidup berdampingan —
  `/api/signal/calculate` (FSPL ringkas) dan `/api/wireless/*` (link budget penuh
  + planner + LoS + rain fade). Frontend sebaiknya memakai `/api/wireless` sebagai
  sumber kebenaran; `/api/signal/calculate` bisa dipertahankan untuk kalkulasi
  cepat ad-hoc atau dideprekasi oleh orchestrator.
