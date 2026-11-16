# Roadmap: outstanding work

All outstanding features and fixes, agreed or not, are listed here and only here. Each feature gets its own plan in [plans/](plans/) and its own branch when it is picked up. When something is finished, remove it from this list; its plan records how it was done.

Updated 2026-11-16.

## Agreed, not started


- **More direct DAW project readers** (2026-11-16): the investigation and first readers are done: DAWproject, Cubase 15/16 and Reason 13/14 are implemented and checked against each DAW's own MIDI export (see the [DAWproject](plans/dawproject-import.md), [Cubase](plans/cubase-import.md) and [Reason](plans/reason-import.md) plans, TEST_CHECKLIST sections 8n and 8o, and the README). What's left, in the user's order of priority:
  - **Cubase before 15** (agreed, later): fixtures are in `samples/` (a Cubase 13 file, `argontest003`); older versions are rejected cleanly for now.
  - **Logic** (secondary) and **Reaper, Bitwig, Ableton, FL Studio** (low priority; the user uses only Reason and Cubase). Feasibility and order are in the [desk research](plans/daw-desk-research.md). **Studio One is deferred**; there is no access to it for testing.
  - Each reader keeps the shared rules: read only, never modify the project; report what was skipped; fail cleanly on unreadable files; preserve track and clip mute states.

## Suggested, not agreed

- **Export/drag filename decoration** (speculative, 2026-11-16: not sure it's needed):
  - Names are mostly fixed today: a range name, a join of range names such as "Verse + Chorus", or `Range N`.
  - Possible: decoration, at least bar numbers (range start–end) or other distinguishing details.

- **More sophisticated tempo mapping** (2026-11-14):
  - Today the workspace uses one whole file's tempo map. Possible: take different files' maps for different sections, for example when files are laid End to End or verse and chorus come from different apps.
  - Related gaps in the current switch: adopting a file's map doesn't shift it to where the file was placed, and a file's map is lost when its last clip is removed, unless it's the current tempo source.
- **Scroll bar zoom:** drag the ends of the horizontal scroll bar to zoom, as other apps do (studio, 2026-11-10).
- **Simplify controller data on export** (2026-11-16, maybe): an export option that drops controller events repeating the previous value and thins the rest to the fewest points staying within one step of the original. DAW exports write curves as a dense stream (Reason's: a value every 1/32 beat), and re-importing it into Reason gives a staircase of points; most DAWs draw straight lines between imported points, so a thinned stream comes back as a few clean points. Off by default: the app aims to be a transparent transport, and this deliberately changes the data; an opt-in fix for a common annoyance.
- **Show controller data on a track** (2026-11-16, maybe): draw a clip's CC data (mod wheel, sustain, pitch bend, expression...) as a line over or under its notes, so imported curves and resets can be seen. Which controller to show could be chosen per track, for example from the track's colour box menu, alongside the export channel.

- **Mirror mode: watch one file** (2026-11-16, under consideration, **not agreed**): a separate mode of operation, entered by an explicit "Open & Mirror MIDI/Project File" command, not a toggle on a normal open. One MIDI or project file is locked to the timeline at bar 1 and the app watches it; whenever the file changes on disk it is re-imported automatically. The aim is to mirror a Cubase (or Reason) project while still working in it, so whatever was last saved is ready to drag out.
  - **Read-only view:** no edits and no drops while mirroring. Allowed: range selections, track locks and probably track mute/solo, carried across reimports (the readers already have `preserve_track_state`; ranges would be kept by time).
  - **Leaving the mode:** the user must unmirror to resume normal operation. It should look and feel different (clear banner, edit tools unavailable).
  - **Only saved files count:** a project changes on disk only when the user saves, which is acceptable.
  - **Open questions:** how to detect a finished save (DAWs write in stages; wait until size and modification time settle, and keep the last good import if a read fails); watch mechanism (`QFileSystemWatcher` loses its watch when a file is replaced by rename; polling the modification time is the simple alternative; undecided); how Cubase and Reason actually write on save (check, don't assume).

## Later, after more real-world use

- **Cubase chord track as chord names** (agreed 2026-11-15, after the Cubase reader): show a Cubase project's chord-track chords as names on a new proxy marker track, rather than rendering chords as notes. Needs investigation of how chord events are stored (`MChordTrackEvent`, `MChordEvent`, `ChordData`) and a design for a marker-style track. See [the Cubase plan](plans/cubase-import.md#decisions-2026-11-15).

- **Cubase expression-map articulations as text** (noted 2026-11-16, maybe): Cubase's own MIDI export writes each articulation of an expression map as a text event on its track (BBCSO: "Legato", "Spiccato", "StacSs"...). The native reader could import them the same way, so articulations survive to other DAWs. Needs finding where they're stored in the project. See [the Cubase plan](plans/cubase-import.md).
- **Reason pattern devices as notes** (agreed 2026-11-15, maybe): render unconverted pattern clips (Redrum, Matrix and similar) from the pattern data stored in the rack device, as Cubase decision 8 does for Pattern Editor parts. Reason's own MIDI export leaves them out, so the first reader reports them as skipped. See [the Reason plan](plans/reason-import.md).

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
