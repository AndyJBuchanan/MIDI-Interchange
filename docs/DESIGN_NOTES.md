# Design Notes and Development Log

Companion to [DESIGN_BRIEF.md](DESIGN_BRIEF.md), the original spec, kept verbatim. This file records how the brief was interpreted: decisions, deviations, known gaps and risks. Update it whenever direction changes.

## Status by milestone (updated 2026-11-09)

| Milestone | Status |
|---|---|
| M1 Functional vertical slice | **Done.** Every M1 bullet works in the GUI, and the brief's success criterion is covered by a headless GUI test (`tests/test_ui.py::test_full_workflow`). |
| M2 Interchange | **Partly done.** Drag-in accepts file URLs and raw MThd data; drag-out offers file URLs to temp files; individual-track export and source provenance are done. Native file promises and virtual files are **not** done (see Risks). |
| M3 Advanced ranges | **Mostly done.** Multiple named ranges, resize and move, concatenation, separate-range export, the boundary policy and whole-output trim are done. Per-track trim and per-range drag handles are **not** done. |
| M4 Polish and packaging | **Partly done.** Undo/redo and keyboard shortcuts are done. The macOS `.app` and DMG build and launch (arm64, Developer ID signed, hardened runtime). They're notarised and stapled, and Gatekeeper accepts them. The Windows build **has never been run**. Workspace persistence is **not** done. |

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
- **Tempo policy:** the first source with a tempo map becomes the workspace map. Later sources with a different map are reported in the status bar, never merged, and can be adopted from Timing ▸ Tempo Map.

### Export policy
Full details are in the module docstring of `core/export_smf.py` and in the README.
- Modes:
  - **Whole:** lossless; used when there are no ranges.
  - **Preserve:** ranges are merged and keep their positions.
  - **Rebase:** ranges are concatenated in list order.
  - **Separate:** one rebased file per range, named `"<stem> - <range>.mid"`.
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
- **Trim** applies to the whole output only. It moves every track by the same amount, so alignment is never broken.
- Output is format 1: an unnamed conductor track first, then the enabled tracks in panel order.
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
  - Double-click edits a range; Tab cycles through ranges; Backspace or Delete deletes one.
- Alt/Option-drag moves a clip (whole-clip offset).
- ⌘/Ctrl+wheel and pinch zoom around the pointer. Alt+wheel changes lane height.
- The track panel uses absolutely positioned headers kept in sync with the timeline's vertical scroll. Drag the grip to reorder; drops onto a name field are blocked.
- Creating the first range switches the export mode from Whole to Preserve.
- Undo takes up to 200 snapshots of the workspace structure; event lists are shared, not copied. Range and clip drags record one undo step per gesture.
- The window zooms to fit on the first import.
- macOS `FileOpen` events (Finder "Open With", dropping on the Dock icon) and paths on the command line are imported.

## Risks and known gaps

1. **Native drag-in (M2).** Qt can't receive macOS file promises (`NSFilePromiseReceiver`) or Windows virtual files (`CFSTR_FILEDESCRIPTOR`/`CFSTR_FILECONTENTS`). DAWs that drag clips this way will need PyObjC and pywin32/ctypes adapters. As a probe for now, when a drop has no usable MIDI the app lists the MIME formats it was offered.
2. **Native drag-out (M2).** Drag-out offers only file URLs, pointing at temp files in `$TMPDIR/MIDI Interchange Drag/<per-drag dir>`. Those files are pruned after 24 h at startup. A destination that needs promises or the data inline won't accept them.
3. **DAW interop is completely untested.** The README checklist is the place to record results. Don't claim compatibility until each target is ticked.
4. **Per-track auto-trim.** `Track.auto_trim` exists in the model but the exporter ignores it.
5. **Per-range drag handles.** Not built; the drag tile exports the current mode and selection.
6. **Workspace persistence.** Not built. QSettings stores only window and splitter state.
7. **Packaging.**
   - **macOS:** the DMG is Developer ID signed, notarised and stapled, using a git-ignored local config.
   - **Still missing:** an app icon, an Intel or universal2 build (arm64 only for now) and stapling the app inside the DMG.
   - **Size:** about 100 MB, because Qt plugins pull in QML/Quick, VirtualKeyboard and Pdf despite the spec's exclude list. Trimming those plugins could save a lot.
   - **Windows:** the build has never been run.
8. **Clip moves** apply to whole clips only; there's no splitting.

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

- `midi_interchange/core` must stay Qt-free and testable without a GUI.
- GUI tests run on Qt's offscreen platform (`tests/conftest.py`). `samples/` is generated by `tools/make_demo_midi.py` and committed, because the GUI tests load it.
- The developer is an experienced engineer. Prefer runnable code to prose, and make reasonable decisions without asking.
