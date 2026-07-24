from datetime import datetime, timedelta, timezone

from nyaarr.torrent_scheduler import enforce_download_limit


class Client:
    def __init__(self):
        self.paused = []
        self.resumed = []

    def pause(self, torrent_hash):
        self.paused.append(torrent_hash)

    def resume(self, torrent_hash):
        self.resumed.append(torrent_hash)


def torrent(index, *, speed=200_000, progress=0.2, state="downloading"):
    return {"hash": f"h{index}", "state": state, "progress": progress, "dlspeed": speed}


def queue(index, now):
    return {"hash": f"h{index}", "queued_at": (now - timedelta(hours=1)).isoformat(), "safety_status": "safe"}


def test_controller_never_leaves_more_than_five_active():
    now = datetime.now(timezone.utc)
    client = Client()
    torrents = [torrent(index) for index in range(7)]
    queues = {f"h{index}": queue(index, now) for index in range(7)}

    summary = enforce_download_limit(client, torrents, queues, now=now)

    assert summary["active"] == 5
    assert summary["paused"] == 2
    assert len(client.paused) == 2
    assert all(queues[item]["scheduler_pause_reason"] == "capacity" for item in client.paused)


def test_slow_torrent_rotates_only_after_continuous_window():
    now = datetime.now(timezone.utc)
    client = Client()
    torrents = [torrent(1, speed=99 * 1024)]
    queues = {"h1": queue(1, now)}
    queues["h1"]["slow_since"] = (now - timedelta(minutes=11)).isoformat()

    summary = enforce_download_limit(client, torrents, queues, now=now)

    assert summary["slow_rotated"] == 1
    assert client.paused == ["h1"]
    assert queues["h1"]["scheduler_pause_reason"] == "slow_rotation"


def test_user_paused_and_completed_torrents_are_excluded():
    now = datetime.now(timezone.utc)
    client = Client()
    torrents = [torrent(1, state="pausedDL"), torrent(2, progress=1.0, state="uploading")]
    queues = {"h1": {**queue(1, now), "user_add_paused": True}, "h2": queue(2, now)}

    summary = enforce_download_limit(client, torrents, queues, now=now)

    assert summary == {"active": 0, "paused": 0, "resumed": 0, "slow_rotated": 0}
    assert client.paused == []
    assert client.resumed == []
