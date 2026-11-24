# Plan: session sources dialog

Status: **built and manually tested (2026-11-19), merged in PR #23.** Branch: `feature/session-sources` from `release/0.5.0`.

A small **(i)** button in the top-left panel opens a dialog listing every source in the workspace, with the details Source Info shows for a single track. From it, one button solos exactly the tracks a source feeds.

## Why

Source details (file, path, format and version, import time, tempo, warnings such as what a project import left out) appear today only per track, under Source Info on a track's menu. With several imports in the workspace there's no single place to see them all, or to find which tracks a given source feeds.

## Behaviour

### The (i) button

- A small circle containing a bright white **i**, in the top-left panel's title band, beside the track count ("TRACKS 3/5"). It's a pseudo-button: clickable, with a pointer cursor, the tooltip **Sources in this session**, and an accessible name.
- It sits clear of the existing M and S clear-boxes at the band's right edge, at any panel width the app allows. To guarantee that with a three-digit count ("TRACKS  120/120"), the track panel's minimum width went from 170 to 215 px (the default is 240).
- Always shown. With nothing imported yet, clicking it opens the dialog with "Nothing imported yet."
- There is **no menu entry and no toolbar button**: the (i) is the only way in.

### The dialog

- **Modal.** Title: "Sources" with the count, for example "Sources — 3 in this session".
- A sources list on the left, in import order, and the details of the selected source on the right. The first source is selected on opening.
- Details are the ones Source Info shows now: name, path with **Show in Folder**, application, file summary (format, version, PPQ, size), imported time, display offset note, original tracks, tempo (and "This is the workspace tempo map"), and warnings.
- **New: Used by.** Each track the source's clips are on, with the number of clips: "Bass: 3 clips". A source with no clips shows "No clips (kept for its tempo map)". The workspace keeps a clipless source only while it's the tempo source.
- Two buttons:
  - **Solo all source tracks.** Solos exactly the tracks that have at least one clip from the selected source, unsoloing every other track (exclusive solo, as ⌥-click on S does for one track). Then it **closes the dialog**, so the result is visible on the timeline.
  - **Close.** Closes with no effect. Esc does the same.
- **Solo all source tracks** is disabled for a source that has no clips, since there are no tracks to solo.
- A track that holds clips from several sources is soloed whole. Clips can't be soloed individually, and a clip moved to another track is soloed with that track.

### The solo

- One undo step, like any other mute or solo action. Undo restores the previous solo set, and the mute states that solo overrode, through the existing rules (see [mute-solo.md](../0.2.2/mute-solo.md)).
- If the solo set is already exactly those tracks, nothing changes and no undo step is made. The dialog still closes.
- Unlocked ranges follow the new solo result, as they do for any solo change.
- A muted track that's part of the source's set is soloed and exports, as soloing a muted track does today.

### Source Info is unchanged

The per-track **Source Info** dialog stays exactly as it is, including what it shows and how it looks. They're different operations. The two share only the sources list and details widget underneath.

## Code

- **`ui/source_info.py`:** pull the sources list and details out of `SourceInfoDialog` into a reusable `SourcesPane(ws, sources, show_usage)`. `SourceInfoDialog` builds one from `track.source_ids()` with `show_usage` off, and keeps the attributes its existing tests use (`src_list`, `detail_host`, `detail_scroll`). A new `SourcesDialog(ws, ctl)` builds one from `ws.sources` with `show_usage` on, adds the **Used by** row, the two buttons, and the empty message.
- **`ui/controller.py`:** `solo_source_tracks(source_id)`, built on the same mute/solo path as `toggle_solo` (checkpoint once, set the `soloed` flags, then the shared `_ms_changed()`), so ranges, dimming and undo behave as for any solo.
- **`ui/track_panel.py`:** the (i) widget in the title band, laid out beside the count text and clear of M and S, emitting a `sourcesRequested` signal.
- **`ui/main_window.py`:** `show_sources()` opens the dialog (`exec()`), connected to that signal.
- **`ui/theme.py`:** only if there's no suitable bright white constant already; the (i) is brighter than `TEXT`.

## Tests (headless)

All use the shared `app` and `win` fixtures (see [CLAUDE.md](../../../CLAUDE.md)).

- **The (i):** it's in the title band, right of the count text and not overlapping M or S at narrow and wide panel widths; its tooltip is right; clicking it opens `SourcesDialog`.
- **Dialog content:** every source in import order; details match Source Info's for the same source; **Used by** lists the right tracks and counts, including a clip moved to another track; a clipless tempo source reads "No clips (kept for its tempo map)"; the empty workspace shows the message.
- **Solo:** it solos exactly the source's tracks and unsolos the rest; a track with clips from several sources is soloed; it's one undo step and undo restores solos and mutes; already-that-set makes no undo step; it closes the dialog (accepted); it's disabled for a source with no clips.
- **Close and Esc** change nothing and make no undo step.
- **Regression:** all existing `SourceInfoDialog` tests pass unchanged.
- The full suite is run four times, as for any new UI.

## Docs and checklist

- README: where Source Info is described, a line about the (i) button and the Sources dialog.
- TEST_CHECKLIST: a manual section for this branch (below).
- ROADMAP: remove the entry when built, and set this plan's status to built.

## Manual test

- Import two or three files (a MIDI file and a Cubase or Reason project). Click the (i): every source is listed with its details, and **Used by** shows the right tracks.
- Move a clip from one source onto another source's track: **Used by** follows.
- Select a source, press **Solo all source tracks**: the dialog closes and exactly its tracks are soloed. Undo brings the previous state back.
- Open the dialog with nothing imported, and with a clipless tempo source.
- Close and Esc leave everything alone.
- Resize the window and the panel: the (i) never overlaps the M and S boxes.
- Right-click a track ▸ Source Info still works as before.
