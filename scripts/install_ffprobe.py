from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path


DEFAULT_FFMPEG_ZIP_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
DEFAULT_INSTALL_DIR = Path("tools/ffmpeg")


def main() -> int:
    parser = argparse.ArgumentParser(description="Install ffprobe into the repo-local tools folder.")
    parser.add_argument("--url", default=DEFAULT_FFMPEG_ZIP_URL, help="FFmpeg zip URL to download.")
    parser.add_argument("--install-dir", default=str(DEFAULT_INSTALL_DIR), help="Install directory.")
    parser.add_argument("--force", action="store_true", help="Replace an existing install directory.")
    args = parser.parse_args()

    install_dir = Path(args.install_dir)
    ffprobe_path = install_dir / "bin" / "ffprobe.exe"
    if ffprobe_path.exists() and not args.force:
        print(f"ffprobe already installed: {ffprobe_path}")
        return 0

    if install_dir.exists() and args.force:
        shutil.rmtree(install_dir)

    with tempfile.TemporaryDirectory() as temp_dir:
        archive_path = Path(temp_dir) / "ffmpeg.zip"
        print(f"Downloading {args.url}")
        urllib.request.urlretrieve(args.url, archive_path)

        with zipfile.ZipFile(archive_path) as archive:
            bin_prefix = _archive_bin_prefix(archive)
            if bin_prefix is None:
                print("Could not find ffprobe.exe inside the downloaded archive.", file=sys.stderr)
                return 1

            for member in archive.infolist():
                if member.is_dir() or not member.filename.startswith(bin_prefix):
                    continue
                relative_name = member.filename.removeprefix(bin_prefix)
                if not relative_name:
                    continue
                target_path = install_dir / "bin" / relative_name
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target_path.open("wb") as target:
                    shutil.copyfileobj(source, target)

    if not ffprobe_path.exists():
        print(f"Install completed, but ffprobe was not found at {ffprobe_path}.", file=sys.stderr)
        return 1

    print(f"Installed ffprobe: {ffprobe_path}")
    return 0


def _archive_bin_prefix(archive: zipfile.ZipFile) -> str | None:
    for name in archive.namelist():
        normalized = name.replace("\\", "/")
        if normalized.endswith("/bin/ffprobe.exe"):
            return normalized.removesuffix("ffprobe.exe")
    return None


if __name__ == "__main__":
    raise SystemExit(main())
