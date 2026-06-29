"""Fixtures bersama untuk test backend NetGeo.

Catatan desain:
- ``app.store.get_repo`` adalah singleton ber-``lru_cache`` (state hidup selama
  proses). Fixture ``client`` membersihkan repo singleton sebelum tiap test
  sehingga test saling terisolasi tanpa menyentuh kontrak API.
- Memakai ``httpx.AsyncClient`` + ``ASGITransport`` agar request menabrak app
  ASGI langsung (tanpa soket TCP) — cepat & deterministik.
- Auth (RB-01): ``_seed_admin`` menanam user tes sebelum tiap test dan
  membersihkan setelah selesai. Fixture ``client`` sudah menyertakan header
  Authorization yang valid sehingga test yang sudah ada tidak perlu diubah.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core import security as sec
from app.core.config import get_settings
from app.core.security import create_access_token
from app.main import app
from app.store import get_repo

# ---- Credentials used by every test ----------------------------------------
# Kept separate from production defaults so tests are hermetic.
_TEST_USER = "testadmin"
_TEST_PASS = "TestPass123!"


def make_test_token() -> str:
    """Create a valid JWT for _TEST_USER. Useful in both async and sync tests."""
    settings = get_settings()
    return create_access_token(
        sub=_TEST_USER,
        role="admin",
        secret=settings.SECRET_KEY,
        expires_in=3600,
    )


def make_auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_test_token()}"}


# ---- autouse fixtures — run for every test ---------------------------------

@pytest.fixture(autouse=True)
def _reset_repo():
    """Kosongkan repo in-memory singleton sebelum setiap test."""
    repo = get_repo()
    repo._projects.clear()
    repo._nodes.clear()
    repo._links.clear()
    repo._scenarios.clear()
    repo._configs.clear()
    repo._configs_by_node.clear()
    yield


@pytest.fixture(autouse=True)
def _seed_admin():
    """Tanam user admin tes sebelum tiap test (RB-01).

    Membersihkan ``security._users`` setelah test selesai sehingga state
    tidak bocor antar test. Fixture ini bersifat *autouse* agar test yang
    menggunakan ``TestClient`` secara langsung juga mendapat user yang valid.
    """
    sec._users.clear()
    sec.init_admin_user(_TEST_USER, _TEST_PASS)
    yield
    sec._users.clear()


# ---- Client fixtures -------------------------------------------------------

@pytest_asyncio.fixture
async def client():
    """Authenticated AsyncClient yang berbicara langsung ke aplikasi ASGI.

    Semua request menyertakan header ``Authorization: Bearer <token>`` yang
    valid sehingga test yang sudah ada tidak perlu menambahkan auth secara
    eksplisit.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers=make_auth_headers(),
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def anon_client():
    """Unauthenticated AsyncClient — dipakai untuk test skenario error 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
