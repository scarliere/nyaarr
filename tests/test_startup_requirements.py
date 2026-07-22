import json

import startup_requirements


def test_installs_changed_requirements_with_space_safe_arguments(tmp_path, monkeypatch):
    root = tmp_path / 'Nyaarr Server Folder'
    root.mkdir()
    requirements = root / 'requirements.txt'
    requirements.write_text('Flask>=3.0,<4.0\n', encoding='utf-8')
    marker = root / 'data' / 'cache' / 'requirements-installed.json'
    python = tmp_path / 'Python With Spaces' / 'python.exe'
    calls = []
    monkeypatch.setattr(
        startup_requirements.subprocess,
        'run',
        lambda arguments, **options: calls.append((arguments, options)),
    )
    assert startup_requirements.ensure_requirements(
        root, python_executable=str(python), marker_path=marker
    )
    assert calls == [
        (
            [str(python.resolve()), '-m', 'pip', 'install', '-r', str(requirements)],
            {'cwd': str(root.resolve()), 'check': True},
        )
    ]
    recorded = json.loads(marker.read_text(encoding='utf-8'))
    assert recorded['python_executable'] == str(python.resolve())


def test_skips_pip_when_fingerprint_is_unchanged(tmp_path, monkeypatch):
    (tmp_path / 'requirements.txt').write_text('waitress>=3.0,<4.0\n', encoding='utf-8')
    marker = tmp_path / 'requirements-installed.json'
    monkeypatch.setattr(startup_requirements.subprocess, 'run', lambda *args, **kwargs: None)
    assert startup_requirements.ensure_requirements(tmp_path, marker_path=marker)

    def unexpected_run(*args, **kwargs):
        raise AssertionError('pip should not run for unchanged requirements')

    monkeypatch.setattr(startup_requirements.subprocess, 'run', unexpected_run)
    assert not startup_requirements.ensure_requirements(tmp_path, marker_path=marker)


def test_reinstalls_after_requirements_change(tmp_path, monkeypatch):
    requirements = tmp_path / 'requirements.txt'
    requirements.write_text('Flask>=3.0,<4.0\n', encoding='utf-8')
    marker = tmp_path / 'requirements-installed.json'
    calls = []
    monkeypatch.setattr(
        startup_requirements.subprocess,
        'run',
        lambda *args, **kwargs: calls.append(args),
    )
    startup_requirements.ensure_requirements(tmp_path, marker_path=marker)
    requirements.write_text('Flask>=3.0,<4.0\nwaitress>=3.0,<4.0\n', encoding='utf-8')
    assert startup_requirements.ensure_requirements(tmp_path, marker_path=marker)
    assert len(calls) == 2
