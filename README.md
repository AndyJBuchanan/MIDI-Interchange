# MIDI Interchange

A small desktop workspace for collecting, trimming and re-exporting MIDI between applications.
It is not a DAW: there's no playback, no instruments and no note editing.

Status: **Milestone 1** (functional vertical slice), plus a few cheap pieces of later milestones: multiple ranges, rebase/concatenate/separate export, whole-output trim, undo/redo, file-URL drag-out and Alt-drag clip moves.

Documentation:

- [docs/DESIGN_BRIEF.md](docs/DESIGN_BRIEF.md) is the original project spec, kept verbatim.
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) explains how to set up on a new machine (macOS or Windows), run, test, debug and build, including in VS Code (extensions, launch configurations and tasks in `.vscode/`).
- [docs/DESIGN_NOTES.md](docs/DESIGN_NOTES.md) covers how the spec was interpreted: status for each milestone, deviations, decisions, risks and known gaps.

## Run (macOS / Windows)

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt   # Windows: .venv\Scripts\pip
.venv/bin/python tools/make_demo_midi.py          # optional: writes demo files to samples/
.venv/bin/python main.py                          # or: main.py samples/*.mid
```

Run the tests with `.venv/bin/python -m pytest -q`. The GUI tests use Qt's offscreen platform.
For Windows commands, a new machine, VS Code setup or troubleshooting, see [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Using it

| Action | How |
|---|---|
| Import | Drop `.mid` files or folders onto the window, use File ▸ Open (⌘O), or pass paths on the command line. Each import adds to the workspace. |
| Create a range | Drag across empty timeline space (in the ruler or in the lanes) |
| Resize / move a range | Drag an edge (in any row) / drag the body in the range strip |
| Bypass snap | Hold Shift while dragging |
| Precise range | Type `bar.beat.tick` (480 ticks per quarter) into Start/End in the bottom panel |
| Delete range / cycle ranges | Backspace or Delete / Tab |
| Move a clip | Alt/Option-drag it |
| Zoom | ⌘/Ctrl + wheel, trackpad pinch, ⌘= / ⌘- / ⌘0 (fit) |
| Lane height | Alt + wheel, ⌘⇧= / ⌘⇧- |
| Track ops | Checkbox = include in export, click the name to rename, drag ⋮⋮ to reorder, ✕ to remove, right-click for Solo, Save This Track and Source Info |
| Export | Save MIDI… (⌘S), or drag the **Drag MIDI out** tile into a DAW or Finder/Explorer |
| Tempo map | Timing ▸ Tempo Map lets you adopt any imported source's map |

## Architecture

```
main.py                         entry point (also handles macOS FileOpen events)
midi_interchange/core/          pure Python, no Qt dependency
  timing.py     Fraction-of-quarter canonical time, TempoMap, BBT, snapping
  events.py     Event(time, mido msg, seq), FIFO note pairing
  document.py   Workspace → Source → Track → Clip → Event, undo snapshots
  ranges.py     half-open [start, end) ranges, merging
  import_smf.py SMF → canonical model
  export_smf.py canonical model → SMF (whole / preserve / rebase / separate, trim)
midi_interchange/interchange/   transport boundary (drop payload extraction, temp files for drag-out)
midi_interchange/ui/            PySide6: controller (undo + signals), timeline, track panel, export panel
```

The main design decisions:

- **Time** is an exact `Fraction` of quarter notes, so mixing 96/480/960/1000 PPQ sources loses nothing. On export the PPQ is the LCM of the source PPQs and every output time's denominator. If that would exceed the 15-bit SMF limit, it falls back to the largest source PPQ (minimum 480) and rounds.
- **Events** keep the original mido message object. SysEx, unknown metas, sequencer-specific data and text bytes (decoded as latin-1, so the round trip is byte-exact) survive untouched. Text is re-decoded as UTF-8 for display only.
- **Import policy**: tempo and time-signature events move into the source's `TempoMap`. The first `track_name` at tick 0 becomes the editable track name. `end_of_track` sets the clip length. Format 0 files are split per channel, plus a `· Meta` track for non-channel events. A pure conductor track is dropped, and a track with only meta events becomes an *auxiliary* track.
- **Tempo policy**: the first source that has a tempo map becomes authoritative. Later conflicting maps stay on their source, are reported, and can be adopted from the menu. They are never merged.
- **Track names**: an unchanged name is written back with its original bytes; an edited name is written as UTF-8.

### Export boundary policy (`core/export_smf.py`)

- Notes are paired FIFO per (channel, pitch). A note that sounds inside `[s, e)` is exported. If it started before `s` it is clipped to start at `s` (or omitted when `partial_notes=False`). If it runs past `e` it gets a note-off synthesized at `e`. **Every note-on gets a note-off.**
- At `s`, the exporter re-emits the last program change, CCs (except 120–127), pitch bend, channel pressure and key signature that came before `s`, **in their original order**. That keeps bank-select→program and RPN/NRPN sequences valid. SysEx and poly aftertouch are not carried.
- The tempo and time signature in effect at `s` are written at the start of each segment.
- Lyrics, text, markers and SysEx are included when their time falls in `[s, e)`.
- **Preserve** mode merges overlapping or adjacent ranges and keeps positions. **Rebase** concatenates ranges in list order. **Separate** writes one rebased file per range. End-of-track is placed at the range end so loop lengths survive.
- **Trim** applies to the whole output only. It cuts to the first and last note or lyric and moves every track by the same amount, so alignment is never broken.

## Known limitations and risks (for Milestone 2)

- **Drag-in from DAWs**: file URLs and any MIME format whose bytes start with `MThd` are handled. Qt cannot receive **macOS file promises** (`NSFilePromiseReceiver`) or **Windows virtual files** (`CFSTR_FILEDESCRIPTOR`/`FILECONTENTS`). These need native adapters (PyObjC on macOS, `pywin32`/ctypes on Windows). If a drop carries no usable MIDI, the app lists the formats it was offered, which is a useful probe for each app.
- **Drag-out** currently offers file URLs to temp files. They stay in `$TMPDIR/MIDI Interchange Drag` and are pruned after 24 h. That covers Finder/Explorer and DAWs that accept file drops. Native file promises are a Milestone 2 item.
- SMPTE-division files are rejected with a clear message.
- Clip moves are whole-clip offsets; there's no splitting.
- Not built yet: per-track auto-trim (`Track.auto_trim` exists but the exporter ignores it), drag handles for individual ranges, and workspace persistence.

## Interoperability test checklist

**None of the targets below have been verified yet.** Fill this in as each one is tested.

| Target | macOS drag-in | macOS drag-out | Windows drag-in | Windows drag-out |
|---|---|---|---|---|
| Cubase | ☐ | ☐ | ☐ | ☐ |
| RapidComposer 6 | ☐ | ☐ | ☐ | ☐ |
| Staccato.ai | ☐ | ☐ | ☐ | ☐ |
| Reason | ☐ | ☐ | ☐ | ☐ |
| Synthesizer V Studio 2 | ☐ | ☐ | ☐ | ☐ |
| Yamaha Omnivocal | ☐ | ☐ | ☐ | ☐ |
| Finder / Explorer | ☐ | ☐ | ☐ | ☐ |

For each target check: does the drop import at all (if not, note the formats listed in the error); are track names, channels, lyrics and tempo intact; does a rebased range land at the drop position with the correct length; and are there no stuck notes at range edges.

## Packaging

```bash
scripts/build_macos.sh            # → dist/MIDI Interchange.app + dist/MIDI-Interchange-<ver>-macOS-<arch>.dmg
```
```bash
powershell scripts/build_windows.ps1   # → dist\MIDI Interchange\MIDI Interchange.exe
```

These use PyInstaller with `midi_interchange.spec` (unused Qt modules such as WebEngine are excluded). The macOS build and DMG have been built and launch tested on Apple silicon. They're unsigned (ad-hoc signature only), so on another Mac you need right-click ▸ Open the first time. The Windows build hasn't been run yet. See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md#building-standalone-apps).
