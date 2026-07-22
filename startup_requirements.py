'''Install changed runtime requirements before importing the application.'''

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def ensure_requirements(
    project_root: Path | None = None,
    *,
    python_executable: str | None = None,
    marker_path: Path | None = None,
) -> bool:
    '''Install requirements when their content or Python environment changed.'''
    if os.environ.get('NYAARR_SKIP_REQUIREMENTS_CHECK') == '1':
        return False
    root = (project_root or Path(__file__).resolve().parent).resolve()
    requirements_path = root / 'requirements.txt'
    if not requirements_path.is_file():
        raise RuntimeError(f'Required dependency file was not found: {requirements_path}')
    executable = str(Path(python_executable or sys.executable).resolve())
    marker = marker_path or root / 'data' / 'cache' / 'requirements-installed.json'
    fingerprint = {
        'requirements_sha256': hashlib.sha256(requirements_path.read_bytes()).hexdigest(),
        'python_executable': executable,
        'python_version': f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}',
    }
    try:
        recorded = json.loads(marker.read_text(encoding='utf-8'))
    except (FileNotFoundError, OSError, ValueError, TypeError):
        recorded = None
    if recorded == fingerprint:
        return False
    print(f'Nyaarr requirements changed; installing from {requirements_path}.', flush=True)
    subprocess.run(
        [executable, '-m', 'pip', 'install', '-r', str(requirements_path)],
        cwd=str(root),
        check=True,
    )
    marker.parent.mkdir(parents=True, exist_ok=True)
    temporary_marker = marker.with_name(f'{marker.name}.{os.getpid()}.tmp')
    temporary_marker.write_text(json.dumps(fingerprint, indent=2) + '\n', encoding='utf-8')
    temporary_marker.replace(marker)
    return True
