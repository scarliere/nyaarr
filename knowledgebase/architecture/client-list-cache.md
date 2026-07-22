# Client List Cache

## What changed

List-oriented pages keep their most recently rendered data in browser
`sessionStorage` for two minutes. Returning to Anime List, Manual Selection,
Metadata Review, Calendar, Settings, System Logs, System Status, Activity, or an
Add Anime search restores the saved result immediately instead of showing the
loading placeholder and repeating the same request. Cached Anime Detail episode
titles are restored through the same mechanism.

The common loader owns HTML-fragment caching. Activity and Add Anime use the
same cache for their JSON-backed lists. A fresh entry avoids another request;
an older entry is replaced by the next server result.

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

The cache is a responsiveness layer, not persistent application storage. A
page older than two minutes is refreshed from the server.
