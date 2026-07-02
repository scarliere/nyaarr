from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:
    sys.exit(0)


def _load_icon(project_root: Path) -> Image.Image:
    icon_path = project_root / "nyaarr" / "static" / "img" / "default-icon.png"
    if icon_path.exists():
        return Image.open(icon_path).convert("RGBA")

    image = Image.new("RGBA", (256, 256), (15, 23, 42, 255))
    draw = ImageDraw.Draw(image)
    draw.ellipse((32, 32, 224, 224), fill=(37, 99, 235, 255))
    draw.text((84, 92), "N", fill=(255, 255, 255, 255))
    return image


def _process_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _terminate_process_tree(pid: int) -> None:
    if pid <= 0:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return


def _watch_process(icon: pystray.Icon, pid: int) -> None:
    while _process_running(pid):
        time.sleep(2)
    icon.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description="Nyaarr tray icon")
    parser.add_argument("--pid", type=int, required=True, help="Nyaarr Flask process id")
    parser.add_argument("--url", default="http://127.0.0.1:1269", help="Browser URL to open")
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parents[1]), help="Nyaarr project root")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()

    def open_nyaarr(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        webbrowser.open(args.url)

    def terminate_nyaarr(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        _terminate_process_tree(args.pid)
        icon.stop()

    icon = pystray.Icon(
        "Nyaarr",
        _load_icon(project_root),
        "Nyaarr",
        pystray.Menu(
            pystray.MenuItem("Open Nyaarr", open_nyaarr, default=True),
            pystray.MenuItem("Terminate Nyaarr", terminate_nyaarr),
        ),
    )
    threading.Thread(target=_watch_process, args=(icon, args.pid), daemon=True).start()
    icon.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())