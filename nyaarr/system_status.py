from __future__ import annotations

import ctypes
import os
import platform
import shutil
import sys
import time
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any

from .app_state import USER_DATABASE_PATH, display_timezone_label, user_settings, _display_datetime_label

APP_STARTED_AT = datetime.now(timezone.utc)
APP_STARTED_MONOTONIC = time.monotonic()
GITHUB_REPO_URL = "https://github.com/scarliere/nyaarr"


def system_status_model() -> dict[str, Any]:
    uptime_seconds = max(int(time.monotonic() - APP_STARTED_MONOTONIC), 0)
    return {
        "disks": _disk_space_rows(),
        "about": _about_rows(),
        "uptime": {
            "started_at": _display_datetime_label(APP_STARTED_AT.isoformat()),
            "seconds": uptime_seconds,
            "label": _duration_label(uptime_seconds),
        },
        "links": [
            {"label": "GitHub repository", "url": GITHUB_REPO_URL},
        ],
    }


def _disk_space_rows() -> list[dict[str, Any]]:
    root_disk = _root_folder_disk_name()
    rows = []
    for disk in _disk_roots():
        try:
            usage = shutil.disk_usage(disk)
        except OSError:
            continue
        used = usage.total - usage.free
        used_percent = round((used / usage.total) * 100, 1) if usage.total else 0
        rows.append(
            {
                "name": disk,
                "total": usage.total,
                "used": used,
                "free": usage.free,
                "total_label": _bytes_label(usage.total),
                "used_label": _bytes_label(used),
                "free_label": _bytes_label(usage.free),
                "used_percent": used_percent,
                "free_percent": round(100 - used_percent, 1),
                "tone": _disk_tone(used_percent),
                "is_root_folder_drive": _same_disk_name(disk, root_disk),
            }
        )
    return rows


def _root_folder_disk_name() -> str:
    root_folder = str(user_settings().get("root_folder") or "").strip()
    if not root_folder:
        return ""
    if os.name == "nt":
        drive, _ = os.path.splitdrive(root_folder)
        return f"{drive.upper()}\\" if drive else ""
    return "/" if os.path.isabs(root_folder) else ""


def _same_disk_name(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return left.rstrip("\\/").casefold() == right.rstrip("\\/").casefold()

def _disk_roots() -> list[str]:
    if os.name == "nt":
        roots = []
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for index in range(26):
            if bitmask & (1 << index):
                roots.append(f"{chr(65 + index)}:\\")
        return roots
    return ["/"]


def _about_rows() -> list[dict[str, str]]:
    return [
        {"label": "Application", "value": "Nyaarr"},
        {"label": "Python", "value": sys.version.split()[0]},
        {"label": "Flask", "value": _package_version("Flask")},
        {"label": "Platform", "value": platform.platform()},
        {"label": "Operating system", "value": f"{platform.system()} {platform.release()}".strip()},
        {"label": "Architecture", "value": platform.machine() or "Unknown"},
        {"label": "Processor", "value": platform.processor() or "Unknown"},
        {"label": "Python executable", "value": sys.executable},
        {"label": "Working directory", "value": str(Path.cwd())},
        {"label": "App package", "value": str(Path(__file__).resolve().parent)},
        {"label": "User database", "value": str(USER_DATABASE_PATH)},
        {"label": "Display timezone", "value": display_timezone_label()},
    ]


def _package_version(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "Unknown"


def _bytes_label(value: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(amount)} {unit}"
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{value} B"


def _duration_label(seconds: int) -> str:
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or parts:
        parts.append(f"{hours}h")
    if minutes or parts:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


def _disk_tone(used_percent: float) -> str:
    if used_percent >= 90:
        return "red"
    if used_percent >= 75:
        return "yellow"
    return "green"

