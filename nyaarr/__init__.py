import csv
import hashlib
import hmac
from io import StringIO

from flask import Flask, Response, current_app, jsonify, redirect, render_template, request, session, url_for

from .app_state import (
    activity_model,
    add_anime_to_library,
    apply_manual_anilist_id,
    apply_metadata_verification,
    allow_flagged_torrent,
    assign_manual_torrent,
    assign_manual_torrent_url,
    anime_detail_model,
    anime_library,
    calendar_model,
    delete_download_client,
    delete_root_folder,
    display_timezone_options,
    event_log_model,
    event_log_rows,
    create_superadmin_account,
    has_superadmin_account,
    load_or_create_session_secret,
    library_stats,
    manual_selection_model,
    metadata_verification_model,
    missing_settings_summary,
    reject_flagged_torrent,
    reject_manual_torrent,
    root_folder_missing,
    root_folder_scan_progress,
    save_display_settings,
    save_download_client,
    save_root_folder,
    sidebar_counts,
    test_download_client,
    verify_superadmin_login,
    user_settings,
)
from .metadata import search_anime_metadata
from .maintenance import start_periodic_maintenance
from .system_status import system_status_model
from .result_controls import (
    SORT_OPTIONS,
    STATUS_FILTERS,
    apply_result_controls,
    normalize_sort_key,
    normalize_status_filter,
)


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = load_or_create_session_secret()
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
    start_periodic_maintenance()

    @app.before_request
    def require_superadmin_session():
        if _auth_route_is_public():
            return None
        if not has_superadmin_account():
            if _wants_json_response():
                return jsonify({"ok": False, "auth_required": True, "setup_required": True, "redirect_url": url_for("setup_superadmin")}), 401
            return redirect(url_for("setup_superadmin", next=request.full_path if request.query_string else request.path))
        if _session_is_authenticated():
            return None
        if _wants_json_response():
            return jsonify({"ok": False, "auth_required": True, "redirect_url": url_for("login")}), 401
        return redirect(url_for("login", next=request.full_path if request.query_string else request.path))

    @app.get("/setup")
    def setup_superadmin():
        if has_superadmin_account():
            return redirect(url_for("login"))
        return render_template("auth.html", mode="setup", active_page="auth", message="", next_url=_safe_next_url(request.args.get("next")))

    @app.post("/setup")
    def setup_superadmin_post():
        next_url = _safe_next_url(request.form.get("next"))
        success, message = create_superadmin_account(
            request.form.get("username", ""),
            request.form.get("password", ""),
            request.form.get("confirm_password", ""),
        )
        if not success:
            return render_template("auth.html", mode="setup", active_page="auth", message=message, next_url=next_url), 400
        session.clear()
        session["superadmin_authenticated"] = True
        session["superadmin_username"] = request.form.get("username", "").strip()
        session["auth_fingerprint"] = _client_auth_fingerprint()
        return redirect(next_url or url_for("dashboard"))

    @app.get("/login")
    def login():
        if not has_superadmin_account():
            return redirect(url_for("setup_superadmin"))
        if _session_is_authenticated():
            return redirect(_safe_next_url(request.args.get("next")) or url_for("dashboard"))
        return render_template("auth.html", mode="login", active_page="auth", message="", next_url=_safe_next_url(request.args.get("next")))

    @app.post("/login")
    def login_post():
        next_url = _safe_next_url(request.form.get("next"))
        if verify_superadmin_login(request.form.get("username", ""), request.form.get("password", "")):
            session.clear()
            session["superadmin_authenticated"] = True
            session["superadmin_username"] = request.form.get("username", "").strip()
            session["auth_fingerprint"] = _client_auth_fingerprint()
            return redirect(next_url or url_for("dashboard"))
        return render_template("auth.html", mode="login", active_page="auth", message="Invalid username or password.", next_url=next_url), 401

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))
    @app.context_processor
    def inject_sidebar_counts():
        try:
            counts = sidebar_counts()
        except Exception:
            counts = _empty_sidebar_counts()
        return {"sidebar_counts": counts, "current_superadmin": session.get("superadmin_username", "")}

    @app.get("/sidebar-counts")
    def sidebar_counts_data():
        return jsonify(sidebar_counts())

    @app.get("/")
    def dashboard():
        return render_template(
            "dashboard.html",
            active_page="anime_list",
            anime_cards=anime_library(),
            stats=library_stats(),
        )

    @app.get("/anime/list")
    def anime_list():
        return dashboard()

    @app.get("/anime/list/data-page")
    def dashboard_data():
        return render_template(
            "dashboard.html",
            layout_template="_partial_base.html",
            active_page="anime_list",
            anime_cards=anime_library(),
            stats=library_stats(),
        )

    @app.get("/anime/<path:library_id>")
    def anime_detail(library_id: str):
        anime = anime_detail_model(library_id)
        if anime is None:
            if _wants_json_response():
                return jsonify({"ok": False, "message": "Anime was not found."}), 404
            return redirect(url_for("anime_list"))
        return render_template(
            "anime_detail.html",
            active_page="anime_list",
            anime=anime,
            anilist_summary=_anilist_summary_from_query(),
        )
    @app.post("/anime/<path:library_id>/anilist-id")
    def update_anime_anilist_id(library_id: str):
        success, message = apply_manual_anilist_id(library_id, request.form.get("anilist_id", ""))
        redirect_url = url_for("anime_detail", library_id=library_id, anilist_saved="1" if success else "0", anilist_message=message)
        if _wants_json_response():
            return jsonify({"ok": success, "message": message, "redirect_url": redirect_url})
        return redirect(redirect_url)

    @app.get("/anime/manual-selection")
    def manual_selection():
        return render_template(
            "manual_selection.html",
            active_page="anime_manual_selection",
            manual_selection={"items": [], "count": 0},
            selection_message=request.args.get("message", ""),
            loading=True,
            async_data_url=url_for("manual_selection_data_page"),
        )

    @app.get("/anime/manual-selection/data-page")
    def manual_selection_data_page():
        return render_template(
            "manual_selection.html",
            layout_template="_partial_base.html",
            active_page="anime_manual_selection",
            manual_selection=manual_selection_model(),
            selection_message=request.args.get("message", ""),
        )

    @app.post("/anime/manual-selection/select")
    def select_manual_torrent():
        success, message = assign_manual_torrent(
            request.form.get("library_id", ""),
            request.form.get("selection_key", ""),
        )
        if _wants_json_response():
            return jsonify({"ok": success, "message": message, "redirect_url": url_for("manual_selection", selected="1" if success else "0", message=message)})
        return redirect(url_for("manual_selection", selected="1" if success else "0", message=message))

    @app.post("/anime/manual-selection/link")
    def submit_manual_torrent_link():
        success, message = assign_manual_torrent_url(
            request.form.get("library_id", ""),
            request.form.get("torrent_link", ""),
            request.form.get("episode", ""),
        )
        redirect_url = url_for("manual_selection", selected="1" if success else "0", message=message)
        if _wants_json_response():
            return jsonify({"ok": success, "message": message, "redirect_url": redirect_url})
        return redirect(redirect_url)
    @app.post("/anime/manual-selection/reject")
    def reject_manual_torrent_route():
        success, message = reject_manual_torrent(
            request.form.get("library_id", ""),
            request.form.get("selection_key", ""),
        )
        if _wants_json_response():
            return jsonify({"ok": success, "message": message, "redirect_url": url_for("manual_selection", selected="1" if success else "0", message=message)})
        return redirect(url_for("manual_selection", selected="1" if success else "0", message=message))

    @app.get("/anime/metadata-verification")
    def metadata_verification():
        return render_template(
            "metadata_verification.html",
            active_page="anime_metadata_verification",
            metadata_verification={"items": [], "count": 0},
            verification_message=request.args.get("message", ""),
            loading=True,
            async_data_url=url_for("metadata_verification_data_page"),
        )

    @app.get("/anime/metadata-verification/data-page")
    def metadata_verification_data_page():
        return render_template(
            "metadata_verification.html",
            layout_template="_partial_base.html",
            active_page="anime_metadata_verification",
            metadata_verification=metadata_verification_model(),
            verification_message=request.args.get("message", ""),
        )

    @app.post("/anime/metadata-verification/select")
    def select_metadata_verification():
        success, message = apply_metadata_verification(
            request.form.get("library_id", ""),
            request.form.get("selection_key", ""),
        )
        redirect_url = url_for("metadata_verification", selected="1" if success else "0", message=message)
        if _wants_json_response():
            return jsonify({"ok": success, "message": message, "redirect_url": redirect_url})
        return redirect(redirect_url)

    @app.get("/calendar")
    def calendar():
        view = request.args.get("view", "week")
        anchor_date = request.args.get("date")
        return render_template(
            "calendar.html",
            active_page="calendar",
            calendar=calendar_model(view, anchor_date),
        )

    @app.get("/calendar/data-page")
    def calendar_data_page():
        return render_template(
            "calendar.html",
            layout_template="_partial_base.html",
            active_page="calendar",
            calendar=calendar_model(request.args.get("view", "week"), request.args.get("date")),
        )

    @app.get("/activity")
    @app.get("/activity/<section>")
    def activity(section: str = "queued"):
        model = _empty_activity_model(section)
        return render_template(
            "activity.html",
            active_page=f"activity_{model['section']}",
            activity=model,
        )

    @app.get("/activity/<section>/page-data")
    def activity_data_page(section: str = "queued"):
        model = _empty_activity_model(section)
        return render_template(
            "activity.html",
            layout_template="_partial_base.html",
            active_page=f"activity_{model['section']}",
            activity=model,
        )

    @app.get("/activity/<section>/data")
    def activity_data(section: str = "queued"):
        return jsonify(activity_model(section))

    @app.get("/add")
    def add_anime():
        query = request.args.get("q", "").strip()
        status_filter = normalize_status_filter(request.args.get("status", "all"))
        sort_key = normalize_sort_key(request.args.get("sort", "relevance"))
        return render_template(
            "add_anime.html",
            active_page="add",
            notices=[],
            query=query,
            results=[],
            sort_key=sort_key,
            sort_options=SORT_OPTIONS,
            status_filter=status_filter,
            status_filters=STATUS_FILTERS,
            total_results=0,
            defer_search=bool(query),
        )

    @app.get("/add/search")
    def add_anime_search():
        query = request.args.get("q", "").strip()
        status_filter = normalize_status_filter(request.args.get("status", "all"))
        sort_key = normalize_sort_key(request.args.get("sort", "relevance"))
        results, notices = search_anime_metadata(query)
        controlled_results = apply_result_controls(results, status_filter, sort_key)
        html = render_template(
            "_metadata_results.html",
            notices=notices,
            query=query,
            results=controlled_results,
            sort_key=sort_key,
            sort_options=SORT_OPTIONS,
            status_filter=status_filter,
            status_filters=STATUS_FILTERS,
            total_results=len(results),
        )
        return jsonify({"html": html, "total_results": len(results), "shown_results": len(controlled_results), "notices": notices})

    @app.get("/settings")
    def settings():
        return render_template(
            "settings.html",
            active_page="settings",
            download_client_summary=_download_client_summary_from_query(),
            display_summary=_display_summary_from_query(),
            import_summary=_import_summary_from_query(),
            root_folder_missing=root_folder_missing(),
            settings=user_settings(),
        )

    @app.get("/settings/data-page")
    def settings_data_page():
        return render_template(
            "settings.html",
            layout_template="_partial_base.html",
            active_page="settings",
            download_client_summary=_download_client_summary_from_query(),
            display_summary=_display_summary_from_query(),
            import_summary=_import_summary_from_query(),
            root_folder_missing=root_folder_missing(),
            settings=user_settings(),
        )

    @app.get("/system/logs")
    @app.get("/system/events")
    def system_logs():
        return render_template(
            "events.html",
            active_page="system_logs",
            events={"rows": [], "count": 0},
            loading=True,
            async_data_url=url_for("system_logs_data_page"),
        )

    @app.get("/system/logs/data-page")
    @app.get("/system/events/data-page")
    def system_logs_data_page():
        return render_template(
            "events.html",
            layout_template="_partial_base.html",
            active_page="system_logs",
            events=event_log_model(),
        )

    @app.get("/system/logs.csv")
    def system_logs_csv():
        output = StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=["created_at", "category", "anime", "torrent", "status", "message"],
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(event_log_rows(limit=None))
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=nyaarr-system-logs.csv"},
        )

    @app.get("/system/status")
    def system_status():
        return render_template(
            "system_status.html",
            active_page="system_status",
            status=system_status_model(),
        )

    @app.get("/system/status/data-page")
    def system_status_data_page():
        return render_template(
            "system_status.html",
            layout_template="_partial_base.html",
            active_page="system_status",
            status=system_status_model(),
        )

    @app.post("/settings/root-folder")
    def update_root_folder():
        success, message, import_summary = save_root_folder(request.form.get("root_folder", ""))
        if request.headers.get("Accept") == "application/json" or request.headers.get("X-Requested-With") == "fetch":
            return jsonify({"ok": success, "message": message, "summary": import_summary, "progress": root_folder_scan_progress()})
        return redirect(
            url_for(
                "settings",
                saved="1" if success else "0",
                message=message,
                imported=import_summary["imported"],
                updated=import_summary["updated"],
                skipped=import_summary["skipped"],
                verified=import_summary["verified"],
                manual_verification=import_summary["manual_verification"],
                removed=0,
            )
        )

    @app.post("/settings/root-folder/delete")
    def delete_root_folder_route():
        success, message, import_summary = delete_root_folder()
        redirect_url = url_for(
            "settings",
            saved="1" if success else "0",
            message=message,
            imported=import_summary["imported"],
            updated=import_summary["updated"],
            skipped=import_summary["skipped"],
            verified=import_summary["verified"],
            manual_verification=import_summary["manual_verification"],
            removed=import_summary.get("removed", 0),
        )
        if _wants_json_response():
            return jsonify({"ok": success, "message": message, "summary": import_summary, "redirect_url": redirect_url})
        return redirect(redirect_url)

    @app.get("/settings/root-folder/progress")
    def root_folder_progress():
        return jsonify(root_folder_scan_progress())


    @app.get("/settings/status")
    def settings_status():
        return jsonify(missing_settings_summary())

    @app.post("/settings/display")
    def update_display_settings():
        success, message = save_display_settings(request.form)
        redirect_url = url_for("settings", display_saved="1" if success else "0", display_message=message)
        if _wants_json_response():
            return jsonify({"ok": success, "message": message, "redirect_url": redirect_url})
        return redirect(redirect_url)

    @app.post("/settings/download-client")
    def update_download_client():
        success, message = save_download_client(request.form)
        redirect_url = url_for("settings", client_saved="1" if success else "0", client_message=message)
        if _wants_json_response():
            return jsonify({"ok": success, "message": message, "redirect_url": redirect_url})
        return redirect(redirect_url)

    @app.post("/settings/download-client/test")
    def test_download_client_route():
        success, message = test_download_client(request.form if request.form else None)
        if request.headers.get("Accept") == "application/json" or request.headers.get("X-Requested-With") == "fetch":
            return jsonify({"ok": success, "message": message})
        return redirect(
            url_for(
                "settings",
                client_saved="1" if success else "0",
                client_message=message,
            )
        )

    @app.post("/settings/download-client/delete")
    def delete_download_client_route():
        success, message = delete_download_client()
        redirect_url = url_for("settings", client_saved="1" if success else "0", client_message=message)
        if _wants_json_response():
            return jsonify({"ok": success, "message": message, "redirect_url": redirect_url})
        return redirect(redirect_url)

    @app.post("/anime")
    def add_anime_to_library_route():
        anime = {
            "library_id": request.form["library_id"],
            "title": request.form["title"],
            "original_title": request.form.get("original_title", ""),
            "year": request.form.get("year", "Unknown"),
            "status": request.form.get("status", "Unknown"),
            "episodes": request.form.get("episodes", "Unknown"),
            "season_number": _posted_season_number(request.form.get("season_number")),
            "runtime": request.form.get("runtime", "Unknown"),
            "genres": request.form.get("genres", "").split("|") if request.form.get("genres") else [],
            "studio": request.form.get("studio", "Unknown"),
            "source": request.form.get("source", "Unknown"),
            "rating": request.form.get("rating", "Unrated"),
            "synopsis": request.form.get("synopsis", ""),
            "poster": request.form.get("poster", ""),
            "air_date": request.form.get("air_date", ""),
            "next_airing_at": request.form.get("next_airing_at", ""),
            "airing_episode": request.form.get("airing_episode", ""),
            "airing_source": request.form.get("airing_source", ""),
            "quality_resolution": _posted_quality_resolution(request.form.get("quality_resolution")),
        }
        torrent_search = {
            "query": anime["title"],
            "strategy": "Torrent search pending",
            "candidates": [],
            "notices": [],
        }
        add_anime_to_library(anime, torrent_search, request.form.get("nyaa_link", ""))
        if _wants_json_response():
            return jsonify({"ok": True, "message": f"Added {anime['title']}.", "redirect_url": url_for("anime_list")})
        return redirect(url_for("anime_list"))

    @app.post("/torrents/flagged/allow")
    def allow_flagged_torrent_route():
        success, message = allow_flagged_torrent(request.form.get("library_id", ""))
        if _wants_json_response():
            return jsonify({"ok": success, "message": message, "redirect_url": url_for("dashboard")})
        return redirect(url_for("anime_list"))

    @app.post("/torrents/flagged/reject")
    def reject_flagged_torrent_route():
        success, message = reject_flagged_torrent(request.form.get("library_id", ""))
        if _wants_json_response():
            return jsonify({"ok": success, "message": message, "redirect_url": url_for("dashboard")})
        return redirect(url_for("anime_list"))

    return app


def _empty_sidebar_counts() -> dict[str, int]:
    return {
        "anime": 0,
        "activity": 0,
        "manual_selection": 0,
        "metadata_verification": 0,
        "wanted": 0,
        "settings_missing": 0,
        "events": 0,
    }


def _empty_calendar_model(view: str = "week", anchor_date: str | None = None) -> dict[str, object]:
    selected = view if view in {"week", "month"} else "week"
    anchor = anchor_date or ""
    return {
        "view": selected,
        "anchor_date": anchor,
        "period_label": "Loading calendar",
        "previous_date": anchor,
        "next_date": anchor,
        "today": "",
        "today_label": "Loading",
        "days": [],
        "scheduled_count": 0,
        "airing_count": 0,
        "upcoming_entries": [],
    }


def _empty_activity_model(section: str = "queued") -> dict[str, object]:
    labels = {"queued": "Queued", "history": "History", "blocked": "Blocked"}
    selected = section if section in labels else "queued"
    return {
        "section": selected,
        "label": labels[selected],
        "description": "Loading activity.",
        "rows": [],
        "counts": {"queued": 0, "history": 0, "blocked": 0},
    }


def _empty_settings_model() -> dict[str, object]:
    return {
        "root_folder": "",
        "timezone": "GMT+8",
        "timezone_label": "GMT+8",
        "timezone_options": display_timezone_options(),
        "download_client": {
            "enabled": False,
            "implementation": "",
            "name": "",
            "host": "",
            "port": 8080,
            "url_base": "",
            "use_ssl": False,
            "username": "",
            "password": "",
            "category": "nyaarr",
            "recent_priority": "Last",
            "older_priority": "Last",
            "add_paused": False,
            "remote_path_mapping_enabled": False,
            "remote_path": "",
            "local_path": "",
        },
    }


def _empty_system_status_model() -> dict[str, object]:
    return {
        "disks": [],
        "about": [],
        "uptime": {"seconds": 0, "label": "Loading", "started_at": "Loading"},
        "links": [],
    }

def _session_is_authenticated() -> bool:
    if session.get("superadmin_authenticated") is not True:
        return False
    expected = str(session.get("auth_fingerprint") or "")
    current = _client_auth_fingerprint()
    if not expected or not hmac.compare_digest(expected, current):
        session.clear()
        return False
    return True


def _client_auth_fingerprint() -> str:
    client_ip = _client_ip_address()
    user_agent = request.headers.get("User-Agent", "")[:300]
    payload = f"{client_ip}|{user_agent}".encode("utf-8", errors="ignore")
    secret = str(current_app.secret_key or "").encode("utf-8", errors="ignore")
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def _client_ip_address() -> str:
    for header in ("CF-Connecting-IP", "True-Client-IP", "X-Real-IP"):
        value = str(request.headers.get(header) or "").strip()
        if value:
            return value.split(",", 1)[0].strip()
    forwarded = str(request.headers.get("X-Forwarded-For") or "").strip()
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return str(request.remote_addr or "")

def _auth_route_is_public() -> bool:
    return request.endpoint in {"static", "setup_superadmin", "setup_superadmin_post", "login", "login_post"}


def _safe_next_url(value: str | None) -> str:
    target = str(value or "").strip()
    if not target or not target.startswith("/") or target.startswith("//"):
        return ""
    if target.startswith(("/login", "/setup", "/logout")):
        return ""
    return target

def _wants_json_response() -> bool:
    return request.headers.get("Accept") == "application/json" or request.headers.get("X-Requested-With") == "fetch"


def _posted_season_number(value: str | None) -> int:
    try:
        return max(int(value or 1), 1)
    except ValueError:
        return 1


def _posted_quality_resolution(value: str | None) -> str:
    selected = str(value or "1080p").strip().casefold()
    if selected == "bd":
        return "BD"
    if selected == "720p":
        return "720p"
    return "1080p"


def _anilist_summary_from_query() -> dict[str, str] | None:
    message = request.args.get("anilist_message")
    if not message:
        return None
    return {"ok": request.args.get("anilist_saved") == "1", "message": message}


def _display_summary_from_query() -> dict[str, str] | None:
    message = request.args.get("display_message")
    if not message:
        return None
    return {"ok": request.args.get("display_saved") == "1", "message": message}

def _import_summary_from_query() -> dict[str, str | int] | None:
    message = request.args.get("message")
    if not message:
        return None
    return {
        "ok": request.args.get("saved") == "1",
        "message": message,
        "imported": _posted_count(request.args.get("imported")),
        "updated": _posted_count(request.args.get("updated")),
        "skipped": _posted_count(request.args.get("skipped")),
        "verified": _posted_count(request.args.get("verified")),
        "manual_verification": _posted_count(request.args.get("manual_verification")),
        "removed": _posted_count(request.args.get("removed")),
    }


def _download_client_summary_from_query() -> dict[str, str | bool] | None:
    message = request.args.get("client_message")
    if not message:
        return None
    return {
        "ok": request.args.get("client_saved") == "1",
        "message": message,
    }


def _posted_count(value: str | None) -> int:
    try:
        return max(int(value or 0), 0)
    except ValueError:
        return 0
















