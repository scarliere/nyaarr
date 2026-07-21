# Service Orchestration and State

Nyaarr is a modular monolith: the web UI, scheduler, and service adapters ship as
one local installation, while durable jobs isolate library, provider, download,
and import work from interactive page requests.

## State repository

`nyaarr/persistence.py` stores the document-shaped application state in SQLite
using WAL mode and a monotonically increasing revision. The first read imports
the existing `anime-library.json`, creates a one-time `anime-library.pre-sqlite.json`
recovery copy, and continues writing an atomic JSON mirror for compatibility.

Concurrent stale writes use a three-way merge keyed by stable identities such as
`library_id`, `ignore_key`, `hash`, and `created_at`. This prevents independent
maintenance, root-scan, and user changes from replacing one another. SQLite is
authoritative after migration. Set `NYAARR_STATE_DATABASE_PATH` to override its
default location beside the JSON user database.

Routine reads no longer rescan anime folders or regenerate NFO files. Filesystem
completion is refreshed by local reconciliation jobs, and NFO files are checked
by that same local lane.

## Durable jobs

`nyaarr/job_queue.py` provides SQLite-backed jobs with idempotency keys, priority,
leases, bounded exponential retry, and retained failure details. The scheduler in
`nyaarr/maintenance.py` runs bounded workers for:

- startup and local qBittorrent/filesystem reconciliation;
- nyaa.si, poster, and dispatch refreshes;
- one unified AniList metadata/airing refresh plus lazy Calendar window hydration;
- low-priority paginated Jikan episode-title enrichment;
- root-folder scans;
- daily anime-offline-database cache maintenance.

Root scans survive a restart as queued jobs. Expired running leases return to the
retry queue. System Status reports queue counts, oldest pending work, and recent
permanent failures. It also retains bounded route, job, metadata, Nyaa, and
qBittorrent latency samples with average, p95, maximum, and failure counts.
Configure worker concurrency with `NYAARR_JOB_WORKERS`.

External request spacing no longer sleeps inside the coordinator. Existing
per-tick caps remain the provider backpressure mechanism, while identical Nyaa
and metadata requests share one in-flight future and a short-lived result cache.
AniList 429 responses carry the provider's `Retry-After` delay into durable job
rescheduling.
Jikan uses its own serialized one-request-per-second lane so concurrent workers
cannot exceed the provider's 60-request-per-minute ceiling.

## Web request path

Dashboard, Calendar, Settings, and System Status now render the common shell and
loading model before fetching their page fragment. Manual Selection, Metadata
Review, Logs, Activity, and Add Anime retain their existing asynchronous paths.

The shared shell calls `/api/ui/bootstrap` for sidebar counts, missing settings,
root-scan state, job health, and the current state revision. Requests are
coalesced in the browser and use ETags, so unchanged polls return `304` without
rerendering. Older count/status endpoints remain available for compatibility.

Non-debug launches use Waitress with `NYAARR_WEB_THREADS` (default `8`). Debug
mode continues to use Flask's development server.

## Adapter behavior

- Nyaa RSS records retain `raw_title` and a `raw` metadata object alongside the
  conservative `parsed` fields and existing compatibility fields.
- Identical RSS and metadata searches are coalesced so concurrent callers do not
  repeat provider work.
- AniList metadata, next-airing state, and recent exact episode dates share one
  snapshot callback. AniChart uses that same underlying API and has no duplicate
  adapter.
- Calendar history is an indexed local read; missing months are hydrated lazily
  in background jobs only when a user navigates to them.
- Episode titles are another indexed local read. Jikan fills missing/stale title
  pages asynchronously by MAL ID and is never part of an operational decision.
- Ongoing-series batches must prove wanted episode coverage from bounded torrent
  metainfo before they can suppress episode searches or dispatch.
- Offline metadata database downloads occur in a low-priority daily job, never in
  an interactive search request.
- Authenticated qBittorrent clients are reused for five minutes and recreated
  when settings change.

## Current limitations

- The domain state remains a single versioned JSON document inside SQLite; the
  repository boundary allows gradual normalization without changing routes.
- Local and external maintenance lanes can overlap, but work inside each lane is
  still intentionally serialized by its idempotent job key.
- The JSON mirror is for recovery and compatibility, not a second writable source.
- Completed jobs retain only the latest 200 records; failed jobs remain visible
  until manually addressed or a later implementation adds failure dismissal.
