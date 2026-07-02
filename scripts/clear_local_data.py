from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = PROJECT_ROOT / "data"
TARGETS = [DATA_ROOT / "user", DATA_ROOT / "cache", DATA_ROOT / "logs", DATA_ROOT / "image"]
MAIN_SCRIPT = PROJECT_ROOT / "main.py"
TRAY_SCRIPT = PROJECT_ROOT / "nyaarr" / "tray.py"


@dataclass
class ProcessInfo:
    pid: int
    command_line: str


def write_step(message: str) -> None:
    print(f"[Nyaarr] {message}")


def assert_in_project(path: Path) -> None:
    project_root = PROJECT_ROOT.resolve()
    target = path.resolve()
    try:
        target.relative_to(project_root)
    except ValueError as exc:
        raise RuntimeError(f"Refusing to clean path outside project root: {target}") from exc


def windows_nyaarr_processes() -> list[ProcessInfo]:
    if os.name != "nt":
        return []
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Process -Filter \"Name = 'python.exe' OR Name = 'pythonw.exe'\" | "
            "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        return []

    import json

    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return []
    rows = data if isinstance(data, list) else [data]
    current_pid = os.getpid()
    project_root_text = str(PROJECT_ROOT.resolve()).casefold()
    main_script_text = str(MAIN_SCRIPT.resolve()).casefold()
    tray_script_text = str(TRAY_SCRIPT.resolve()).casefold()
    matches: list[ProcessInfo] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            pid = int(row.get("ProcessId") or 0)
        except (TypeError, ValueError):
            continue
        if pid <= 0 or pid == current_pid:
            continue
        command_line = str(row.get("CommandLine") or "")
        command_folded = command_line.casefold()
        runs_exact_script = main_script_text in command_folded or tray_script_text in command_folded
        runs_project_script = project_root_text in command_folded and ("main.py" in command_folded or "tray.py" in command_folded)
        if runs_exact_script or runs_project_script:
            matches.append(ProcessInfo(pid=pid, command_line=command_line))
    return matches


def stop_existing_nyaarr_processes() -> None:
    matches = windows_nyaarr_processes()
    if not matches:
        return
    write_step(f"Stopping {len(matches)} running Nyaarr process(es).")
    for process in matches:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    time.sleep(1)


def clear_directory_contents(path: Path) -> None:
    assert_in_project(path)
    path.mkdir(parents=True, exist_ok=True)
    for child in path.iterdir():
        if child.name == ".gitkeep":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    (path / ".gitkeep").touch()


def confirm(force: bool) -> bool:
    print("This will delete Nyaarr local test data under:")
    for target in TARGETS:
        print(f"  {target}")
    print("It will not delete code, .venv, tools, requirements, or the desktop shortcut.")
    if force:
        return True
    return input("Type CLEAN to continue: ") == "CLEAN"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Clear Nyaarr local test data and reset to fresh-client state.")
    parser.add_argument("--force", action="store_true", help="Skip the CLEAN confirmation prompt.")
    args = parser.parse_args(argv)

    if not confirm(args.force):
        print("Cancelled.")
        return 0

    stop_existing_nyaarr_processes()
    for target in TARGETS:
        write_step(f"Cleaning {target}")
        clear_directory_contents(target)
    write_step("Local data cleared. Next startup will behave like a fresh client and ask for superadmin setup again.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())