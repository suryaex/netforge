"""Device-type registry endpoints.

Provides a catalog of known device types (AP, CPE, Tower, Switch, Router, …)
that the frontend map-mode uses to populate node-creation palettes and set
sensible defaults. Built-in types are read-only; operators may extend the
registry with custom entries at runtime.

Endpoints
---------
GET    /api/device-types              — list all device types (built-in + custom)
POST   /api/device-types              — add a custom device type
DELETE /api/device-types/{id}         — remove a custom device type (built-ins protected)
POST   /api/device-types/upload-iso   — parse ISO 9660 image and register device type
"""
from __future__ import annotations

import struct
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from app.utils.ids import new_id

router = APIRouter(tags=["device-types"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class DeviceType(BaseModel):
    id: str
    name: str
    category: str = Field(
        default="custom",
        description="Logical group: wireless, wired, infrastructure, custom, …",
    )
    icon: str | None = Field(
        default=None,
        description="Icon identifier used by the frontend (e.g. 'ap', 'tower')",
    )
    description: str = ""
    builtin: bool = Field(default=False, description="True for read-only built-in types")


class DeviceTypeCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    category: str = "custom"
    icon: str | None = None
    description: str = ""


# ---------------------------------------------------------------------------
# Built-in catalog  (immutable; returned in every GET response)
# ---------------------------------------------------------------------------

_BUILTIN: list[DeviceType] = [
    DeviceType(id="builtin-ap",      name="Access Point",   category="wireless",        icon="ap",      description="802.11 wireless access point",                builtin=True),
    DeviceType(id="builtin-cpe",     name="CPE",            category="wireless",        icon="cpe",     description="Customer-premises equipment (wireless)",       builtin=True),
    DeviceType(id="builtin-tower",   name="Tower",          category="wireless",        icon="tower",   description="Cellular / backhaul tower",                   builtin=True),
    DeviceType(id="builtin-switch",  name="Switch",         category="wired",           icon="switch",  description="Layer-2 Ethernet switch",                     builtin=True),
    DeviceType(id="builtin-router",  name="Router",         category="wired",           icon="router",  description="Layer-3 IP router",                           builtin=True),
    DeviceType(id="builtin-olt",     name="OLT",            category="fiber",           icon="olt",     description="Optical Line Terminal (PON/GPON headend)",    builtin=True),
    DeviceType(id="builtin-onu",     name="ONU/ONT",        category="fiber",           icon="onu",     description="Optical Network Unit / Terminal (subscriber)", builtin=True),
    DeviceType(id="builtin-fw",      name="Firewall",       category="security",        icon="fw",      description="Stateful packet-filter / NGFW",               builtin=True),
    DeviceType(id="builtin-server",  name="Server",         category="infrastructure",  icon="server",  description="Physical or virtual server",                  builtin=True),
    DeviceType(id="builtin-cloud",   name="Cloud / Internet", category="infrastructure", icon="cloud",  description="Internet gateway / cloud-uplink node",        builtin=True),
]

# Runtime-mutable store for operator-added custom types
_custom: dict[str, DeviceType] = {}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/device-types", response_model=list[DeviceType])
async def list_device_types() -> list[DeviceType]:
    """Return all device types: built-ins first, then custom entries."""
    return _BUILTIN + list(_custom.values())


@router.post("/device-types", response_model=DeviceType, status_code=status.HTTP_201_CREATED)
async def create_device_type(body: DeviceTypeCreate) -> DeviceType:
    """Register a new custom device type.

    The name must be unique across built-ins and existing custom types.
    """
    all_names = {dt.name.lower() for dt in _BUILTIN} | {dt.name.lower() for dt in _custom.values()}
    if body.name.lower() in all_names:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A device type named '{body.name}' already exists.",
        )
    dt = DeviceType(
        id=new_id(),
        name=body.name,
        category=body.category,
        icon=body.icon,
        description=body.description,
        builtin=False,
    )
    _custom[dt.id] = dt
    return dt


@router.delete("/device-types/{device_type_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device_type(device_type_id: str) -> None:
    """Delete a custom device type.

    Built-in types cannot be deleted (returns 403).
    Non-existent IDs return 404.
    """
    # Check built-ins first
    if any(dt.id == device_type_id for dt in _BUILTIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Built-in device types cannot be deleted.",
        )
    if device_type_id not in _custom:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Device type '{device_type_id}' not found.",
        )
    del _custom[device_type_id]


# ---------------------------------------------------------------------------
# ISO 9660 upload — parse label, size, architecture and register device type
# ---------------------------------------------------------------------------

class ISODeviceType(BaseModel):
    """Metadata extracted from an ISO 9660 image."""
    id:            str
    name:          str
    label:         str   = Field(description="ISO 9660 Volume Identifier")
    system_id:     str   = Field(description="ISO 9660 System Identifier field")
    architecture:  str   = Field(description="Inferred CPU architecture (x86_64, arm64, …)")
    size_bytes:    int   = Field(description="Declared image size in bytes")
    size_mb:       float = Field(description="Image size in megabytes (rounded 2 dp)")
    category:      str   = "iso"
    builtin:       bool  = False


# ISO 9660 Primary Volume Descriptor layout
# Absolute file offsets (sector 16 = byte 32768, each sector = 2048 bytes)
_PVD_OFFSET       = 32768   # byte offset of Primary Volume Descriptor in ISO
_PVD_TYPE_OFFSET  = 0       # relative offset: descriptor type (1 byte)
_PVD_ID_OFFSET    = 1       # relative: standard identifier "CD001" (5 bytes)
_PVD_SYS_ID_OFF   = 8       # relative: system identifier (32 bytes)
_PVD_VOL_ID_OFF   = 40      # relative: volume identifier / label (32 bytes)
_PVD_SPACE_OFF    = 80      # relative: volume space size LE+BE (8 bytes)
_PVD_BLOCK_SZ_OFF = 128     # relative: logical block size LE+BE (4 bytes)
_PVD_TYPE_PRIMARY = 1

_MIN_ISO_SIZE = _PVD_OFFSET + 512  # must have at least enough bytes to read PVD


def _parse_iso_9660(data: bytes) -> dict:
    """Extract label, size, and architecture from raw ISO 9660 bytes.

    Reads the Primary Volume Descriptor at byte offset 32768 (sector 16).

    Args:
        data: Raw bytes of the ISO image (at least 33280 bytes required).

    Returns:
        Dict with keys: label, system_id, architecture, size_bytes, size_mb.

    Raises:
        ValueError: If the data is too short or not a valid ISO 9660 image.
    """
    if len(data) < _MIN_ISO_SIZE:
        raise ValueError(
            f"File too small to be a valid ISO 9660 image "
            f"(got {len(data)} bytes, need ≥ {_MIN_ISO_SIZE})"
        )

    pvd = data[_PVD_OFFSET:]

    # Verify PVD signature
    pvd_type = pvd[_PVD_TYPE_OFFSET]
    std_id   = pvd[_PVD_ID_OFFSET: _PVD_ID_OFFSET + 5].decode("ascii", errors="replace")
    if pvd_type != _PVD_TYPE_PRIMARY or std_id != "CD001":
        raise ValueError(
            f"Not a valid ISO 9660 Primary Volume Descriptor "
            f"(type={pvd_type:#x}, id={std_id!r})"
        )

    # System Identifier (32 bytes, a-characters, space-padded)
    system_id = pvd[_PVD_SYS_ID_OFF: _PVD_SYS_ID_OFF + 32].decode(
        "ascii", errors="replace"
    ).strip()

    # Volume Identifier / Label (32 bytes, d-characters, space-padded)
    volume_id = pvd[_PVD_VOL_ID_OFF: _PVD_VOL_ID_OFF + 32].decode(
        "ascii", errors="replace"
    ).strip()

    # Volume Space Size: little-endian 4 bytes at offset 80
    volume_space_size_le = struct.unpack_from("<I", pvd, _PVD_SPACE_OFF)[0]

    # Logical Block Size: little-endian 2 bytes at offset 128
    logical_block_size = struct.unpack_from("<H", pvd, _PVD_BLOCK_SZ_OFF)[0]
    if logical_block_size == 0:
        logical_block_size = 2048  # ISO 9660 standard default

    size_bytes = volume_space_size_le * logical_block_size

    # Infer architecture from system identifier and volume label heuristics
    architecture = _infer_architecture(system_id, volume_id)

    return {
        "label":        volume_id or "UNKNOWN",
        "system_id":    system_id or "",
        "architecture": architecture,
        "size_bytes":   size_bytes,
        "size_mb":      round(size_bytes / (1024 * 1024), 2),
    }


_ARCH_KEYWORDS: list[tuple[list[str], str]] = [
    (["x86_64", "amd64", "x64", "64-bit"],              "x86_64"),
    (["i386", "i686", "x86", "32-bit"],                  "x86"),
    (["arm64", "aarch64", "armv8"],                       "arm64"),
    (["armv7", "armhf", "arm32"],                         "armv7"),
    (["mips64", "mips"],                                  "mips"),
    (["riscv64", "riscv"],                                "riscv64"),
    (["ppc64le", "powerpc", "ppc"],                       "ppc64le"),
    (["s390x"],                                           "s390x"),
]


def _infer_architecture(system_id: str, volume_id: str) -> str:
    """Best-effort architecture inference from ISO identifier strings."""
    combined = (system_id + " " + volume_id).lower()
    for keywords, arch in _ARCH_KEYWORDS:
        for kw in keywords:
            if kw in combined:
                return arch
    return "unknown"


@router.post(
    "/device-types/upload-iso",
    response_model=ISODeviceType,
    status_code=status.HTTP_201_CREATED,
    summary="Upload ISO image and register device type",
    description=(
        "Parse an ISO 9660 disc image (multipart/form-data), extract the "
        "volume label, declared size, and inferred CPU architecture from the "
        "Primary Volume Descriptor, then register the result as a custom "
        "device type in the registry."
    ),
)
async def upload_iso_device_type(
    file: Annotated[UploadFile, File(description="ISO 9660 disc image (.iso)")],
) -> ISODeviceType:
    """Parse ISO 9660 header and register device type from disc image.

    Reads up to the first 2 MB of the file (enough to cover the PVD at
    byte 32 768 plus margin). Registers the extracted metadata as a custom
    device type named after the volume label.

    Returns 400 if the file is not a valid ISO 9660 image.
    Returns 409 if a device type with the same label already exists.
    """
    # Read enough bytes to cover the PVD (sector 16 + slack)
    raw = await file.read(2 * 1024 * 1024)  # 2 MB cap

    try:
        meta = _parse_iso_9660(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid ISO 9660 image: {exc}",
        ) from exc

    label = meta["label"]
    name = label.replace("_", " ").replace("-", " ").title()

    # Collision check against built-ins and existing custom types
    all_names = {dt.name.lower() for dt in _BUILTIN} | {
        dt.name.lower() for dt in _custom.values()
    }
    if name.lower() in all_names:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A device type named '{name}' (from ISO label '{label}') already exists.",
        )

    device_id = new_id()
    iso_dt = ISODeviceType(
        id=device_id,
        name=name,
        label=label,
        system_id=meta["system_id"],
        architecture=meta["architecture"],
        size_bytes=meta["size_bytes"],
        size_mb=meta["size_mb"],
        category="iso",
        builtin=False,
    )

    # Also store a plain DeviceType entry so it appears in the main listing
    _custom[device_id] = DeviceType(
        id=device_id,
        name=name,
        category="iso",
        icon="server",
        description=(
            f"ISO: {label} | arch={meta['architecture']} | "
            f"size={meta['size_mb']} MiB"
        ),
        builtin=False,
    )

    return iso_dt
