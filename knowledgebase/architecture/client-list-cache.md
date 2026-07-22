# Client List Cache

## What changed

List-oriented pages keep their most recently rendered data in browser
`sessionStorage` for two minutes. Returning to Anime List, Manual Selection,
Metadata Review, Calendar, Settings, System Logs, System Status, Activity, or an
Add Anime search restores the saved result immediately instead of showing the
loading placeholder and repeating the same request. Cached Anime Detail episode
titles and complete Anime Detail fragments are restored through the same
mechanism. Anime Detail first renders a lightweight shell and loads its
database-backed model from `/anime/<library_id>/data-page`, keeping navigation
responsive while the detail calculation runs.

The common loader owns HTML-fragment caching. Activity and Add Anime use the
same cache for their JSON-backed lists. A fresh entry avoids another request;
an older entry is replaced by the next server result.
The cache is capped at the 24 newest entries per tab to keep storage use bounded.

The combined UI bootstrap snapshot is cached as well. During full menu
navigation, the new document restores Anime, Manual Selection, Metadata Review,
Activity, Events, and Settings badge values immediately after parsing the
sidebar and before rendering the main page. The normal conditional bootstrap
request then refreshes those values without making counters disappear and
reappear between menu items.

## Invalidation and limitations

Submitting any POST form clears all cached lists before the mutation runs. This
prevents library, torrent, metadata, and settings changes from restoring an old
view. Entries are scoped to the current browser tab and disappear when its
session ends. Activity polling continues after restoration, so download
progress can update without returning to a loading state.

The one-minute UI bootstrap poll carries the database revision. When background
reconciliation changes that revision, cached fragments are invalidated and the
currently visible asynchronous page is refreshed while the tab is visible.
This allows Anime List and Anime Detail episode states to reflect completed
downloads without waiting for the two-minute cache TTL or requiring a hard
refresh.

The cache is a responsiveness layer, not persistent application storage. A
page older than two minutes is refreshed from the server.

## Resource and scaling trade-offs

This adds no server-side cache, worker, or persistent memory cost. It uses
bounded browser `sessionStorage`; actual size varies with list and episode
counts and remains constrained by the browser's per-origin quota. The first
detail visit still performs the existing whole-library state read in the
background, so server CPU and latency can grow with library size. Splitting
anime records into an indexed repository is the next scaling step if measured
detail-generation time becomes significant; that requires a data migration and
is intentionally separate from this low-risk deployment improvement.
