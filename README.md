# MIDI Interchange

A palette for MIDI on its way between music apps. Drop in bits of MIDI from the apps you're working with, hold them and shape them in one place, then hand exactly what's needed to the next app.

Moving MIDI between apps is full of friction: each app drags MIDI in a different, often one-way, way. Cubase drags out one clip at a time with no position, Logic can't drag MIDI out at all, and there's no shared MIDI clipboard. MIDI Interchange sits in the middle. It takes whatever each app can give, lets you collect, trim and choose, and hands it on as plain MIDI files, the one format that works with almost every app.

It isn't a DAW or an arranger: there's no playback, no instruments and no note editing. Your source files are never changed.

## Download

The current release is **[v0.2.0-pre](https://github.com/AndyJBuchanan/MIDI-Interchange/releases/tag/v0.2.0-pre)** (2026-11-10), a pre-release. All releases are on the [Releases page](https://github.com/AndyJBuchanan/MIDI-Interchange/releases); you don't need to build anything.

| Your computer | Download |
|---|---|
| Mac with Apple silicon, macOS 15 or newer | `MIDI-Interchange-<ver>-macOS-arm64.dmg`: signed and notarised |
| Windows 10 / 11 (64-bit) | `MIDI-Interchange-<ver>-Windows-x64-Setup.exe` (installer), or the portable `.zip`. Not code-signed yet, so Windows may warn: **More info ▸ Run anyway** |

## What it's for

- **Collect from apps that give MIDI out a clip at a time.** Drag Cubase parts in one by one and drop each on its track at the bar it belongs to.
- **Round trips.** Send tracks to another app (Staccato.ai, for example), then drop what comes back on one of its tracks: every part lands back on its own track, even when the app has renamed the song.
- **Hand on exactly what the next app needs.** Mark ranges, choose which tracks each range sends, and drag the result straight into the next app, or into a folder.
- **Keep what matters intact.** Notes cut cleanly at range edges with nothing stuck, instrument and controller settings are carried into each range, and lyrics, markers and other MIDI data survive.

## Using it

Shortcuts are shown for macOS; on Windows use Ctrl for ⌘ and Alt for ⌥ (Option).

### Bringing MIDI in

- Drag MIDI from another app, or `.mid` files and folders, onto the window. You can also use File ▸ Open (⌘O), open a file with the app from the Finder or Explorer, or pass paths on the command line. Each import adds to the workspace.
- While you drag, a cursor and label show where it will land, and **what the label says is what happens**:
  - **Over a track lane:** it joins that track at the cursor's (snapped) time, but **only if the names match** (ignoring case and spacing; a renamed track still matches its original name). If nothing matches, it arrives as new track(s) at that time, and the label and status bar say why.
  - **Over a track header:** the same, at bar 1.
  - **Anywhere else:** new track(s), at the cursor time over the timeline or at bar 1 elsewhere.
- Dropped DAW clips carry no position of their own, so this is how you put them where they belong.
- Hold a dragged MIDI part near either edge of the timeline to scroll. The timeline grows as you drag right; dropping keeps only the length needed for the content, and leaving the window during the drag restores the previous view. Esc cancellation on macOS depends on the drag source and destination; it doesn't currently work for incoming Finder or Cubase drags in studio tests.
- **Several files at once:** you're asked: **End to End** (each file starts where the previous one ends, on **one** new track named after the first file's track; multi-track files line up by track position) or **All at Cursor** (each file at the cursor, with the usual name matching).
- **Round trips:** when a multi-track file matches the track you drop it on, its other tracks also join their same-named tracks, and the rest become new tracks.
  - A file that repeats a track name (Staccato.ai files can) pairs its copies in order with the existing same-named tracks.
  - A dropped clip with exactly the same start and end as one already on the track **replaces** it (a trimmed clip counts by its visible edges); partial overlaps are kept and tinted.
  - **Song titles:** Staccato.ai names tracks "part - song" and changes the song between generations. If no name matches exactly, names are compared again without a known song title, so "Drums - Staccato Generation" joins "Drums - Industrial EBM Anthem"; the status bar says when it did. A song title is known only from the file itself (its tempo track's name, or an ending all its tracks share), so DAW clips such as "Lead - Verse" and "Lead - Chorus" never match.
- The first file with a tempo map sets the workspace tempo. Timing ▸ Tempo Map lets you adopt another file's map.

### Reorganising what you hold

| Action | How |
|---|---|
| Move a clip | ⌥-drag it in time and onto another track; drag below the last track for a new one. Hold Shift to keep its time (track change only). A track left empty is removed (Undo restores it) |
| Trim a clip | ⌥-drag its left or right edge (the cursor turns to ↔). The edge snaps like a clip move (Shift bypasses the snap) and can't go past where the clip's MIDI originally started or ended. Notes and settings outside the trims are left out of exports and drag-out; right-click ▸ **Restore Full Clip** puts both edges back. An edge placed off the grid with Shift stays there until the clip is moved. A plain move snaps the clip's visible start to the grid; Shift keeps its time. Duplicate places the copy straight after the visible end, so the two abut. A plain drag on a clip edge still makes or resizes a range. A clip too narrow to hold both edges can only be moved: zoom in to trim it |
| Copy a clip | ⌥⌘-drag it, or right-click ▸ Duplicate Clip (placed straight after it) |
| Clip tools | Right-click a clip: Duplicate, Butt Against Previous Clip, Restore Full Clip (on a trimmed clip), Move Clip to Track (or New Track), Delete Clip |
| Overlaps | Clips may overlap on a track; the overlap is tinted red and both clips' notes are exported, merged |
| Tracks | Click the name to rename, drag ⋮⋮ to reorder, ✕ to remove. Right-click a header (or a clip ▸ Track) for Enable/Disable, Rename, Solo for Export / Unsolo, Move Up/Down, Merge Into (another track), Save This Track…, Source Info… and Remove Track |
| Start again | File ▸ New (⌘N, also on the toolbar) clears the workspace; Undo brings it back. Export settings are kept |
| Undo / redo | ⌘Z / ⇧⌘Z cover everything |
| About | The About button at the right end of the toolbar shows the version and the project link |

### Choosing what to hand on

| Action | How |
|---|---|
| Choose tracks | Each track's checkbox includes it in the export (Edit ▸ Enable/Disable All Tracks for all of them) |
| Create a range | Drag across empty timeline space (in the ruler or in the lanes) |
| Resize / move a range | Drag an edge (in any row) / drag the body in the range strip |
| Snap | Snap list on the toolbar, or Timing ▸ Snap: off, bar, beat (the default), 1/8, 1/16, 1/32, 1/8T, 1/16T. Hold Shift while dragging to bypass it |
| Name a range, exact positions | Pick it in the Range list in the bottom panel (or double-click it, or right-click ▸ Edit Range…), then type a name, and `bar.beat.tick` (480 ticks per quarter) into Start/End |
| Delete / cycle ranges | Backspace or Delete (or the panel's Delete button, Edit ▸ Delete Range) / Tab. Escape deselects. Clear All Ranges is on the toolbar and the Edit menu |
| Tracks per range | Click the range's checkbox in a track's lane (at the range's inner left edge) to leave that track out of the range; the excluded section is hatched. Right-click the range for the same list, plus Include All, Exclude All and Reset to Track Toggles. A new range starts with the track checkboxes; after that its own checkboxes win. A track switched off is still drawn in colour inside ranges that include it. ⌥-click a track's checkbox to set it in every range too |

### Exporting

- Pick a mode in the bottom panel's Export list:
  - **Whole workspace**
  - **Ranges · keep positions**
  - **Ranges · rebase & concatenate** (the default): the ranges back to back from bar 1
  - **Ranges · separate files**: one file per range
- Tick **Trim leading/trailing silence** to trim the output as a whole; tracks stay aligned.
- Then **Save MIDI…** (⌘S), or drag the **Drag MIDI out** tile straight into another app or a folder. The tile and the line beside the Trim box say how many tracks and files will go.
- **File names:** a one-track export is named after the track; otherwise after the range names ("Verse + Chorus"). Separate files dragged out are named after their range ("Verse.mid"; a repeat gets " (2)"); Save MIDI… adds the range name to the name you choose.
- An export whose clips all come from one song keeps the song's title in its tempo track, so it can be matched again when it comes back.

### Viewing

- Zoom: ⌘ + wheel, trackpad pinch, ⌘= / ⌘- / ⌘0 (fit).
- Lane height: ⌥ + wheel (a small step per notch), or ⌘⇧= / ⌘⇧- (View ▸ Taller/Shorter Lanes).
- Each lane shows its notes, lyrics and text; the rows above show tempo, time signature, markers and the ranges. The status bar shows the position under the pointer.

## Works with

Tested by hand on macOS (2026-11-09 and 2026-11-10). Drag and drop works as far as each app allows. On Windows the app builds and its tests pass, but drag and drop with DAWs hasn't been tried yet. Details, the clipboard investigation and open issues are in [docs/INTEROP_FINDINGS.md](docs/INTEROP_FINDINGS.md).

Key: ✓ works · ◐ works within limits (see notes) · — the app doesn't support it · ☐ not tested or not yet confirmed

"Drag-in" means dragging from the app into MIDI Interchange; "drag-out" means dragging from MIDI Interchange into the app.

| App | macOS drag-in | macOS drag-out | Windows drag-in | Windows drag-out | Notes |
|---|---|---|---|---|---|
| Cubase 16 | ◐ | ✓ | ☐ | ☐ | Cubase drags out one clip at a time (a Cubase limitation; also true when dragging to the Finder). A drag into Cubase doesn't set its tempo (possibly normal for a drag into an open project); opening the saved file does |
| Reason 14 | ✓ | ◐ | ☐ | ☐ | Drag-out works, whole and by range, but Reason splits a track that mixes MIDI channels into one track per channel, and a drag doesn't set its tempo |
| RapidComposer 6 | ◐ | ☐ | ☐ | ☐ | Single clip/track only |
| Scaler 3 | ◐ | ◐ | ☐ | ☐ | Where it applies, e.g. the main page |
| Staccato.ai | ✓ | ✓ | ☐ | ☐ | Round trips match tracks even when Staccato renames the song |
| Logic Pro | — | ✓ | ☐ | ☐ | Logic doesn't drag MIDI out. A dragged file imports cleanly, but Logic doesn't take its tempo; a new project made from the file does |
| Synthesizer V Studio 2 | ☐ | ☐ | ☐ | ☐ | |
| Finder / Explorer | ✓ | ✓ | ☐ | ☐ | Files and folders in; files out (used throughout testing) |

Yamaha Omnivocal isn't listed: no MIDI is dragged to or from it. It takes its MIDI from Cubase.

**Clipboard:** Cubase, Reason and Logic Pro don't put usable MIDI on the system clipboard, so copy and paste between them and MIDI Interchange isn't possible. Pro Tools and Sibelius use `public.midi-audio`, a possible future route; see the findings page.

For each app check: does the drop import at all (if not, note the formats listed in the error); are track names, channels, lyrics and tempo intact; does a rebased range land at the drop position with the correct length; and are there no stuck notes at range edges.

## Known limitations

- **Drag and drop depends on the other app.** File URLs and any data starting with `MThd` are handled. Qt can't receive **macOS file promises** or **Windows virtual files**; no app tested so far needed them. If a drop carries no usable MIDI, the app lists the formats it was offered, which helps a lot in a bug report. Drag-out offers temp files (in `$TMPDIR/MIDI Interchange Drag`, pruned after 24 h).
- **Mixed channels:** a clip moved onto another track keeps its own MIDI channel(s), so a track can end up mixing channels (its header lists them all). MIDI Interchange exports it as one track, but some importers split it: **Reason 14** turns it into one track per channel. To get one track there, assemble clips that share a channel. A per-track export channel is planned.
- Clips can be trimmed at either edge but not split.
- The workspace isn't kept between sessions yet (planned); export what you need before quitting.
- SMPTE-division files are rejected with a clear message.
- On Windows, opening several files at once from Explorer opens several windows; drag them onto one window instead.

The plan for what comes next is in the "To do" section of [docs/DESIGN_NOTES.md](docs/DESIGN_NOTES.md).

## Run from source (macOS / Windows)

Source: https://github.com/AndyJBuchanan/MIDI-Interchange

```bash
git clone https://github.com/AndyJBuchanan/MIDI-Interchange.git && cd MIDI-Interchange
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt   # Windows: .venv\Scripts\pip
.venv/bin/python tools/make_demo_midi.py          # optional: writes demo files to samples/
.venv/bin/python main.py                          # or: main.py samples/*.mid
```

Run the tests with `.venv/bin/python -m pytest -q`. The GUI tests use Qt's offscreen platform.
For Windows commands, a new machine, VS Code setup or troubleshooting, see [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Documentation

- [docs/DESIGN_BRIEF.md](docs/DESIGN_BRIEF.md) is the original project spec, kept verbatim.
- [docs/DESIGN_NOTES.md](docs/DESIGN_NOTES.md) covers how the spec was interpreted: status, decisions, risks, known gaps and the to-do list.
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) explains how to set up on a new machine (macOS or Windows), run, test, debug and build, including in VS Code. **Before committing from a new clone**, read its section on setting each clone's commit identity and GitHub login.
- [docs/INTEROP_FINDINGS.md](docs/INTEROP_FINDINGS.md) has the app-by-app drag test results, the clipboard investigation and open interop issues.
- [docs/TEST_CHECKLIST.md](docs/TEST_CHECKLIST.md) is the manual test checklist, one section per feature plus a regression pass.
- [docs/RELEASING.md](docs/RELEASING.md) explains the version number, tag naming, and building and publishing a release. Release notes are in [docs/releases/](docs/releases/).

## Architecture

```
main.py                         entry point (also handles macOS FileOpen events)
midi_interchange/core/          pure Python, no Qt dependency
  timing.py     Fraction-of-quarter canonical time, TempoMap, BBT, snapping
  events.py     Event(time, mido msg, seq), FIFO note pairing
  document.py   Workspace → Source → Track → Clip → Event, undo snapshots
  ranges.py     half-open [start, end) ranges, merging
  import_smf.py SMF → canonical model
  placement.py  where a drop lands: plan_drop() decides, place_imports() carries it out
  names.py      every naming rule: name matching, song titles, range labels, file names
  export_smf.py canonical model → SMF (whole / preserve / rebase / separate, trim)
midi_interchange/interchange/   transport boundary (drop payload extraction, temp files for drag-out)
midi_interchange/ui/            PySide6: controller (undo + signals), timeline, track panel, export panel
```

The main design decisions:

- **Time** is an exact `Fraction` of quarter notes, so mixing 96/480/960/1000 PPQ sources loses nothing. On export the PPQ is the LCM of the source PPQs and every output time's denominator. If that would exceed the 15-bit SMF limit, it falls back to the largest source PPQ (minimum 480) and rounds.
- **Events** keep the original mido message object. SysEx, unknown metas, sequencer-specific data and text bytes (decoded as latin-1, so the round trip is byte-exact) survive untouched. Text is re-decoded as UTF-8 for display only.
- **Import policy**: tempo and time-signature events move into the source's `TempoMap`. The first `track_name` at tick 0 becomes the editable track name; a pure conductor track's name is kept as the source's song title when the track names end in it. `end_of_track` sets the clip length. Format 0 files are split per channel, plus a `· Meta` track for non-channel events. A pure conductor track is dropped, and a track with only meta events becomes an *auxiliary* track.
- **Tempo policy**: the first source that has a tempo map becomes authoritative. Later conflicting maps stay on their source, are reported, and can be adopted from the menu. They are never merged.
- **Track names**: an unchanged name is written back with its original bytes; an edited name is written as UTF-8. The conductor track is named after the song when every exported clip comes from one song, otherwise it's unnamed.

### Export boundary policy (`core/export_smf.py`)

- Notes are paired FIFO per (channel, pitch). A note that sounds inside `[s, e)` is exported. If it started before `s` it is clipped to start at `s` (or omitted when `partial_notes=False`). If it runs past `e` it gets a note-off synthesized at `e`. **Every note-on gets a note-off.**
- At `s`, the exporter re-emits the last program change, CCs (except 120–127), pitch bend, channel pressure and key signature that came before `s`, **in their original order**. That keeps bank-select→program and RPN/NRPN sequences valid. SysEx and poly aftertouch are not carried.
- The tempo and time signature in effect at `s` are written at the start of each segment.
- Lyrics, text, markers and SysEx are included when their time falls in `[s, e)`.
- **Preserve** mode merges overlapping or adjacent ranges and keeps positions. **Rebase** concatenates ranges in list order; it's the default. With no ranges, the whole workspace is exported. **Separate** writes one rebased file per range. End-of-track is placed at the range end so loop lengths survive.
- **Tracks per range:** range exports use each range's own track checkboxes, not the track toggles. A track excluded from a range is silent there (the range still takes its time); a track no exported range includes is left out of the file. Whole export uses the track toggles.
- **File names:** a one-track export is named after the track; otherwise after the range names ("Verse + Chorus"). Separate files dragged out are named by their range alone ("Verse.mid", a repeat gets " (2)"); Save MIDI… adds the range name to the name you choose.
- **Clip trims** use the same edge rules as ranges: a note that started before a trimmed start sounds from the edge, a note running past a trimmed end is released at it, and the program, controllers and pitch bend in force are written at the start. A whole export writes untrimmed clips exactly as imported.
- **Trim** applies to the whole output only. It cuts to the first and last note or lyric and moves every track by the same amount, so alignment is never broken.

## Packaging

```bash
scripts/build_macos.sh            # → dist/MIDI Interchange.app + dist/MIDI-Interchange-<ver>-macOS-<arch>.dmg
```
```bash
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1   # → dist\MIDI-Interchange-<ver>-Windows-x64-Setup.exe (installer) + portable .zip
```

Both scripts use PyInstaller with `midi_interchange.spec`. The app icon files in `assets/icon/` are made from the master artwork `assets/icon/icon.png` (1024 px, transparent corners) by `tools/make_icons.py`; rerun it after changing the master.

- **macOS:** when the git-ignored `scripts/signing.local.env` is set up, the app and DMG are signed with Developer ID and the hardened runtime, notarised by Apple and stapled. Verified for v0.2.0-pre (2026-11-10): Gatekeeper reports "Notarized Developer ID". Without that file the build falls back to ad-hoc signing. Setup is in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md#macos-signing-and-notarisation).
- **Windows:** builds a one-folder app, a portable zip and an installer (Inno Setup: per-user install with no admin prompt, Start-menu shortcut, uninstaller, *Open with* for `.mid`). Verified on 2026-11-09 (Windows 11 x64, Python 3.12.10): the app runs from the zip and after a silent install, which also uninstalls cleanly. For v0.2.0-pre (2026-11-10) the full test suite passes on Windows too. It is **not code-signed** yet, so SmartScreen warns on download. See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md#windows-build).
