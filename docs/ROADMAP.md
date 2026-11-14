# Roadmap: outstanding work

All outstanding features and fixes, agreed or not, are listed here and only here. Each feature gets its own plan in [plans/](plans/) and its own branch when it is picked up. When something is finished, remove it from this list; its plan records how it was done.

Updated 2026-11-14.

## Agreed, not started

- **Investigate direct DAW project import** (2026-11-14; investigation agreed, implementation not yet scoped):
  - Goal: drag a saved project into MIDI Interchange and extract usable MIDI, tempo/time signatures, markers and lyrics through the ordinary import workflow, without first exporting MIDI from the DAW. Read source projects and any referenced media only; never write to or modify them.
  - Provide a MIDI view of the project's current arrangement, not a recovery view of everything stored in its files. Do not expose hidden material, unused pool contents, inactive alternate takes or abandoned edits, even if they can be found and labelled. Respect the arrangement's clip boundaries and active choices.
  - Target DAWs: **Cubase, Reason, Logic, Reaper, Bitwig, Ableton and FL Studio**. FL Studio support is subject to native-format feasibility investigation. **Studio One is deferred**; there is no current access to it for testing.
  - **DAWproject and the shared reader registry are provisionally implemented** (accepted 2026-11-14; [implementation and limitations](plans/dawproject-import.md)). This milestone validates the pluggable importer architecture alongside MIDI. Native-reader order after that remains to be scoped. Assess format feasibility independently; shipping one reader must not depend on completing all seven DAWs.
  - For each format, establish how its saved files/packages expose events and metadata, which versions can be read, and whether data is embedded or depends on referenced files. Distinguish saved MIDI from data that would require the DAW or an instrument to generate it.
  - Scope the musical mapping: track/clip names and positions, offsets, trims, loops/repeats, MIDI channels and controllers, tempo/time-signature changes, markers and lyrics. Establish how each format identifies the current arrangement and excludes hidden/inactive material.
  - **Mute state:** preserve both track and clip mute states on import. Muted arrangement material is included with its mute state, rather than treated as hidden/inactive material to omit. Track mute maps to the existing controls. Clip mute, its context-menu control, export gating, undo and session persistence are implemented with DAWproject; retain these semantics for subsequent readers. Do not flatten clip mute into track mute or discard muted clips.
  - Use small real projects with known content and matching DAW-exported MIDI as fixtures. Compare recovered events, timing and metadata programmatically, including missing references and unsupported project versions. Establish which marker/lyric data is actually saved and recoverable for each format.
  - Deliver a feasibility matrix and a separate implementation recommendation for each format: recoverable data, gaps, dependencies, estimated effort and evidence from fixtures. Partial support must report what was skipped; unreadable projects must fail cleanly without altering the workspace.
  - Design a common importer interface and registry/selection mechanism so MIDI and each supported project format can be selected and slotted into the same import pipeline. Separate format detection/reader selection from parsing. Define a shared import result and diagnostics contract that feeds the existing source/track/clip/tempo model; readers translate format-specific data into that contract. Adding a reader should not require format-specific branches throughout the UI or downstream logic.
  - Reuse placement, provenance, session persistence and export logic for every reader. Investigate and resolve shared model gaps explicitly, including clip mute, rather than creating separate per-format models or project workflows. Scope this common architecture alongside the first format investigations, using their findings to validate the contract.
- **Export/drag filename decoration:**
  - Names are mostly fixed today: a range name, a join of range names such as "Verse + Chorus", or `Range N`.
  - Offer decoration, at least bar numbers (range start–end) or other distinguishing details.

## Suggested, not agreed

- **More sophisticated tempo mapping** (2026-11-14):
  - Today the workspace uses one whole file's tempo map. Possible: take different files' maps for different sections, for example when files are laid End to End or verse and chorus come from different apps.
  - Related gaps in the current switch: adopting a file's map doesn't shift it to where the file was placed, and a file's map is lost when its last clip is removed, unless it's the current tempo source.
- **Scroll bar zoom:** drag the ends of the horizontal scroll bar to zoom, as other apps do (studio, 2026-11-10).

## Later, after more real-world use

- **Imported note tails beyond part ends** (deferred by agreement, 2026-11-14): keep current clip-edge cutting for now. Consider a tail-preservation policy later, including its interaction with user trims, loops and ranges. This does not block provisional DAWproject completion. See the [Ditty](DAWPROJECT_DITTY_FINDINGS.md) and [other-pair](DAWPROJECT_OTHER_PAIRS_FINDINGS.md) evidence; no Cubase-export repair is planned.

- **Intermittent cursor switching** (reported during clip-splitting verification, 2026-11-14): cursors occasionally stop switching. The user has observed this throughout the app's development, before clip splitting; the cause is unknown. Investigate later when a reproducible case is available. Clip-splitting manual checks otherwise passed.
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
  - Review the UI's keyboard shortcuts and drag modifiers as a whole. Shift on clip move/copy now bypasses snap on the source track and preserves original time on another/new track.


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
