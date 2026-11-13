# Design Notes and Development Log

Companion to [DESIGN_BRIEF.md](DESIGN_BRIEF.md), the original spec, kept verbatim. This file records how the brief was interpreted: decisions, deviations, known gaps and risks. Update it whenever direction changes.

## Why MIDI Interchange

The brief's aim is to remove the friction of moving MIDI between applications. Hand testing on macOS keeps confirming that the friction is real: each app supports a different, often one-way, subset of MIDI drag-and-drop, and there is no shared MIDI clipboard. Detail is in [INTEROP_FINDINGS.md](INTEROP_FINDINGS.md).

- **Logic Pro** accepts dragged MIDI but doesn't drag MIDI out.
- **Cubase 16** drags only one MIDI part at a time from its Project window, however many are selected, to any destination: the desktop, MIDI Interchange or a VST plugin it hosts. Dragged parts also lose their position.
- **Reason 14** takes MIDI dragged from a VST plugin it hosts into its sequencer, but can't drag sequencer MIDI into that plugin. It also splits a multi-channel track into one track per channel on import.
- **RapidComposer 6** drags only a single clip or track out.
- **Clipboard:** Cubase, Reason and Logic keep copy and paste to themselves (a pointer, an encrypted blob, a text listing). No public MIDI clipboard format is in common use.

Plain MIDI files via file URLs are the one route that works almost everywhere. MIDI Interchange builds on that: it takes whatever each app can give (one part at a time, whole files), assembles and trims it in one place, and hands it on as a file any of them can accept.

## Status by milestone (updated 2026-11-10)

| Milestone | Status |
|---|---|
| M1 Functional vertical slice | **Done.** Every M1 bullet works in the GUI, and the brief's success criterion is covered by a headless GUI test (`tests/test_ui.py::test_full_workflow`). |
| M2 Interchange | **Partly done.** Drag-in accepts file URLs and raw MThd data; drag-out offers file URLs to temp files; individual-track export and source provenance are done. Native file promises and virtual files are **not** done (see Risks). Even so, hand tests on macOS (2026-11-09) show drag in and out working with Cubase 16, Scaler 3, Staccato.ai and Reason 14 (Reason drag-out confirmed 2026-11-10); drag-in with RapidComposer 6 (drag-out not yet confirmed); and drag-out to Logic Pro, which can't drag MIDI out. Cubase drags out only one clip at a time, even to the Finder (a Cubase limitation). Details in [INTEROP_FINDINGS.md](INTEROP_FINDINGS.md). Clipboard import was investigated and isn't viable for those DAWs. |
| M3 Advanced ranges | **Mostly done.** Multiple named ranges, resize and move, concatenation, separate-range export, per-range track selection, the boundary policy and whole-output trim are done. Per-track trim and per-range drag handles are **not** done. |
| M4 Polish and packaging | **Partly done.** Undo/redo and keyboard shortcuts are done. The macOS `.app` and DMG build and launch (arm64, Developer ID signed, hardened runtime). They're notarised and stapled, and Gatekeeper accepts them. On Windows, the one-folder build, zip and Inno Setup installer build and launch (x64, 2026-11-09), but aren't code-signed. Workspace persistence and single-instance file handoff are implemented; studio verification is pending. See [the plan](plans/session-persistence.md). |

User priority, given with the brief: the timeline is the primary UI element and must work early and well. It was built in M1, not deferred.

## Stack (as installed)

Python 3.12 venv, PySide6 6.12, mido 1.3.3, pytest 8, PyInstaller 6.x. The UI uses the Fusion style with a custom dark palette (`ui/theme.py`), so it looks the same on macOS and Windows.

## Deviations from the brief's suggested structure

- **Package name.** The code lives under a `midi_interchange/` package instead of top-level `core/`, `ui/` and `interchange/`. Generic top-level names collide easily, both on `sys.path` and inside PyInstaller bundles.
- **No `transforms.py`.** The non-destructive transforms (range extraction, clipping, state carry, rebasing, trim) all happen at export time in `core/export_smf.py`. The workspace itself is never transformed, so a separate module would have been an empty layer.
- **No `macos.py` or `windows.py` yet.** These are needed only for native file promises and virtual files (M2). The Qt-level code is in `interchange/drag_import.py` and `drag_export.py`.
- **`interchange/payload.py`.** The `Payload` type that transport adapters hand to the importer lives here, so the interchange layer doesn't import from the UI layer.
- **`ui/controller.py`.** A `QObject` that owns the workspace, undo stack and Qt signals. Widgets call the controller and never change the model directly.
- **Tests.** The suggested `test_ranges.py` and `test_metadata.py` were folded into `test_export.py`, `test_roundtrip.py` and `test_import.py`. `test_ui.py` was added.

## Key decisions

### Time
- Canonical time is an exact `fractions.Fraction` of a quarter note. Importing tick `t` at resolution `ppq` gives `Fraction(t, ppq)`, which is lossless at any resolution, including 1000 PPQ.
- Export PPQ is the LCM of the source PPQs and the denominators of every output time, so unsnapped range edges stay exact. If that would exceed 32767 (the 15-bit SMF limit), it falls back to the largest source PPQ (minimum 480) and rounds half up.
- BBT text uses `bar.beat.tick` with 480 ticks per quarter. That's for display and entry only, not storage.
- A time signature change in the middle of a bar starts a new bar.

### Events and integrity
- `Event(time, msg, seq)` wraps the **original mido message**, so the payload isn't rebuilt. That's how SysEx, unknown metas, sequencer-specific data, key signatures and so on survive.
- `seq` gives simultaneous events a stable order: source order on import, and sort key `(segment, priority, seq)` on export.
- Text metas are decoded as latin-1, which is byte-exact both ways, and re-decoded as UTF-8 for display only. An unchanged track name is written with its original bytes; a renamed track is written as UTF-8.
- A `note_on` with velocity 0 counts as a note-off. Notes are paired FIFO per (channel, pitch).
- Import rejects files with SMPTE time division, with a clear message. If strict parsing fails, it retries in mido's lenient mode (`clip=True`).

### Import policy
- Tempo and time-signature events move into the source's `TempoMap`. The first `track_name` at tick 0 becomes the editable track name. `end_of_track` sets the clip length.
- **Format 0** files are split into one track per channel (`"<name> · Ch N"`), plus a `"· Meta"` track for non-channel events. Channel numbers stay intact in the messages.
- A **conductor track** that contained only tempo and time-signature data is dropped once those events are lifted out. A track holding only other metas (lyrics, markers) becomes an **auxiliary** track: kept, exported, shown without notes.
- Each import adds a `Source` (frozen provenance: filename, path, app, PPQ, format, timestamp, original track names, **raw bytes**, warnings) and appends its tracks. Imports never replace material already in the workspace.
- **Placement** (`core/placement.py`, agreed 2026-11-09, modelled on Cubase/Reason): imports land at the drop's insertion cursor. Dropped on a track lane (or its header, for bar 1), an imported track joins that track **only when the names match** (case-insensitive, against the track's current or original name); if nothing matches that track, everything becomes new tracks at the cursor time. When the track under the cursor does match, the drop's other imported tracks also join existing tracks with matching names (the target wins ties; tracks made by the same drop are never candidates); the rest become new tracks. Added 2026-11-09 after hand testing, for multi-track round trips. A clip landing on an existing track replaces any clip there with exactly the same start and end (only clips that existed before the drop); partial overlaps are kept. Sources left with no clips are pruned (the tempo source is kept). Undo restores the replaced clips. Each existing track takes at most one imported track per file: a file that repeats a name (seen in Staccato.ai exports, 2026-11-10) pairs its copies in order with the existing same-named tracks, and extras become new tracks. **Song titles** (added 2026-11-10 after a studio round trip failed: Staccato renamed "Heavy EBM Drums - Industrial EBM Anthem" to "Heavy EBM Drums - Staccato Generation"): matching has two levels, paired in this order across the whole file: exact names, then names with a known song title removed from the end (" - <song>") on both sides. A source's song (`Source.song`, `names.song_title`) is its conductor track's name when some track ends in " - <it>", else an ending every named track shares (two or more tracks). A third, generic level (cut at the last " - ") was discussed and rejected as too loose: it would join "Lead - Verse" to "Lead - Chorus". Consequence: Reason's shortened names ("Monotone Chant - Industr Ch4") don't match. Export writes the song title as the conductor track's name when every exported clip's source shares one, so a title survives a round trip through MIDI Interchange (checked 2026-11-10: Cubase, Reason and Logic import such a file with no extra track; see INTEROP_FINDINGS). Dropped elsewhere, everything becomes new tracks. When several *files* are dropped the user picks End to End or All at Cursor. **End to End** (revised 2026-11-10 after hand testing): files laid in sequence on **one** new track named after the first file's track, ignoring names; multi-track files line up by track position; no matching to existing tracks (re-dropping a run isn't supported). The dialog names the resulting track(s). File ▸ Open always adds new tracks at bar 1. **One decision, one place** (2026-11-10, after the drop preview kept the old exact-name rule while the drop used song titles): `placement.plan_drop()` decides every drop and changes nothing; the drop preview, the several-files dialog and `place_imports()` (which only carries the plan out) all use it. Every name rule (comparing names, song titles, range labels, quoting names in messages, cleaning file names) is in `core/names.py`. A drop on a track that matches nothing says why in the preview and the status bar: the file's tracks and song title, and the track's song title.
- **Why:** DAW clip drags carry no position. Tested 2026-11-09: a Cubase part at bar 9 arrives at bar 1. And Cubase drags only one clip at a time, so parts are assembled by dropping them one by one where they belong.
- **Tempo policy:** the first source with a tempo map becomes the workspace map. Later sources with a different map are reported in the status bar, never merged, and can be adopted from Timing ▸ Tempo Map.

### Export policy
Full details are in the module docstring of `core/export_smf.py` and in the README.
- Modes:
  - **Whole:** lossless; used when there are no ranges.
  - **Preserve:** ranges are merged and keep their positions.
  - **Rebase:** ranges are concatenated in list order.
  - **Separate:** one rebased file per range. Dragged out, each is named after its range ("Verse.mid"); Save MIDI… names them `"<chosen name> - <range>.mid"` (see Export names below).
- **Boundaries:**
  - Ranges are half-open, `[s, e)`.
  - A note that started before `s` is clipped to `s`; the `partial_notes=False` option omits it instead.
  - A note that runs past `e` gets a note-off synthesized at `e`.
  - A note left unterminated in the source is closed at its clip's end.
  - Every exported note-on gets a note-off.
- **State carried into a range start**, in its original order (so bank-select→program and RPN/NRPN sequences stay valid):
  - the last program change
  - CCs, except mode messages 120–127
  - pitch bend and channel pressure
  - the key signature
  - The tempo and time signature in effect at `s` are written at the segment start.
  - SysEx and poly aftertouch are **not** carried.
- **Clip edge trims** (built 2026-11-11, [plans/clip-edge-trims.md](plans/clip-edge-trims.md)): a `Clip` keeps `events` and `length` as its full extent and has `trim_start`/`trim_end` (clip time); `start`/`end` are the visible edges and `set_start` positions a clip by its visible start. Exports apply trims with the range edge rules, from the same code (`clip_window` and `_extract_clips` in `core/export_smf.py`): each clip's window is the segment cut to its trims, `partial_notes` governs notes that started before a trimmed start, notes are released at a trimmed end, settings in force are written at the window start, and lyrics/text/markers outside the trims are dropped. A whole export writes untrimmed clips byte-exact and sends only trimmed clips through that code. Channel badges and Source Info use `visible_msgs`, the same code. Replace on drop compares visible edges (`Placement.compare_full_extent` compares full extents; not in the UI).
- **Trim** applies to the whole output only. It moves every track by the same amount, so alignment is never broken.
- Output is format 1: a conductor track first (named after the song when every exported clip comes from one song, else unnamed), then the exported tracks in panel order.
- Building an export never changes the workspace (tested).

### Packaging and distribution
- PyInstaller builds a one-folder `.app` bundle, version 0.1.0, bundle ID `com.midiinterchange.app`. It registers `.mid`, `.midi` and `.smf` as documents.
- **macOS release builds:**
  - Signed with Developer ID, with the hardened runtime and secure timestamps. PyInstaller signs every nested binary.
  - No entitlements: `scripts/entitlements.plist` is empty.
  - Distributed as a compressed DMG with an Applications shortcut.
  - Only the DMG is notarised. Its ticket covers the app inside, and it's stapled to both the DMG and `dist/` app.
- **Signing details stay out of git:**
  - The certificate identity and notary profile name are in `scripts/signing.local.env` (git-ignored); a template is checked in.
  - The Apple ID and app-specific password live only in the macOS keychain (a `notarytool` profile).
  - Which Apple account is used depends on the machine; it can be a personal developer team on a work Mac.
- Builds without the local file still work, but are ad-hoc signed.

### Timeline and UI
- One `QAbstractScrollArea` paints everything. Note geometry is cached per clip, and only notes that intersect the viewport are drawn (found by bisect). There are no per-note graphics items.
- **Header rows:** ruler (22 px), info row for tempo, time signature and markers (16 px), range strip (20 px).
- **Lanes:** each lane scales notes to its track's pitch span, with alpha set by velocity. Lyrics and text appear as ticks with labels.
- **Grid:** bar, beat and subdivision lines, with stride adjusted to the zoom level. Beat numbers appear when a beat is at least 46 px wide.
- **Range interaction:**
  - Drag on empty space to create a range (it needs at least 4 px of movement).
  - Drag an edge to resize; the edges swap if dragged past each other.
  - Drag the body in the strip to move it.
  - Shift bypasses snap. Snap choices are off, bar, beat, 1/8, 1/16, 1/32, 1/8T and 1/16T.
  - The view scrolls automatically near the edges.
  - Double-click a range (or a lane inside it) to edit it in the bottom panel; Tab cycles through ranges; Escape deselects; Backspace or Delete deletes one.
  - Each range has an include checkbox per lane at its inner left edge (hidden when the range is under ~23 px wide; the range's right-click menu lists the same choices). A quick second click on it flips it again rather than opening the range editor.
- Alt/Option-drag moves a clip in time and across tracks (below the last lane: a new track named after the clip's original track). Shift keeps its time. Alt+Ctrl / Option-⌘-drag copies. Empty tracks are removed when the gesture ends; one undo step per gesture.
- Clips carry their own `source_id`, so a track can hold clips from several sources. Export chooses PPQ from every clip's source; Source Info and the track header list all of them.
- Overlapping clips on a track are allowed: the overlap is tinted red and both clips' events are exported, merged.
- File ▸ New empties the workspace as one undoable step, keeping export settings.
- ⌘/Ctrl+wheel and pinch zoom around the pointer. Alt+wheel changes lane height, 3 px per wheel notch, with trackpad deltas added up (halved after studio testing, 2026-11-10).
- The track panel uses absolutely positioned headers kept in sync with the timeline's vertical scroll. Drag the grip to reorder; drops onto a name field are blocked.
- **Per-range track selection** (2026-11-10). `Range.excluded` holds the ids of tracks left out of that range.
  - A new range is seeded from the track toggles; afterwards it is independent of them (the range wins). Track toggles still drive whole export and seed new ranges.
  - A track created later starts with its own toggle in every range (imports); a clip moved onto a new track copies the range state of the track it came from.
  - Export: Rebase and Preserve give each track only the segments of ranges that include it (the conductor still covers every range); Separate writes each range's file with that range's tracks and skips a range with none; a track in no exported range is left out. Trim measures content only over the tracks each range includes. An explicit track export (track header drag) follows the same range rules.
  - Excluded lane sections are dimmed and hatched. A track switched off at track level is drawn grey except inside the ranges that include it, where it is drawn normally: a range shows what it exports (changed after studio testing, 2026-11-10).
  - Option/Alt-click on a track toggle also sets that track's checkbox in every range to match (one undo step).
- **Export names** (revised 2026-11-10 after studio testing). One file: the track's name if it holds one track, else the names of the ranges used joined with " + " (in export order, each once, skipping unnamed ranges and ranges that contribute no tracks), else "MIDI Interchange Export". Separate files dragged out are named by their range's label alone ("Verse.mid"; studio found "Verse + Chorus - Verse.mid" overkill); Save MIDI… appends the label to the chosen name ("name - Range.mid"). Clashing names get " (2)" etc. instead of overwriting.
- The default export mode is Rebase & concatenate (changed from Preserve on 2026-11-10, after hand testing). If Whole is selected, creating a range switches it to Rebase. With no ranges, export is always whole.
- Undo takes up to 200 snapshots of the workspace structure; event lists are shared, not copied. Range and clip drags record one undo step per gesture.
- The window zooms to fit on the first import.
- macOS `FileOpen` events (Finder "Open With", dropping on the Dock icon) and paths on the command line are imported.

## Risks and known gaps

1. **Native drag-in (M2).** Qt can't receive macOS file promises (`NSFilePromiseReceiver`) or Windows virtual files (`CFSTR_FILEDESCRIPTOR`/`CFSTR_FILECONTENTS`). DAWs that drag clips this way will need PyObjC and pywin32/ctypes adapters. As a probe for now, when a drop has no usable MIDI the app lists the MIME formats it was offered.
2. **Native drag-out (M2).** Drag-out offers only file URLs, pointing at temp files in `$TMPDIR/MIDI Interchange Drag/<per-drag dir>`. Those files are pruned after 24 h at startup. A destination that needs promises or the data inline won't accept them.
3. **DAW interop is only partly tested.** On macOS, plain file-URL drags work with Cubase 16, Reason 14, RapidComposer 6, Scaler 3, Staccato.ai and Logic Pro in the directions each app supports; no native promise support was needed. Cubase drags out only one clip at a time (its limitation, confirmed with the Finder); drag-out to Reason works (2026-11-10), drag-out to RapidComposer isn't confirmed. Synthesizer V hasn't been tested (Omnivocal is out of scope for drag tests: it takes its MIDI from Cubase, not by drag and drop), and nothing has been tested on Windows. See [INTEROP_FINDINGS.md](INTEROP_FINDINGS.md). Results go in the README checklist; don't claim compatibility for a target until it's ticked.
4. **Per-track auto-trim.** `Track.auto_trim` exists in the model but the exporter ignores it.
5. **Per-range drag handles.** Not built; the drag tile exports the current mode and selection.
6. **Workspace persistence.** Implemented as one self-contained, schema-versioned session, saved on exit and after the idle checkpoint gate. QSettings keeps the internal enable switch separately. Incompatible/damaged sessions are preserved and skipped; undo history starts fresh. Studio verification is pending ([plan](plans/session-persistence.md)).
7. **Packaging.**
   - **macOS:** the DMG is Developer ID signed, notarised and stapled, using a git-ignored local config.
   - **Still missing:** an Intel or universal2 build (arm64 only for now) and stapling the app inside the DMG.
   - **App icon (2026-11-11, first draft):** the master is `assets/icon/icon.png` (1024 px RGBA, transparent around the rounded square); `tools/make_icons.py` (needs Pillow and numpy, not in the requirements) makes the `.icns`, `.ico` and window PNGs, which are committed so the builds don't need Pillow. New artwork drawn on black goes through `--import`, which makes the outside transparent, crops and centres it and writes the master. Windows icons fill the canvas; the macOS one follows Apple's 824-in-1024 grid, and macOS 26 shows it at the normal size without a grey frame.
   - **Size:** about 100 MB, because Qt plugins pull in QML/Quick, VirtualKeyboard and Pdf despite the spec's exclude list. Trimming those plugins could save a lot.
   - **Windows:** builds and launches on Windows 11 x64. It's unsigned, so SmartScreen warns. The Inno Setup installer (`scripts/installer.iss`) registers the app under *Open with* for MIDI files but deliberately doesn't claim the default handler. Single-instance file handoff is now implemented; the packaged Explorer association still needs Windows studio verification. Drag-in/drag-out against DAWs isn't tested yet. User-facing shortcut hints are platform-aware (`⌘`/`⌥` on macOS, `Ctrl+`/`Alt+` elsewhere); keep any new ones that way.
8. **Clip moves** apply to whole clips only; there's no splitting.
9. **Mixed channels after clip moves.** Original channels remain the default, so a track can export several channels. A track-level export override is built on `feature/track-export-channel` (studio checks passed): choose Original channels or 1–16 through the header colour box. It maps all exported channel messages from every clip without rewriting source events. **Seen in practice (2026-11-10):** Reason 14 splits a multi-channel track into one track per channel on import (INTEROP_FINDINGS). See [the plan](plans/track-export-channel.md).
10. **Clipboard import.** Not built, and not planned: Cubase puts only an in-process pointer on the clipboard, Reason an encrypted blob, and Logic a text listing of regions with no notes. The only public convention found is `public.midi-audio` (Pro Tools, Sibelius), worth revisiting after a capture from either (INTEROP_FINDINGS.md).

## To do

All outstanding work, agreed or not, is listed in [ROADMAP.md](ROADMAP.md).

## Issues found and fixed during development

- An unterminated note was originally expected to end at the range end. The chosen policy closes it at the clip's `end_of_track`, and the test was corrected to match.
- Tempo is stored in µs per beat, so 140 BPM reads back as 140.00014. BPM comparisons now use a tolerance.
- `drag_import` used to import `Payload` from the UI layer. It moved to `interchange/payload.py`.
- Visual fixes from screenshot review:
  - lighter range tint (alpha 9, or 20 when selected)
  - beat numbers at close zoom
  - wider drag tile so its subtitle isn't cut off
  - marker labels shifted only when a tempo or time-signature label shares their position
- **Packaging:**
  - `hdiutil create -srcfolder` failed with "Resource busy" straight after a build, consistently once the app was signed; `-fs HFS+` didn't help. The fix was to build the DMG by copying into a blank image and converting it.
  - The first Developer ID signing failed with "timestamps differ by 297 seconds", most likely because the keychain access prompt was left open. Rerunning after allowing access fixed it.
  - The signed app launches under the hardened runtime with no entitlements. The first notarisation was accepted with no issues.

## Working conventions

- The repo is https://github.com/AndyJBuchanan/MIDI-Interchange, on a personal GitHub account. Each clone sets its own commit identity (GitHub no-reply address) and GitHub login (`gh`) in the repo's own config; never use the build machine's global or work settings. See DEVELOPMENT.md, "Configure each clone".

- `samples/assembly/` is generated by `tools/make_assembly_midi.py` (DAW-style parts, each with its own pitches) and committed. `tests/test_export_assembly.py` uses it to prove that clips assembled onto one track export as one track with every note, through the Save and Drag MIDI out paths, in every export mode.
- `samples/non-synthetic/` holds real exports from DAWs and other apps, added by hand for testing (not generated).
- `midi_interchange/core` must stay Qt-free and testable without a GUI.
- GUI tests run on Qt's offscreen platform (`tests/conftest.py`). `samples/` is generated by `tools/make_demo_midi.py` and committed, because the GUI tests load it.
- The developer is an experienced engineer. Prefer runnable code to prose, and make reasonable decisions without asking.
