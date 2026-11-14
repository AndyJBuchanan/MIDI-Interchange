# Roadmap: outstanding work

All outstanding features and fixes, agreed or not, are listed here and only here. Each feature gets its own plan in [plans/](plans/) and its own branch when it is picked up. When something is finished, remove it from this list; its plan records how it was done.

Updated 2026-11-14.

## Agreed, not started

- **Clip splitting:** [agreed plan](plans/clip-splitting.md) on `feature/clip-splitting`, based on `release/0.3.0`. Reuse duplication and edge trims with shared event data; keep both pieces in place and make the split one undo step. Cmd/Ctrl-click splits with scissors feedback; the pieces retain the existing non-destructive trim behaviour. Includes move/copy cursor feedback.
- **Export/drag filename decoration:**
  - Names are mostly fixed today: a range name, a join of range names such as "Verse + Chorus", or `Range N`.
  - Offer decoration, at least bar numbers (range start–end) or other distinguishing details.

## Suggested, not agreed

- **More sophisticated tempo mapping** (2026-11-14):
  - Today the workspace uses one whole file's tempo map. Possible: take different files' maps for different sections, for example when files are laid End to End or verse and chorus come from different apps.
  - Related gaps in the current switch: adopting a file's map doesn't shift it to where the file was placed, and a file's map is lost when its last clip is removed, unless it's the current tempo source.
- **Scroll bar zoom:** drag the ends of the horizontal scroll bar to zoom, as other apps do (studio, 2026-11-10).

## Later, after more real-world use

- **Reason Controller #254 automation lane** (known issue, deferred by agreement, 2026-11-13): channel-override export worked, but Reason added an unwanted automation lane. Zeroing release velocities did not remove it. Users can delete the lane; further investigation is deferred. See [the findings](INTEROP_FINDINGS.md#reason-unexpected-automation-lane-after-channel-override-2026-11-13).
- **Esc cancellation of incoming macOS drags** (deferred by agreement, 2026-11-12):
  - Finder → Finder cancels, but Finder → MIDI Interchange doesn't. Cubase → Finder and Cubase → MIDI Interchange both fail to cancel.
  - Investigate the Finder difference, and whether native handling can help. Don't assume the destination can cancel another app's drag.
  - Keep restoring the timeline when a drag leaves the window.
  - See [the recorded results](INTEROP_FINDINGS.md#esc-during-incoming-drags-studio-report-2026-11-12).
- **Clicking a greyed-out range checkbox:**
  - On an unlocked range, this does nothing for now (agreed 2026-11-12).
  - A possible change: the click locks the range and applies the change in one step. See [the mute/solo plan](plans/mute-solo.md).
- **Keys and modifiers:**
  - Review the UI's keyboard shortcuts and drag modifiers as a whole, including Shift on clip drags.
  - Shift currently keeps a clip's time and changes only its track. On range drags, Shift bypasses snap instead. This is kept for now.

## Future settings page

Not planned yet. These options exist, or are planned, in code but have no UI. They're collected here so a settings page can expose them later.

- **Show Markers** (QSettings `show_markers`, default on): the marker row in the timeline header. It also has a toolbar button. See [the timeline management plan](plans/timeline-management.md).
- **Session persistence:** internal enable/disable setting, default on. Gate session restoration and saving; expose a switch here later if needed. See [the plan](plans/session-persistence.md).
- **Notes that started before an edge** (`ExportOptions.partial_notes`, default on): they sound from a range or clip-trim edge, or are dropped.
- **What a drop replaces** (`Placement.compare_full_extent`, default visible edges): a dropped clip replaces one whose trimmed start and end match, or one whose full extent matches.

## Known gaps, not planned

The details of each are in [DESIGN_NOTES, Risks and known gaps](DESIGN_NOTES.md#risks-and-known-gaps).

- **Native drag formats** (risks 1 and 2): macOS file promises and Windows virtual files, for apps that drag that way.
- **Testing with other apps** (risk 3):
  - Synthesizer V hasn't been tried.
  - Drag-out to RapidComposer isn't confirmed.
  - Drag and drop with DAWs hasn't been tried on Windows.
- **Per-track auto-trim** (risk 4): it's in the model, but the export ignores it.
- **Per-range drag handles** (risk 5).
- **Packaging** (risk 7):
  - An Intel or universal Mac build.
  - Stapling the app inside the DMG.
  - Trimming the app size (about 100 MB).
  - Windows code signing.
