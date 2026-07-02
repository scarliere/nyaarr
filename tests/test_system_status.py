from __future__ import annotations

from collections import namedtuple

from nyaarr import system_status


DiskUsage = namedtuple("DiskUsage", "total used free")


def test_disk_space_rows_marks_configured_root_folder_drive(monkeypatch) -> None:
    monkeypatch.setattr(system_status, "_disk_roots", lambda: ["C:\\", "D:\\"])
    monkeypatch.setattr(system_status, "user_settings", lambda: {"root_folder": "D:\\Anime"})
    monkeypatch.setattr(system_status.shutil, "disk_usage", lambda disk: DiskUsage(total=100, used=40, free=60))

    rows = system_status._disk_space_rows()

    assert [row["name"] for row in rows] == ["C:\\", "D:\\"]
    assert [row["is_root_folder_drive"] for row in rows] == [False, True]