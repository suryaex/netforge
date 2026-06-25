"""In-app self-update service.

Lets an operator update NetForge *from the running app*: check whether a newer
release exists on GitHub, then apply it (pull + rebuild + restart) via the
committed, auditable ``scripts/self-update.sh`` — never arbitrary code.

Design notes
------------
* **check** is read-only: it queries the public GitHub Releases API and compares
  the latest tag with the running version. Network failures degrade gracefully.
* **apply** writes a sentinel *trigger* file that a host-side watcher (or the
  backend itself, when ``UPDATE_INPROC`` is on and the repo + docker socket are
  mounted) acts on by running ``scripts/self-update.sh``. The backend never
  executes anything other than that one committed script.
* **status** reflects whatever ``scripts/self-update.sh`` last wrote to the
  status file, so the UI can show progress and survive the restart.

Standard library only — no new dependencies.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from app.core.config import get_settings

_RELEASES_LATEST = "https://api.github.com/repos/{repo}/releases/latest"
_TAGS = "https://api.github.com/repos/{repo}/tags"
_HTTP_TIMEOUT = 6  # seconds — keep the UI responsive on a slow network


# --------------------------------------------------------------------------- #
# Semantic-ish version comparison (tolerant of "v" prefixes and suffixes).
# --------------------------------------------------------------------------- #
def normalize(version: str) -> str:
    return (version or "").strip().lstrip("vV")


def _parts(version: str) -> tuple[int, ...]:
    out: list[int] = []
    for chunk in normalize(version).split("."):
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        out.append(int(digits) if digits else 0)
    return tuple(out) or (0,)


def is_newer(candidate: str, current: str) -> bool:
    """True when ``candidate`` is a strictly higher version than ``current``."""
    a, b = _parts(candidate), _parts(current)
    length = max(len(a), len(b))
    a += (0,) * (length - len(a))
    b += (0,) * (length - len(b))
    return a > b


# --------------------------------------------------------------------------- #
# GitHub release lookup.
# --------------------------------------------------------------------------- #
def _get_json(url: str) -> object:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "netforge-updater",
        },
    )
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def _latest_release(repo: str) -> dict | None:
    """Latest published release, falling back to the newest tag."""
    try:
        rel = _get_json(_RELEASES_LATEST.format(repo=repo))
        if isinstance(rel, dict) and rel.get("tag_name"):
            return {
                "version": rel["tag_name"],
                "notes": rel.get("body") or "",
                "url": rel.get("html_url") or "",
                "published_at": rel.get("published_at") or "",
            }
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError, OSError):
        pass
    # No releases yet → newest tag.
    try:
        tags = _get_json(_TAGS.format(repo=repo))
        if isinstance(tags, list) and tags:
            tag = tags[0]
            return {
                "version": tag.get("name", ""),
                "notes": "",
                "url": f"https://github.com/{repo}/releases",
                "published_at": "",
            }
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError, OSError):
        pass
    return None


# --------------------------------------------------------------------------- #
# Public API used by the router.
# --------------------------------------------------------------------------- #
def check() -> dict:
    settings = get_settings()
    current = settings.APP_VERSION
    latest = _latest_release(settings.GITHUB_REPO)
    if latest is None:
        return {
            "current": current,
            "latest": None,
            "update_available": False,
            "checked_at": int(time.time()),
            "error": "Could not reach GitHub to check for updates.",
        }
    return {
        "current": current,
        "latest": normalize(latest["version"]),
        "update_available": is_newer(latest["version"], current),
        "notes": latest["notes"],
        "url": latest["url"],
        "published_at": latest["published_at"],
        "checked_at": int(time.time()),
        "can_apply": bool(settings.UPDATE_TOKEN),
    }


def status() -> dict:
    settings = get_settings()
    path = Path(settings.UPDATE_STATUS_FILE)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"state": "idle"}


def _write_status(state: str, message: str = "") -> None:
    settings = get_settings()
    path = Path(settings.UPDATE_STATUS_FILE)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"state": state, "message": message, "at": int(time.time())}),
            encoding="utf-8",
        )
    except OSError:
        pass


def apply() -> dict:
    """Request an update. Returns the queued status; the actual work happens
    out-of-process so the API can return before the server restarts."""
    settings = get_settings()
    target = check()
    if not target.get("update_available"):
        return {"state": "up-to-date", "message": "Already on the latest version."}

    trigger = Path(settings.UPDATE_TRIGGER_FILE)
    try:
        trigger.parent.mkdir(parents=True, exist_ok=True)
        trigger.write_text(
            json.dumps(
                {
                    "requested_at": int(time.time()),
                    "from": settings.APP_VERSION,
                    "to": target.get("latest"),
                    "branch": settings.UPDATE_BRANCH,
                }
            ),
            encoding="utf-8",
        )
    except OSError as exc:
        return {"state": "error", "message": f"Cannot write update trigger: {exc}"}

    _write_status("queued", f"Update to {target.get('latest')} requested.")

    if settings.UPDATE_INPROC:
        script = Path(__file__).resolve().parents[3] / "scripts" / "self-update.sh"
        if script.exists():
            try:
                # Detached: it will rebuild + restart this very process.
                subprocess.Popen(  # noqa: S603
                    ["bash", str(script), "--apply"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                _write_status("updating", "Running self-update.sh…")
            except OSError as exc:
                return {"state": "error", "message": f"Failed to launch updater: {exc}"}
        else:
            return {
                "state": "error",
                "message": f"Updater script not found at {script}.",
            }

    return {
        "state": "queued",
        "message": f"Updating to {target.get('latest')}. The app will restart shortly.",
        "to": target.get("latest"),
    }
