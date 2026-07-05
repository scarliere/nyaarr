# UI/UX Leftovers

These are the remaining UI/UX improvements after the current dashboard, add-flow, and responsive table updates.

## Detail Pages

- Redesign anime detail pages around next action first: missing episodes, active downloads, metadata issues, and monitor settings should be visible before lower-priority metadata.
- Add stronger empty and error states for episode lists, manual torrent assignment, and metadata review when providers or download clients are unavailable.

## Feedback And Recovery

- Replace redirect-only form feedback with inline success/error states for add, select, reject, unblock, and manual link assignment actions.
- Add consistent confirmation copy for destructive actions, especially library removal and torrent rejection.

## Controls And Accessibility

- Standardize action buttons with icons, labels, and disabled/loading states across dashboard, activity, manual selection, metadata review, and detail pages.
- Add ARIA live regions for async table refreshes and form submissions so background changes are announced correctly.
- Audit keyboard focus order and focus-visible styling after async page swaps.

## Visual Polish

- Tighten the detail-page hierarchy and reduce repeated panel chrome where adjacent sections are part of the same workflow.
- Review color contrast and state colors across warning, danger, success, and muted status treatments.