# Plan: low-effort session persistence

Status: **implemented; awaiting studio verification** (2026-11-13). No application build or release made. Branch: `feature/session-persistence` from `main`.

Keep the one current workspace between app runs without introducing project files, workspace Save/Open commands, or session management UI.

## Agreed decisions

- Save on exit, and periodically when two minutes have elapsed and the app has been inactive for at least 15 seconds. Persistence must not interfere with normal operation.
- Restore workspace plus settings/view, with fresh undo/redo history.
- Session persistence is controlled by an internal boolean setting, **enabled by default**. Store it in app settings independently of the session file so it can be exposed in a future settings UI. No visible switch in this feature.
- Enforce a single app instance. Do not allow additional temporary workspaces or last-writer-wins saving.
- Keep the implementation small and reuse existing model, controller, import and settings behaviour; do not introduce parallel implementations of those features.
- Use an explicit session schema version as the compatibility gate. Incompatible model changes must bump it; incompatible or damaged sessions must never crash startup.

- A second launch passes supplied MIDI files to the existing window for normal additive import, then exits. It never opens a second workspace or reads/writes the saved session. A launch without files raises the existing window and exits.

## Proposed behaviour

- Read the persistence-enabled setting before loading session data. When disabled, start without restoring the session and perform no periodic or exit session saves. Leave any existing saved session intact. The setting is read at startup; live toggling is outside this feature's scope.
- Single-instance enforcement and file handoff remain active regardless of the persistence setting. Normal imports, exports and existing app preferences continue to work when persistence is disabled.
- Startup restores the previous session automatically. No saved session means the usual empty workspace.
- Keep tracks and their order, names, colours, mute/solo (including remembered mutes), export-channel overrides and source-channel information.
- Keep every clip, its source association, position, events, full extent and edge trims. Keep source MIDI bytes and provenance, the workspace tempo map and selected tempo source.
- Keep ranges, order, names, exact boundaries, included/excluded tracks and track-lock states. Preserve IDs so relationships remain intact.
- The session is self-contained: reopening never depends on the original file paths or DAW drag temp files still existing. Paths remain provenance, not required data dependencies.
- Also restore export mode, trim-silence setting, snap, selected range, horizontal zoom, lane height and scroll. Restore view positions after content and geometry are ready, clamping to valid bounds.
- Begin with empty undo/redo stacks. Restoring does not count as an edit.
- Restore before normal startup imports. MIDI files supplied on the command line or via the app's file-open event are then added using the existing import behaviour, rather than replacing the restored workspace.
- File ▸ New saves the resulting empty workspace under the agreed cadence; reopening must not resurrect cleared content. No new reset-session command is needed.

## Saving and recovery

- Store one versioned session in the app's per-user application-data directory, separate from export/temp folders and the repository. No user-selected path or MIDI export is involved.
- Use explicit, versioned structured serialization of the workspace, including exact fractions, MIDI messages, source bytes and metadata. Reuse the existing snapshot semantics where appropriate, but do not serialize UI objects or use executable object serialization.
- Record both the session schema version and the writing app version. Accept only the supported schema version; app-version changes alone do not invalidate an otherwise compatible session. Bump the schema version whenever a model or persisted-state change makes old data unsafe to load, including changes in field meaning or invariants. Document this requirement beside the version constant and in the contributor guidance. No migration framework is needed for this feature: unsupported schemas are preserved and skipped with a notice.
- Write a complete temporary file, then atomically replace the previous session only after successful serialization/writing. An interrupted save must not destroy the previous successful file.
- Mark persisted state dirty on relevant edits, including undo/redo and settings/view changes. Avoid whole-workspace scans or serialization in edit handlers.
- Periodic save eligibility: dirty state, at least **120 seconds since the last successful save** (or startup if none), and at least **15 seconds without user interaction**. If the two-minute point arrives during activity, defer until the inactivity condition is met; do not save forcibly on schedule. Continued activity may postpone checkpoints beyond two minutes.
- User interaction includes mouse/keyboard input, scrolling and active dialogs. Never checkpoint a live internal/external drag, trim or range gesture, even if the pointer is stationary. Background timers/repaints do not reset inactivity.
- Keep main-thread work limited to capturing a consistent, detached snapshot after the idle gate. Serialize and write on one background worker, with no worker access to live UI/model objects. Event/source data may be shared only where immutable. Do not launch overlapping saves.
- If editing resumes during a save, UI operation continues and those later edits remain dirty for the next checkpoint. A successful older snapshot must not clear newer changes. Use a change generation to track this explicitly.
- On an accepted close, save the latest state regardless of the inactivity/two-minute gates. Coordinate with any in-flight write so an older checkpoint cannot overwrite the final state. Do not finish shutdown before the final write succeeds or the user explicitly exits without saving.
- No partial restoration: decode and validate the whole session before applying it to the controller. Validate schema, required fields and ID references. Unsupported/corrupt/unreadable data produces a clear notice and an empty workspace; preserve the failed file for inspection rather than silently replacing it during startup.
- Treat saved data as untrusted input: validate types, enum values, numeric bounds, finite view values, exact-fraction denominators, MIDI payloads, unique IDs and model relationships before use. Put a recovery boundary around session reading, decoding, model construction and application (including settings/view restoration). If any stage fails, discard partial restored state and continue with a usable empty workspace and safe settings/view defaults. The session error must not terminate the app or prevent queued normal imports. Preserve the rejected file before subsequent saves can replace the active session path.
- A failed save leaves the last successful session intact and reports the failure without flooding the user with repeated periodic warnings. A close-time failure must be reported before exit, with an explicit choice to retry or exit without saving.
- If the previous run ended uncleanly, restore the last successful checkpoint and tell the user that newer changes may have been lost. Do not claim full crash recovery.
- Acquire single-instance ownership before restoring or enabling writes. Another launch must not read/modify the saved session or open a second workspace. Recover ownership after a crashed process without requiring manual lock-file deletion. Second-launch files are handed to the existing window for normal additive import.
- Headless tests must use temporary storage and never read or overwrite the user's real session. Persistence should be wired into the application startup/lifecycle rather than automatically enabled for every test-created `MainWindow`.

## Implementation scope

- A small session codec/storage module, with one application lifecycle owner for restore, dirty tracking, saving and any instance lock.
- Restore controller/model state and emit the existing refresh notifications. Rebuild transient render caches and drag state normally.
- Keep one codec and one save path shared by periodic and exit saves. Reuse existing controller restoration/refresh, workspace snapshot, additive import and settings paths where suitable; extend those paths narrowly when needed instead of duplicating mute/solo, range inclusion, export, import or UI-refresh logic. Keep session-specific validation and compatibility decisions centralized.
- Preserve current export/import semantics; this feature stores the workspace, not an exported approximation of it.
- No named sessions, project browser, recent-session menu or cloud sync. Include a local second-launch file handoff to the existing window. Queue incoming paths until startup restoration completes; do not import them into a partially restored workspace.
- New snapshot fields added by future features must also be considered by the session codec. A schema version allows incompatible saved sessions to be detected and reported.

## Verification

- Round-trip a workspace with mixed-source clips, duplicate/copied clips, offsets/trims, lyrics/meta/SysEx, names/colours, hidden mutes, solos, channel overrides, locked/unlocked ranges and a chosen tempo map. Check exact event data, fractions and ID relationships.
- Delete/move original input files before restore: the full workspace and exports still work.
- Compare exports before and after restoration in Whole, Preserve, Rebase and Separate modes.
- Test settings/view restoration and fresh undo history, File ▸ New, startup imports and a normal close/reopen.
- Test the internal switch: absent setting defaults to enabled; disabled skips session restoration and all session writes without deleting the saved file. Re-enabling on a subsequent launch restores the preserved session. Single-instance/file handoff remains functional in both states.
- Use a controlled clock to test two-minute eligibility, 15-second inactivity, continuous-activity deferral, dirty-generation tracking during background saves, close-time coordination, gesture deferral, interrupted writes, corrupt/truncated/unsupported sessions, storage failures and unclean-exit reporting.
- Test compatibility explicitly: changed app version with the supported schema still loads; older/newer unsupported schemas are rejected without crashing or losing the rejected file. Exercise malformed but parseable data (wrong types, invalid MIDI/fractions/enums, duplicate/dangling IDs and invalid view values), plus failures during model construction and settings/view application. Verify recovery leaves no partial workspace, permits normal imports and later saves, and preserves the rejected session.
- Exercise single-instance enforcement and recovery after process termination, including second-launch file handoff during and after startup restoration, a launch without files raising the window, paths with spaces/non-ASCII characters, and multiple supplied files. Confirm each handed-off request imports once and the secondary process exits only after acknowledgment; handoff failure must report an error rather than silently dropping files or opening another workspace. Ensure test instances cannot touch normal app storage.
- Studio: reopen an assembled workspace and export it into Cubase/Reason. Repeat with unsaved source/temp files gone, after New, and after a forced termination. Confirm exports, imports, drag/trim gestures and scrolling remain responsive while a large session is checkpointed.

## Build rules

- Implementation authorized. Do not build or publish the application unless requested.
- Work on `feature/session-persistence`. Do not push or open a PR until requested.
- If the existing code conflicts with the agreed plan, stop and ask before changing the design.

## Implementation notes

- `core/session.py` provides the explicit schema, validation and atomic storage; shared clip event lists are encoded once. `ui/session.py` owns restore and the single save worker, reusing workspace snapshots and controller refresh. `single_instance.py` owns the process lock and acknowledged file-open queue.
- The schema version, not the writing app version, gates loading. Rejected files are moved aside before a new save can replace them; a failed preservation blocks writes rather than losing the original.
- Validation checks effective clip source relationships. A track's original source ID and a locked range's exclusions can legitimately retain IDs removed from the current model; these inert historical IDs are preserved, matching existing model behaviour.
- Source/event/tempo data are immutable under existing snapshot semantics. Snapshot capture copies editable track/clip/range state on the UI thread; encoding and writing run on the worker.
- Tests exercise exact MIDI/export round trips (including the Cubase lyric fixture), settings/view, fresh undo, bad data and unsupported schemas, failed/overlapping writes, idle gates, process handoff and crash recovery, and the real application entry point with isolated storage. Manual checks are in `test-results-delete-me.md`.

Automated verification: **307 tests passed**, including 48 new session/instance checks. Existing Qt deprecation warnings only. Native studio checks remain pending.
