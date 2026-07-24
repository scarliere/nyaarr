from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

ACTIVE_STATES = {"downloading", "forceddl", "metadl", "queueddl", "stalleddl"}
SLOW_BYTES_PER_SECOND = 100 * 1024
SLOW_GRACE_SECONDS = 2 * 60
SLOW_WINDOW_SECONDS = 10 * 60


def enforce_download_limit(
    client: Any,
    torrents: list[dict[str, Any]],
    queues_by_hash: dict[str, dict[str, Any]],
    *,
    limit: int = 5,
    now: datetime | None = None,
) -> dict[str, int]:
    """Keep at most ``limit`` Nyaarr downloads active and rotate proven-slow work.

    Completed/seeding torrents and user/safety-paused items are never counted or
    mutated. Slow state is persisted on the queue record so restarts remain fair.
    """
    now = now or datetime.now(timezone.utc)
    limit = max(1, min(int(limit), 5))
    active: list[tuple[dict[str, Any], dict[str, Any]]] = []
    resumable: list[tuple[dict[str, Any], dict[str, Any]]] = []
    summary = {"active": 0, "paused": 0, "resumed": 0, "slow_rotated": 0}

    for torrent in torrents:
        torrent_hash = str(torrent.get("hash") or "").casefold()
        queue = queues_by_hash.get(torrent_hash)
        if queue is None:
            continue
        state = str(torrent.get("state") or "")
        progress = float(torrent.get("progress") or 0)
        speed = int(torrent.get("dlspeed") or 0)
        queue["download_speed"] = speed
        if progress >= 1 or state.casefold().endswith("up"):
            continue
        if queue.get("user_add_paused") or queue.get("safety_status") not in {"safe", "allowed"}:
            continue
        if state in ACTIVE_STATES:
            active.append((torrent, queue))
            queued_at = _date(queue.get("queued_at")) or now
            if speed < SLOW_BYTES_PER_SECOND and (now - queued_at).total_seconds() >= SLOW_GRACE_SECONDS:
                slow_since = _date(queue.get("slow_since"))
                if slow_since is None:
                    queue["slow_since"] = now.isoformat()
                elif (now - slow_since).total_seconds() >= SLOW_WINDOW_SECONDS:
                    client.pause(torrent_hash)
                    queue["scheduler_pause_reason"] = "slow_rotation"
                    queue["slow_pause_count"] = int(queue.get("slow_pause_count") or 0) + 1
                    cooldown = min(15 * (2 ** (queue["slow_pause_count"] - 1)), 6 * 60)
                    queue["scheduler_resume_after"] = (now + timedelta(minutes=cooldown)).isoformat()
                    queue["message"] = "Paused and rotated after remaining below 100 KiB/s for 10 minutes."
                    summary["paused"] += 1
                    summary["slow_rotated"] += 1
            else:
                queue.pop("slow_since", None)
        elif queue.get("scheduler_pause_reason") in {"capacity", "slow_rotation"}:
            due = _date(queue.get("scheduler_resume_after"))
            if due is None or due <= now:
                resumable.append((torrent, queue))

    active = [(torrent, queue) for torrent, queue in active if not queue.get("scheduler_pause_reason")]
    # Manual boosts, near-complete items, then oldest requests win.
    active.sort(key=lambda item: _priority(item[0], item[1]))
    while len(active) > limit:
        torrent, queue = active.pop()
        client.pause(str(torrent.get("hash") or ""))
        queue["scheduler_pause_reason"] = "capacity"
        queue["scheduler_resume_after"] = ""
        queue["message"] = "Paused by Nyaarr's five-download capacity controller."
        summary["paused"] += 1

    for torrent, queue in sorted(resumable, key=lambda item: _priority(item[0], item[1])):
        if len(active) >= limit:
            break
        client.resume(str(torrent.get("hash") or ""))
        queue.pop("scheduler_pause_reason", None)
        queue.pop("scheduler_resume_after", None)
        queue["message"] = "Resumed by Nyaarr's download capacity controller."
        active.append((torrent, queue))
        summary["resumed"] += 1
    summary["active"] = len(active)
    return summary


def _priority(torrent: dict[str, Any], queue: dict[str, Any]) -> tuple[int, float, str]:
    boosted = 0 if queue.get("manual_selected") else 1
    progress = -float(torrent.get("progress") or 0)
    return boosted, progress, str(queue.get("queued_at") or "")


def _date(value: Any) -> datetime | None:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
