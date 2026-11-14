# Plan: native Cubase project import (`.cpr`)

Branch: `feature/direct-daw-import-cubase`, based on and targeting
`feature/direct-daw-import`.

Status: **draft, not started** (2026-11-14). Cubase was chosen as the first
native reader after DAWproject. Reason follows, after a short feasibility probe.

The scope and rules come from the [roadmap entry](../ROADMAP.md) and the
[direct DAW import plan](direct-daw-import.md). They aren't repeated here. In
short: drop a saved `.cpr` in and get the current arrangement as MIDI through
the normal import. Keep track and clip mute. Never modify the project. The
reader plugs into the shared registry (`interchange/readers.py`) and returns
`(Source, list[Track])` like the MIDI and DAWproject readers.

## Why Cubase next

- **Test material exists.** Three realistic `.cpr` files are committed, each
  paired with a Cubase MIDI export and a DAWproject export
  (`samples/project-sets`). The comparison harness
  (`scripts/compare_project_exports.py`) already treats Cubase MIDI as ground
  truth.
- **The container is structured, not opaque** (see below). We can walk it
  rather than scan for byte signatures.
- **It answers questions DAWproject couldn't.** indy's missing drum notes, GA's
  +24 Prologue transpose and Ditty's arpeggiated parts all point to data that
  is in the `.cpr` but not in its DAWproject export.
- It is the DAW in most active use here (Cubase 15 and 16).

## What the fixtures already show

Read from the three committed `.cpr` files, without Cubase. Unverified beyond
these files.

- **Container.** A big-endian RIFF-style file with form type `NUND`.
  - `RIFF` uses 32-bit chunk sizes (Ditty, GA).
  - `RIF2` uses 64-bit chunk sizes (indy). Class and object tags inside the
    archives widen from 4 to 8 bytes as well.
  - indy and GA both report version 15.0.30, but only indy is `RIF2`. File
    size or a save setting may select the variant; to find out.
- **Top level.** A sequence of `ROOT` records, each naming an `ARCH` archive and
  its root class:

  | ROOT name | Root class | Notes |
  | --- | --- | --- |
  | `Version` | `PAppVersion` | Saving application and version |
  | `Arrangement1` | `PArrangement` (`GDocument`) | The song. The only archive the reader needs, apart from Version |
  | `ComputerGuid` | `CmString` | Ignore |
  | `Devices` | `FAttributes` | Ignore |
  | `WindowLayouts`, `ProjectLayouts` | `UWindowLayout`, `FAttributes` | Ignore |
  | `Metadata` | `StMedia::PAttributes` | Possibly the song title; to check |
  | `Previewdata` | `StMedia::PAttributes` | Ignore (about 1 MB) |

- **Object serialisation.** Each archive introduces a class by name the first
  time it is used: a `0xFFFFFFFE` tag, a length-prefixed name such as
  `CmObject` or `GDocument`, then the object. Later objects refer back to
  classes or objects by index. The details are the first thing the spike
  decodes.
- **Class names seen in the arrangement:** `MMidiTrack`, `MMidiTrackEvent`,
  `MInstrumentTrack`, `MInstrumentTrackEvent`, `MFolderTrack`, `MMidiPart`,
  `MMidiPartEvent`, `MMidiNote`, `MMidiEvent`, `MTempoTrackEvent`,
  `MTimeSignatureEvent`, `MSignatureTrackEvent`, `MMarkerTrackEvent`,
  `MMarkerEvent`, `MRangeMarkerEvent`, `MChordTrackEvent`, `MAutomationTrack`,
  `MAudioTrackEvent`, `MHitPointEvent`.
- **indy contains `MPatternEvent`** next to its "Drum Core" track. The
  DAWproject export of those two drum lanes is empty, but the Cubase MIDI has
  644 drum notes. This is a strong lead that they are Pattern Editor data.
- **Ditty contains `PMidiArpeggiator` / `Arpache 5`**, and all three files have
  many "Transpose" strings. These match the rendered differences recorded in
  the [Ditty](../DAWPROJECT_DITTY_FINDINGS.md) and
  [other-pair](../DAWPROJECT_OTHER_PAIRS_FINDINGS.md) findings.

### Fixture caveats

- **The native files predate their exports.** The `.cpr` version strings are
  15.0.21 (Ditty) and 15.0.30 (GA, indy), and the files are dated Jun 2 and
  Nov 2. The MIDI and DAWproject exports are from Nov 14, made with 15.0.30
  and 16.0.5. The saved project may not be the state that was exported. A
  mismatch against them is not yet evidence of a reader fault. Re-save requests
  are in the [fixture catalogue](#fixture-requests).
- **Privacy.** The committed `.cpr` files contain absolute paths from the
  author's machine (home folder, volume names), and the repo is public. New
  fixtures should be saved in a neutral folder. Whether to keep the existing
  three is an open question below.

## Prior work to read first

Read for understanding; check each licence before copying any code.

- [cpr2rpp](https://github.com/daniel-lynch/cpr2rpp) `docs/FORMAT.md` (MIT,
  Cubase 12.0.50): container, object framing, tracks, audio events. It has no
  MIDI, tempo or markers, and found no part-mute flag for audio events.
- [cubase-project-plugins](https://pkg.go.dev/github.com/fgimian/cubase-project-plugins/parser)
  (Go): walks the container to list plug-ins and the version.
- [Marker export gist](https://gist.github.com/andigamesandmusic/94be52eff000013d7cdf5daef54bc4aa)
  (JavaScript): marker track to JSON.
- Studying only files we saved ourselves; no decompiling of Cubase (see the
  [legal section](direct-daw-import.md#legal-and-licensing)).

## Approach

Four phases. Phases 1 and 2 are research with go/no-go points; production
code starts at phase 3.

### Phase 1: inspector and object framing (spike)

Timebox: about two working sessions.

- Write a read-only research tool, `tools/cpr_inspect.py` (not shipped in the
  app). It dumps the ROOT/ARCH tree, the class table and the object tree of
  `Arrangement1`, with offsets. It has a diff mode for two files.
- Decode object framing (class tags, back-references, field lengths) for both
  `RIFF` and `RIF2`, until the whole `Arrangement1` archive parses with no
  bytes left unexplained at the framing level. Field meanings can stay unknown.
- Use the progressive files (tier 1) to identify the note, part and track
  records.

**Go/no-go:** go if a one-note project gives its note's pitch, velocity, start
and length from structured fields (not signature scanning), and the same code
walks all three realistic files without errors. Otherwise stop, record what was
learned, and reconsider the order (Reason probe, Logic).

### Phase 2: musical mapping (spike continues)

- Tracks: name, type (MIDI or instrument), folder nesting, order, MIDI channel.
- Parts: position, length, the part's start offset into its events (trims),
  name, shared copies (ghost parts), and repeats if stored as such.
- Notes: pitch, velocity, release velocity, start, length, channel.
- Controllers, pitch bend, aftertouch, program change and SysEx stored in parts
  (`MMidiEvent`). Cubase stores these in parts, unlike its DAWproject export.
- Tempo track: events, tempo ramps, and whether the tempo track is active.
  Fixed-tempo mode uses one tempo.
- Signature track, marker track (cue markers; range markers as named regions
  become markers at their start, or are skipped with a diagnostic; to decide).
- Mute: track mute, part mute (DAWproject's `enable` maps from Cubase part
  mute, so the flag should exist for MIDI parts).
- Musical vs linear (seconds) time base, per track and per part.

**Go/no-go:** go if indy's four DAWproject-visible tracks (Bass Sequence,
Industrial Stab, Secondary Motif, Texture Bed) match `indy-001x.mid` note for
note, within the explicit `[3, 196)` window already used for DAWproject, apart
from known release-velocity differences. Matching against a re-saved fixture
pair is acceptable if the committed `.cpr` turns out to differ.

### Phase 3: reader

- `core/import_cubase.py`, registered in `interchange/readers.py`.
  - Path-backed, extension `.cpr`. Detection: `RIFF…NUND` or `RIF2…NUND` magic.
  - Reads only the `Version` and `Arrangement1` archives (and `Metadata` if it
    has the title). Never loads `Previewdata` or media.
  - Bounded: file size cap, archive size cap, object count and recursion
    limits. Malformed or truncated input fails with `ImportError_` before the
    workspace changes.
  - Unsupported versions fail cleanly with the version found and the supported
    range.
- `Source.input_format = 'Cubase'`, `format_version` = the saving version,
  `app` from `PAppVersion`. Reuse DAWproject's precedent for PPQ and beat
  storage unless the native tick rate argues otherwise.
- Muted parts become `Clip.muted`; muted tracks keep their mute. Folder tracks
  flatten with inherited mute/solo, as DAWproject does.
- Diagnostics for everything skipped: audio, pattern events (unless decided
  otherwise), MIDI inserts and modifiers, chord track, expression maps, note
  expression, inactive lanes/takes, hidden tracks if the format marks them.

### Phase 4: evidence

- Extend `scripts/compare_project_exports.py` to take a `.cpr` as the project
  side, so the same report compares native import vs Cubase MIDI.
- Automated tests for the progressive fixtures (exact expected events, written
  by hand from what was saved) and the realistic sets (comparison against the
  MIDI, with known discrepancies listed explicitly, as for DAWproject).
- A feasibility-matrix entry for Cubase in the direct DAW import plan.
- Manual checks as a new numbered section in TEST_CHECKLIST, linked from here.

## Current arrangement vs everything stored

The reader exposes the arrangement as Cubase plays it, not every object in the
file. Rules to confirm against the fixtures:

- **Included:** parts on track lanes that play; muted parts and muted tracks,
  with their mute.
- **Excluded, with a diagnostic:** inactive lanes and takes (comping), the
  MIDI pool, disabled tracks (Cubase's "Disable Track", distinct from mute),
  and anything only in the undo history.
- **Hidden tracks:** hidden in the Project window but still playing. Include
  them; hiding is a view setting.

## Generated and processed material (decision needed)

The direct DAW import plan's open question 6 proposes these are reported as
skipped, not rendered. Cubase sharpens the question, because Cubase's own MIDI
export can render some of them, and that MIDI is our ground truth:

| Material | Stored as | Rendering effort | Without it |
| --- | --- | --- | --- |
| Pattern Editor events | Step data in the project | Medium: decode steps, expand to notes | indy loses 644 drum notes |
| Track transpose / velocity (MIDI modifiers, track parameters) | A few numbers per track | Low | GA Prologue is 24 semitones low |
| MIDI inserts (arpeggiator etc.) | Plug-in state | Out of reach: would mean reimplementing each plug-in | Ditty's arpeggiated parts differ |
| Chord track | Chord events | Out of scope: Cubase voices them at playback | Missing unless already converted to MIDI |

Proposal: skip inserts and the chord track with diagnostics. Decide pattern
events and track transpose/velocity after phase 2 shows how they are stored.

## Fixture requests

The three realistic sets stay. These add progressive files, each differing from
the previous one by **one** change, so the bytes can be diffed. Small files make
this fast.

### How to save them

- **Cubase 16.0.5**, in a new folder with a neutral name and no audio (for
  example `~/Music/cpr-fixtures/`), so no personal paths go into the repo.
- Start from an **empty project** with no template, at 120 BPM, 4/4. Leave the
  tempo track in fixed mode unless the step says otherwise.
- Use one **instrument track** with HALion Sonic (or any stock instrument) for
  steps that need sound, so that 16.0.5 opens it anywhere.
- **Save As** each step under its own numbered name: `c01-empty.cpr`,
  `c02-one-note.cpr`, and so on. Don't save over a previous step.
- **MIDI export** for steps marked ✱: File ▸ Export ▸ MIDI File, whole project,
  same name with `.mid`. Use the same export options every time, with
  **Export Inserts off**. Take one screenshot of the options dialog so we know
  them.
- Optional for the same ✱ steps: File ▸ Export ▸ DAWproject.
- Notes below are C3 = MIDI 60 (Cubase's default naming). If your display
  differs, say which octave convention you used.

### Tier 1: framing and notes (needed for phase 1)

| # | Change from the previous file |
| --- | --- |
| c01 | Empty project, saved. No tracks |
| c02 ✱ | Add one instrument track, one MIDI part bars 1–2, one note: C3, velocity 100, bar 1 beat 1, one beat long |
| c03 | Move that note to bar 1 beat 2 |
| c04 | Change its velocity to 64 |
| c05 | Change its pitch to D3 |
| c06 | Change its length to two beats |
| c07 ✱ | Add a second note: E3, velocity 90, bar 2 beat 1, half a beat |
| c08 | Rename the track to `Lead` and the part to `Riff` |
| c09 | Save c08 again under a new name with no change (shows what changes between saves) |

### Tier 2: parts and the timeline (phase 2)

| # | Change |
| --- | --- |
| c10 ✱ | Move the part to bar 5 |
| c11 | Trim the part's start by one beat (drag the left edge) |
| c12 ✱ | Trim the part's end by one beat |
| c13 ✱ | Mute the part (track unmuted) |
| c14 ✱ | Unmute the part, mute the track |
| c15 | Unmute the track. Duplicate the part to bar 9 (Ctrl/⌘-D) |
| c16 ✱ | Make the copy a shared copy instead (Edit ▸ Functions ▸ Repeat with Shared Copies, or Alt/Shift-drag) |
| c17 ✱ | Add a second MIDI track on channel 2 with one part and one note |
| c18 ✱ | Put both tracks in a folder track |

### Tier 3: tempo, meter, markers, controllers (phase 2)

| # | Change |
| --- | --- |
| c19 ✱ | Tempo track active, tempo change to 90 BPM at bar 3 (jump) |
| c20 ✱ | Change that to a ramp from bar 3 to bar 5 |
| c21 ✱ | Time-signature change to 3/4 at bar 5 |
| c22 ✱ | Marker track with a marker named `Verse` at bar 2 and `Chorus` at bar 6 |
| c23 | One cycle (range) marker named `Intro`, bars 1–3 |
| c24 ✱ | In the first part, a mod wheel (CC1) ramp and a pitch bend |
| c25 ✱ | Program change and sustain pedal (CC64) on/off |
| c26 | Switch the first track to linear (seconds) time base |

### Tier 4: inactive and generated material (phase 2 rules)

| # | Change |
| --- | --- |
| c27 ✱ | Record two takes over the same bars in lanes, with one take active (comping) |
| c28 ✱ | Disable a track (Disable Track, not mute) |
| c29 ✱ | Hide a track in the Project window |
| c30 ✱ | A Pattern Editor part on a drum track, one bar, kick on 1 and 3, snare on 2 and 4 |
| c31 ✱ | Track transpose +12 in the Inspector on the first track |
| c32 ✱ | MIDI modifiers: velocity shift +20 |
| c33 ✱ | Arpache 5 as a MIDI insert on the first track. Export twice: Export Inserts off (`c33.mid`) and on (`c33-inserts.mid`) |
| c34 | A chord track with two chord events, not converted to MIDI |

### Version coverage

- **c02 and c07 also saved from Cubase 15** (whichever 15.0.x you have), named
  `c02-cb15.cpr` and `c07-cb15.cpr`, to see what differs between versions.
- If you know what makes Cubase write `RIF2` instead of `RIFF`, say. Otherwise
  the spike will try to find out from the files.

### Re-saved realistic sets

For each of Ditty, GA and indy: open the project in 16.0.5, save it as a new
`.cpr`, then export MIDI (with the same options as above) and DAWproject in the
same session without changing anything. This gives pairs known to match. Keep
the existing files too.

## Questions for you

1. **Generated material.** Agree to skip MIDI inserts and the chord track with
   diagnostics, and decide pattern events and track transpose/velocity after
   phase 2?
2. **Version support.** Cubase 15 and 16 only, with a clean "unsupported
   version" message for others?
3. **Fixture privacy.** Commit the new progressive fixtures (saved in a neutral
   folder)? Keep, replace or remove the three existing `.cpr` files that
   contain your local paths? Removing them from history would need a rewrite;
   replacing them going forward does not.
4. **Range markers.** Map cycle markers to a marker at their start (named), or
   skip them with a diagnostic?
5. **Tempo ramps.** DAWproject fails on ramps. For Cubase, should the reader
   approximate ramps with fine steps (and say so), or fail as DAWproject does?
