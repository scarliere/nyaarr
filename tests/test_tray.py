from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace


def import_tray(monkeypatch):
    fake_pystray = SimpleNamespace(
        Icon=object,
        Menu=lambda *items: items,
        MenuItem=lambda *args, **kwargs: (args, kwargs),
    )
    fake_image = SimpleNamespace(open=lambda path: None, new=lambda *args, **kwargs: None)
    fake_image_draw = SimpleNamespace(Draw=lambda image: None)
    monkeypatch.setitem(sys.modules, "pystray", fake_pystray)
    monkeypatch.setitem(sys.modules, "PIL", SimpleNamespace(Image=fake_image, ImageDraw=fake_image_draw))
    monkeypatch.setitem(sys.modules, "PIL.Image", fake_image)
    monkeypatch.setitem(sys.modules, "PIL.ImageDraw", fake_image_draw)
    sys.modules.pop("nyaarr.tray", None)
    return importlib.import_module("nyaarr.tray")


def test_windows_terminate_process_tree_hides_taskkill_console(monkeypatch) -> None:
    tray = import_tray(monkeypatch)
    calls = []
    monkeypatch.setattr(tray.os, "name", "nt")
    monkeypatch.setattr(tray.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(tray.subprocess, "STARTF_USESHOWWINDOW", 1, raising=False)
    monkeypatch.setattr(tray.subprocess, "SW_HIDE", 0, raising=False)

    class FakeStartupInfo:
        def __init__(self) -> None:
            self.dwFlags = 0
            self.wShowWindow = None

    monkeypatch.setattr(tray.subprocess, "STARTUPINFO", FakeStartupInfo, raising=False)
    monkeypatch.setattr(tray.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    tray._terminate_process_tree(1234)

    assert calls
    args, kwargs = calls[0]
    assert args[0] == ["taskkill", "/PID", "1234", "/T", "/F"]
    assert kwargs["creationflags"] == tray.subprocess.CREATE_NO_WINDOW
    assert kwargs["startupinfo"].dwFlags & tray.subprocess.STARTF_USESHOWWINDOW
    assert kwargs["startupinfo"].wShowWindow == tray.subprocess.SW_HIDE