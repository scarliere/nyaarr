from __future__ import annotations

import json

import nyaarr
from nyaarr import app_state


def _isolated_auth_app(monkeypatch, tmp_path):
    monkeypatch.setattr(nyaarr, "start_periodic_maintenance", lambda: None)
    monkeypatch.setattr(app_state, "USER_DATABASE_PATH", tmp_path / "anime-library.json")
    monkeypatch.setattr(app_state, "SESSION_SECRET_PATH", tmp_path / "session-secret.key")
    app = nyaarr.create_app()
    app.config.update(TESTING=True)
    return app


def test_first_run_redirects_to_superadmin_setup(monkeypatch, tmp_path) -> None:
    app = _isolated_auth_app(monkeypatch, tmp_path)

    response = app.test_client().get("/")

    assert response.status_code == 302
    assert response.headers["Location"].startswith("/setup")


def test_superadmin_setup_stores_hash_not_password(monkeypatch, tmp_path) -> None:
    app = _isolated_auth_app(monkeypatch, tmp_path)
    client = app.test_client()

    response = client.post(
        "/setup",
        data={"username": "admin", "password": "CorrectHorse1!", "confirm_password": "CorrectHorse1!"},
    )

    assert response.status_code == 302
    database = json.loads((tmp_path / "anime-library.json").read_text(encoding="utf-8"))
    superadmin = database["auth"]["superadmin"]
    assert superadmin["username"] == "admin"
    assert superadmin["role"] == "superadmin"
    assert "password" not in superadmin
    assert superadmin["password_hash"] != "CorrectHorse1!"
    assert superadmin["password_hash"].startswith("scrypt:")


def test_existing_superadmin_requires_login(monkeypatch, tmp_path) -> None:
    app = _isolated_auth_app(monkeypatch, tmp_path)
    client = app.test_client()
    client.post(
        "/setup",
        data={"username": "admin", "password": "CorrectHorse1!", "confirm_password": "CorrectHorse1!"},
    )
    client.post("/logout")

    blocked = client.get("/")
    failed = client.post("/login", data={"username": "admin", "password": "wrong-password"})
    logged_in = client.post("/login", data={"username": "admin", "password": "CorrectHorse1!"})

    assert blocked.status_code == 302
    assert blocked.headers["Location"].startswith("/login")
    assert failed.status_code == 401
    assert logged_in.status_code == 302
    assert logged_in.headers["Location"] == "/"

def test_cloudflare_network_change_forces_login_prompt(monkeypatch, tmp_path) -> None:
    app = _isolated_auth_app(monkeypatch, tmp_path)
    client = app.test_client()
    first_network = {"CF-Connecting-IP": "203.0.113.10", "User-Agent": "DeviceA"}
    second_network = {"CF-Connecting-IP": "198.51.100.25", "User-Agent": "DeviceA"}

    client.post(
        "/setup",
        data={"username": "admin", "password": "CorrectHorse1!", "confirm_password": "CorrectHorse1!"},
        headers=first_network,
    )
    same_network = client.get("/", headers=first_network)
    changed_network = client.get("/", headers=second_network)

    assert same_network.status_code == 200
    assert changed_network.status_code == 302
    assert changed_network.headers["Location"].startswith("/login")