# Torrent Dispatch Reliability

## What changed

Resolved torrent candidates are now retried during startup and the
high-priority local maintenance pass, in addition to the external Nyaa refresh
pass. This prevents a candidate already stored in Nyaarr from waiting behind
slower metadata or provider jobs before it is submitted to qBittorrent.

The existing dispatch checks remain in force: the anime must be monitored and
missing episodes, qBittorrent and the root folder must be configured, manual
selection must not be required, and the retry cooldown must have elapsed.
Candidate and qBittorrent identity checks keep retries idempotent.

qBittorrent's torrent-add endpoint can return HTTP 200 with a textual `Fails.`
body. The client adapter now requires the documented `Ok.` response before
Nyaarr creates a queued record. Rejections remain candidates, are logged as
dispatch failures, and can be retried after the cooldown. Previously those
responses could produce a false queued row with unknown ETA and no progress.

An `Ok.` response is also only command acceptance. When Nyaa supplied an
infohash, Nyaarr polls qBittorrent briefly for that exact hash. Slower
asynchronous URL ingestion is stored as `Submitted · awaiting client`, not as a
false queued torrent or a dispatch failure. Reconciliation allows a 90-second
visibility grace period (`NYAARR_TORRENT_SUBMISSION_VISIBILITY_GRACE_SECONDS`),
then returns a still-invisible submission to retry. Once visible, normal safety
inspection and startup continue.

## Queued episode indicators

The Queued view intentionally includes every pending episode. Each row has a
lifecycle pill so presence in that view is not confused with qBittorrent
acceptance: waiting for torrent, resolved and dispatch pending, checking client,
safety check, downloading, paused, stalled, client error, or needs review.
Resolved per-episode candidates show their release title immediately and remain
eligible for the startup/local dispatch path.

## Bounded proactive safety pipeline

Each anime submits at most four resolved torrents per maintenance pass by
default (`NYAARR_MAX_TORRENT_DISPATCHES_PER_ANIME_TICK`). A backlog bypasses the
normal failed-dispatch cooldown so the next local pass continues draining it.
This bounds qBittorrent API and metadata pressure while remaining proactive.
At most two anime are dispatched per pass by default
(`NYAARR_MAX_TORRENT_DISPATCH_ANIME_PER_TICK`), producing a default global
ceiling of eight new torrent submissions per minute. Both limits are tunable
without adding workers or persistent memory.

After each confirmed add, Nyaarr immediately reads the torrent file list while
the torrent is paused. Safe torrents have batch file priorities applied when
needed and are started immediately. Missing file metadata remains in Safety
check for reconciliation; flagged content never starts. The user's Add Paused
setting still takes precedence.

## Resource impact and limitations

No worker or cache was added. The local maintenance pass may make one extra
qBittorrent API check for an anime with pending candidates, using the existing
60-second maintenance schedule and five-minute failed-dispatch cooldown. Nyaa
is not contacted by this retry path. A server that cannot reach qBittorrent
will retain the candidate and retry after the cooldown while recording the
client error in torrent notices.
