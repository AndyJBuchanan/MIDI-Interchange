# Plan: native Cubase project import (`.cpr`)

Branch: `feature/direct-daw-import-cubase`, based on and targeting
`feature/direct-daw-import`.

Status: **phase 3 implemented** (2026-11-15): the reader is in the app;
manual checks are in [TEST_CHECKLIST section 8n](../TEST_CHECKLIST.md#8n-cubase-project-import-feature-direct-daw-import-cubase).
Phase 2 complete, go (2026-11-15). Phase 1 (object framing, MIDI
part events) is complete for Cubase 15 and 16, `RIFF` and `RIF2`. Phase 2 has
decoded part windows, trims, mute, shared copies, track mute and solo,
program change, tempo and signature tracks, markers, folders and the display
offset, and indy matches Cubase's MIDI export; see
[Phase 2 findings](#phase-2-findings-2026-11-15) and [Phase 3](#phase-3-the-reader-2026-11-15). Cubase was chosen as the first native reader after
DAWproject. Reason follows, after a short feasibility probe.

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
  - indy and GA both report version 15.0.30, but only indy is `RIF2`. Every
    tier 1 fixture is `RIF2`, even the 100 KB empty project, so size doesn't
    select the variant. The reader must handle both.
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

## Phase 1 findings (2026-11-14)

Research tool: `tools/cpr_inspect.py` (read-only; `roots`, `tree`, `classes`,
`notes`, `diff`, `hex`). Regression evidence: `tests/test_cpr_inspect.py`
(24 tests). Everything below is from our own saved files.

### Object framing

All integers big-endian. Tag width W is 4 bytes in `RIFF` files and 8 in
`RIF2`; object lengths are W bytes too. Name lengths stay u32, versions u16.

- **BASE** `FF..FE` · u32 nameLen · name\0 · u16 version. Declares one parent
  class of the NEW class that follows; a run lists parents nearest first.
  Each BASE tag is itself a class declaration that later objects can refer
  to (GA declares `MMidiNote` as a base of `MScaleEvent`, then refers to it).
- **NEW** `FF..FF` · u32 nameLen · name\0 · u16 version · uW length · body.
- **REF** `0x80..` OR'd with the **archive byte offset of the class's
  declaration tag** · uW length · body. This is why cpr2rpp found ids that
  "vary between files". Target 0 never occurs as a real reference.
- Lengths nest exactly: `PArrangement` fills the `Arrangement1` archive.
  Bodies hold class-specific fields with child objects among them; the
  inspector finds children by validated tags. A few named records
  (`Name`, `Max`, `Title`, `SummingMode`) inside attribute blobs can look like
  NEW tags; the reader must descend by structure, not by scanning.
- Strings: u32 length (including terminator) · UTF-8 · `\0` · `EF BB BF`.
- Class versions change between releases: `PArrangement` v4 (15) / v5 (16),
  `MInstrumentTrack` v10 / v11. The reader should check versions it relies on.

### Arrangement structure

`PArrangement` → `MRoot` → `MTrackList` → track events (`MFolderTrack`,
`MInstrumentTrackEvent`, `MMidiTrackEvent`, tempo, signature, device) →
the track's `MListNode` (track name at its start) → `MMidiPartEvent` →
`MMidiPart`. `MMarkerTrackEvent`, `PArrangeSetup` and
`ProjectLyricsSettings` also hang off the arrangement; to examine in phase 2.

### MIDI parts

- **`MMidiPartEvent`** (the part on the timeline): u16 · f64 start · f64
  length, in **ticks at 480 PPQ from the project's absolute zero**. The
  one-bar display offset in c02-1 moves the start to 1920: the blank bar is
  real time before "bar 1".
- **`MMidiPart`** (the contents): string name · uW · u32 · uW (unknown) · u32
  event count · u8 event-class count (absent when the count is 0) · that many
  zero-length class entries (NEW or REF; the first part in a file declares
  the seven MIDI event classes) · the events.
- **Each event** is one byte, then a body:
  - a MIDI status byte (`90` note, `B0` controller, `E0` pitch bend, …)
    means a compact body whose class the status implies;
  - `00` means a full NEW/REF object header precedes the same body. Notes
    just drawn or edited use this form, probably because the selection refers
    to them. Harmless for reading; its length gives a free consistency check.
- **Event body:** f64 position (ticks, relative to the part's content) · u8
  channel · two MIDI data bytes (note pitch and velocity; controller number
  and value; pitch bend LSB and MSB, to confirm with tier 3) · u32 (zero so
  far) · u16 property count · properties · type-specific fields.
- **Properties:** reversed FourCC · u16 type · value. Type 1 is i64, type 4
  f64, type 2 an embedded NEW/REF object. Seen: `OffV` release velocity as
  (v − 1) / 126 (64 → 0.5); `HRDT` velocity in the same form; `GLFX`,
  `relP`, `ncda`, `VOCE`, `cuTy` (unknown); `cuOb` on controllers holds a
  `MParamEventCurveRationalBezier`. **Cubase stores controller curve shapes
  between points**, so its MIDI export renders more CC messages than are
  stored; phase 2 must compare against the export with that in mind.
- **Note-specific:** f64 length in ticks, then 17 bytes ending in `40`
  (release velocity 64 again, probably).

### Evidence

| Project | Format | Parts | Notes | Controllers | Pitch bends | Problems |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Tier 1, c01–c09 and c02-1, both versions | `RIF2` | 0–1 | as saved | 0 | 0 | 0 |
| Ditty (15.0.21) | `RIFF` | 176 | 1,501 | 1,161 | 16 | 0 |
| GA (15.0.30) | `RIFF` | 182 | 6,435 | 0 | 0 | 0 |
| indy (15.0.30) | `RIF2` | 104 | 819 | 0 | 0 | 0 |

Every part's declared event count is consumed exactly to the part's end.
The note counts equal the DAWproject exports' stored notes (1,501, 6,435
and 819), and GA's and indy's part counts equal their clip counts. Ditty's
extra part is an empty Rare Flutes (D) part at tick 58,560, probably left
out of the DAWproject clip count; confirm in phase 2. indy's 644 missing
drum notes are not in any `MMidiPart`, consistent with them being
`MPatternEvent` data.

### Go decision

The phase 1 criterion is met: tier 1 notes come from structured fields, and
the same code walks all three realistic projects without errors. Object
framing is decoded; bodies outside MIDI parts are walked by tag, not yet
field by field.

### Phase 2 priorities from these findings

1. Track records: name, type, channel, mute, folder nesting; which part list
   belongs to which track. Ditty's disabled clips (52) give the part-mute
   flag to find, with c13/c14 in tier 2.
2. Part trims: the unknown `MMidiPart` header fields and `MMidiPartEvent`'s
   leading u16 are candidates (tier 2, c11/c12).
3. Tempo, signature and marker tracks (tier 3), and the display offset
   setting (likely `PArrangeSetup`), so imports can decide whether bar 1
   lands at zero.
4. Then the indy go/no-go comparison against `indy-001x.mid`.

## Phase 2 findings (2026-11-15)

Inspector: `cpr_inspect.py notes` now lists tracks with mute, and parts with
window, offset, mute and shared state; `cpr_inspect.py timeline` lists tempo
and signature points. 42 regression tests in `tests/test_cpr_inspect.py`.

- **`MMidiPartEvent`:** u16 flags · f64 start · f64 length · f64 **content
  offset** · contents. Bit 1 (`0x0002`) of the flags is **part mute** (c13;
  Ditty 52, indy 2, GA 0, exactly as in the DAWproject exports). An end trim
  changes only the length (c12); a start trim moves the start and sets the
  content offset (c11: start 8160, offset 480). A note's absolute time is
  start − offset + position; the visible window is [start, start + length).
- **Shared copies (c16):** instead of an `MMidiPart` object, the part event
  holds a W-byte **object back-reference**: high bit clear, value = the offset
  of the referenced object's length field (just after its class tag or
  declaration). An independent copy (c15) writes its own `MMidiPart`.
- **Track mute and solo (c14, c17s, c17m):** a u32 **channel state flags**
  word: bit 0 = solo, bit 2 = mute, the same for instrument and MIDI tracks.
  GA's two muted tracks have mute set; all other fixture tracks are clear.
  Muting an instrument track also adds a mixer record `SoloFlag` = 1, and
  soloing adds `Solo` = 1; these look like mixer-side copies.
  **Located by structure, not by port name** (`state_flags_offset`): the
  track's MIDI input is a *port record* (u16 3 · string id · u16 0 · string
  name; both "All MIDI Inputs" for the default input, but any name works).
  - `MInstrumentTrack` (v10, v11): the flags follow the last input port
    record, then a tail of u16 count (0 or 1) · that many BOM strings (Ditty's
    Groove Agent track names its loaded pattern, "Feel How Sweet It Is - Groove
    Agent SE [1]") · 14 bytes · i64 −1 (`FF` × 8). Cubase 16 (v11) appends a
    short `FAttributes` object after that.
  - `MMidiTrack` (v8, Cubase 16 fixtures only): the body starts with the
    output port (u16 3 · id · 4 bytes · name, e.g. "Input 1"), then the input
    port record, a u32 (1 for c17's channel-2 track; possibly the channel,
    unconfirmed), then the flags.
  Verified on every instrument and MIDI track in every fixture, plus
  synthetic bodies with other port names.
- **Track names** start the track event's `MListNode` child; GA, Ditty and
  indy names match their DAWproject tracks.
- **Program change (c25):** the standard event layout; data = program, 0.
  Every short MIDI event uses channel + two data bytes; poly and channel
  pressure assumed the same (no fixture). Sysex not decoded.
- **Channels:** a MIDI track on channel 2 (c17) writes channel byte 1 into
  each event. Instrument-track events so far use 0.
- **Tempo track (`MTempoTrackEvent`):** u32 count · points of f32 seconds per
  beat · f64 seconds · f64 ticks · u16 type (1 = ramp into this point) · then
  f32 tempo in BPM (120 in the tiers, 93 in GA; probably the fixed tempo).
  **Ramps are linear in beats**: the stored seconds match
  60·beats/(bpm₁−bpm₂)·ln(bpm₁/bpm₂) to 1 µs (c20). GA's native tempo track
  has two real ramps (93→97 over beats 264–272, 97→93 over 384–432).
  No separate "tempo track active" flag was found in `Arrangement1`.
- **Signature track (`MSignatureTrackEvent`):** u32 count · 16-byte points of
  u32 ticks · u16 numerator · u16 denominator · 8 bytes unknown (c21: 3/4 at
  tick 7680).
- **Folders (c18):** an `MFolderTrack` holds its own `MTrackList`, whose body
  starts with the folder's name. **No folder is special.** Cubase's I/O folder
  ("Input/Output", or "Input/Output Channels" in older saves) holds in/out
  channel (device) tracks; rack instrument folders (e.g. HALion Sonic) hold
  device tracks too. Neither normally holds MIDI parts. Tempo, signature,
  marker and chord tracks are loose by default and can be moved anywhere,
  including into folders (GA has them loose; the other fixtures have tempo and
  signature inside the I/O folder), so the reader finds them by class
  wherever they are.
  **Folder mute (c18fm):** the folder's state flags (same bits as tracks) are
  the u32 just before its `MTrack` child, which follows its `MTrackList`; muting a folder also sets the mute flag
  on every track inside it, so the saved track flags carry the inherited
  state.
- **Instrument stack (c18is):** also an `MFolderTrack`, containing a MIDI
  track named after the stack. Stacking **moves the parts onto that stack
  track**; the member instrument track is left empty. Cubase's export naming
  ("Instrument Stack 01") is therefore literal; imports should use it too.
- **Markers (c22, c23):** the marker track's `MListNode` holds a count, then
  `MMarkerEvent` / `MRangeMarkerEvent` objects: string name · u32 id · u16 ·
  f64 start · f64 **length** (ticks; 0 for plain markers). indy's contiguous
  sections (each 32 beats, each ending where the next starts) confirm length,
  not end. Cubase's MIDI export writes plain marker meta events at starts.
- **Display offset (c02-1):** `PArrangeSetup` i32 at body offset 84, in bars:
  0 normally, −1 for one blank bar before bar 1. Ditty −3, indy −1, GA 0.
  **The absolute timeline is unaffected, and Cubase's MIDI export ignores the
  offset**: Ditty's first notes are a six-beat pickup at absolute beat 6, before
  its displayed bar 1 (beat 12), and its export has them at beat 6.
- **Linear time base (c26):** the part event holds seconds and the part body
  layout differs; not decoded (deferred).

### Phase 2 go decision

**Go.** indy's four available tracks match Cubase's own MIDI export in the
explicit [3, 196) window: all **663 notes** match in onset, pitch, velocity
and channel, and lengths match within one tick, except the two known Texture
Bed tails (the clip-edge policy, the same residue as DAWproject). Cubase
stores **fractional ticks** (e.g. 102.953) and rounds them on export; the reader
should keep the fractions. The 644 missing drum notes are Pattern Editor data
(`MPatternEvent`), as expected. `tests/test_cpr_inspect.py` (57 tests) pins all
of this.

Open for phase 3 or later: linear time base, pattern
events, controller curve shapes, chord track names, and sysex.

## Phase 3: the reader (2026-11-15)

- **Code.** `core/cpr_format.py` holds all format decoding (moved from the
  inspector, which now imports it); `core/import_cubase.py` maps it onto the
  model; `interchange/readers.py` registers `.cpr` (path-backed, detected by
  extension or by the `RIFF`/`RIF2` + `NUND` magic). The tag scan jumps
  between candidate bytes (`0x80`/`0xFF`): Ditty decodes in 0.04 s instead of
  1.26 s, fast enough for drag-enter previews.
- **Mapping.** One track per instrument/MIDI track with parts; clip zero is
  the part's content zero (or its visible start when the part was extended
  before its content: GA's negative offsets); trims and part mute map
  directly; shared copies share one event list; fractional ticks are kept as
  exact fractions (denominator-bounded). Notes carry release velocity from
  `OffV`. Track mute/solo come from the state flags; folder state is applied to
  contained tracks with a diagnostic. Instrument-stack parts arrive under the
  stack track's name, as in Cubase's export. Tempo points become a stepped map
  (ramps: one step per beat at the midpoint tempo; within about 0.02 BPM of
  Cubase's own export steps); signatures map directly; markers go on an
  auxiliary Markers track, with `name |` closing markers per decision 4.
- **Source.** `input_format='cubase'`, `format_version` and `app` from the
  `Version` archive, PPQ 480, `display_bar_offset` recorded (decision 7;
  session schema 4 with a captured schema-3 upgrade fixture). Source Info shows
  a "Display" line when the offset is non-zero.
- **Diagnostics and failures.** Reported as skipped: audio, Pattern Editor
  parts, the chord track, instruments/inserts/modifiers/track parameters,
  controller curve shapes, linear-time-base tracks, and any part events after
  an undecodable one (sysex). Versions other than Cubase 15/16, damaged files
  and invalid values fail with `ImportError_` before the workspace changes.
- **Evidence** (`tests/test_import_cubase.py`, 24 tests;
  `scripts/compare_project_exports.py` now also compares `.cpr` projects):
  - Note, muted-part and muted-track counts equal the DAWproject exports for
    Ditty, GA and indy.
  - indy through the real exporter vs Cubase's MIDI in [3, 196): all notes
    match exactly except the two known Texture Bed tails.
  - The native reader matches Cubase's MIDI exports more exactly than the
    DAWproject route (e.g. Ditty Rare Flutes 47/47 exact vs 29 + 18 within a
    tick; GA HALion Sonic 80/80 vs 68 + 12), because Cubase's DAWproject export
    rounds positions through seconds.
  - GA: the two readers agree within one tick before beat 264. After GA's
    first tempo ramp, DAWproject positions drift (271.83 for 272) because
    Cubase's DAWproject export keeps seconds but reduces ramps to steps; native
    positions stay on the beat grid. This explains the earlier "first BPM
    change near 271.834" observation.
  - GA's windowed comparison shows five reference notes starting exactly at
    the window end (beat 192, no note-off in Cubase's export); native positions
    place them at 192, outside [0, 192). A boundary artefact, not a reader
    fault.
- **Full suite:** 521 passed, 3 platform skips.

### Spot-test fixes (2026-11-15)

Four user projects in `samples/project-cubase-phases/Verify` (not yet
committed; tests skip when absent) exposed decoder assumptions:

- **Mixer flags tail varies.** After the flags, BBCSO (15.0.10) has a u32
  count and the track's own name; Beat003vs ends `FF FF FF FF 00 00 00 00`.
  The flags are now taken after the **last** input port record in the mixer
  object's tail, checking only that the value holds state bits.
- **Other objects inside parts.** BBCSO parts begin with `MScoreEvent`
  objects (Score Editor symbols). Framed objects of unknown classes are now
  stepped over (their length is explicit) and reported; previously decoding
  stopped and those parts' notes were lost.
- **Property types are a kind byte plus flags.** 1 = i64, 4 = f64; other kinds
  hold objects (0x22 `ScAr` with **Omnivocal lyric attributes** such as
  "Kettles[k eh]"; 0x0408 a string object). A future lyrics feature could
  import these.
- **Out-of-range stored values.** The orchestral project stores one
  aftertouch value of 201; such events are skipped with a warning instead of
  failing the import. Aftertouch is confirmed as channel · value · 0, with
  `HRDT` = value / 128.
- **Speed.** That project's arrangement archive is 172 MB, mostly plug-in
  states inside mixer objects. The reader now registers every class
  declaration with a regex pre-pass, then doesn't walk mixer-object bodies:
  0.18 s instead of 3.5 s, with identical results on all 48 fixture and verify
  projects.
- **Cubase 14** (Scaler3Test, 14.0.20) walks with the same classes, but has no
  MIDI parts, so it can't validate the reader; Cubase 14 stays unsupported
  until a project with parts is checked.

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
- For trim and move steps, note the part's Start, End and Length from the Info
  Line. Exact values needn't be tidy; they are a reference for decoding.
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
| c02-1 | c02 with a one-bar display offset (a blank bar before bar 1). Added by the user; real projects often use it |

### Tier 2: parts and the timeline (phase 2)

| # | Change |
| --- | --- |
| c10 ✱ | Move the part to bar 5 |
| c11 | Trim the part's start by one beat (drag the left edge) |
| c12 ✱ | Trim the part's end by one beat |
| c13 ✱ | Mute the part (track unmuted) |
| c14 ✱ | Unmute the part, mute the track |
| c15 | Unmute the track. Copy the part so the copy starts at bar 9 (Option/Alt-drag, or copy and paste at 9.1; not Ctrl/⌘-D, which places it straight after) |
| c16 ✱ | From c14 + unmute, make the bar 9 copy a shared copy instead (Option/Alt-Shift-drag) |
| c17 ✱ | Add a **MIDI track** (not an instrument track; Add Track ▸ MIDI), output to any instrument or Not Connected, MIDI channel 2 in the Inspector, with one part and one note. All realistic fixtures use instrument tracks only, so this is the only MIDI-track example |
| c18 ✱ | Put both tracks in a folder track |
| c17s | Optional, from c17: solo the Lead track (isolates solo) |
| c17m | Optional, from c17: mute the MIDI track (isolates MIDI-track mute) |
| c18fm | Optional, from c18: mute the folder (isolates folder mute) |
| c18is ✱ | Optional, Cubase 16: from c17, move the instrument track To New Instrument Stack instead (only instrument tracks can be stacked) |

### Tier 3: tempo, meter, markers, controllers (phase 2)

| # | Change |
| --- | --- |
| c19 ✱ | Tempo track active, tempo change to 90 BPM at bar 3 (jump) |
| c20 ✱ | Change that to a ramp from bar 3 to bar 5 |
| c21 ✱ | Time-signature change to 3/4 at bar 5 |
| c22 ✱ | Marker track with a marker named `Verse` at bar 2 and `Chorus` at bar 6 |
| c23 | One cycle (range) marker named `Intro`, bars 1–3 inclusive: start 1.1.1.0, end 4.1.1.0 |
| c24 ✱ | In the MIDI track's part at bar 1 (channel 2), a mod wheel (CC1) ramp and a pitch bend |
| c25 ✱ | Program change and sustain pedal (CC64) on/off |
| c26 | Switch the Lead instrument track from musical to linear time base (Inspector: the note-symbol button beside the track name toggles to a clock). Its part at 5.2 lies after the tempo changes, so positions may be stored in time rather than ticks |

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

### Received

- **Tier 1** (used for phase 1), Cubase 15.0.30 and 16.0.5 (2026-11-14), in
  `samples/project-cubase-phases/Tier 1`. Both MIDI exports match the spec, and
  the 15 and 16 exports are byte-identical. Re-saving with no change (c08 → c09)
  alters 53–66 bytes; single-field edits (c04 → c05, c05 → c06) alter 55–67,
  starting near byte 3070. Diffs must filter per-save noise.
- **Tier 2**, Cubase 16.0.5 only (2026-11-14), in
  `samples/project-cubase-phases/Tier 2`. The phase 1 decoder reads every part;
  positions and lengths agree with the MIDI exports. The c12 end trim is one
  sixteenth (length 3240 ticks). Still to decode: the start-trim offset (notes
  stay relative to the untrimmed origin), part and track mute, and the shared
  copy in c16 (its part event refers back to the first part's contents).
  `c18is` (instrument stack) decodes as is: the stack is saved as an
  `MFolderTrack` holding the instrument track, plus `VstInstrumentMidiChannel`,
  `SoloManager` and `NodePath` objects. Cubase's MIDI export names the stacked
  track after the stack ("Instrument Stack 01"), not the member ("Lead"):
  decide in phase 2 which name imports use.
- **Tier 3**, Cubase 16.0.5 (2026-11-15). First results:
  - Pitch bend data bytes are LSB, MSB (stored `3c 10` = 2108 = −6084 from
    centre, as exported); CC1 value matches.
  - **Controller and pitch-bend curves are stored as points and rendered on
    export:** c24 stores 2 CC1 and 12 pitch-bend points; Cubase exports 36 and
    251 messages. A tempo ramp (c20) exports as 10 stepped tempo events.
  - Cubase exports a cycle marker (c23) as a marker at its start ("Intro").
  - **Linear time base (c26) stores seconds:** the Lead part event reads
    start 9.266, length 4.5 (6.75 beats at 90 BPM), and the part body layout
    changes. Defer linear tracks until musical tracks work; the user never
    uses them.
  - Not yet decoded: program change (status `C0`), tempo, signature and
    marker tracks.

## Decisions (2026-11-15)

1. **Generated material.** Skip MIDI inserts with diagnostics. Decide pattern
   events and track transpose/velocity once phase 2 shows how they are stored.
   **Chord track:** don't render chords as notes, but show the chord names on a
   new proxy marker track. Investigation and design come in a later phase;
   recorded in the roadmap.
2. **Version support.** Cubase 15 and 16 for now, with a clean "unsupported
   version" message for others. The user can later supply real-world projects
   from Cubase 14, 13 and 10.5 (not progressive c-series files) for broader
   support.
3. **Fixture privacy.** No action. The embedded paths reveal only the user's
   name, which is already public through the GitHub account. Revisit only if
   fixtures would expose more.
4. **Cycle (range) markers.** A named marker at the range start (`Intro`), and
   a closing marker at the range end named after the range with a bar
   (`Intro |`). Omit the closing marker when it coincides with the start of
   another range or with a standard marker.
5. **Tempo ramps.** Approximate with fine tempo steps, with a diagnostic.
   Cubase's own MIDI export does the same (c20).
6. **Controller curves.** Defer rendering. Import the stored points (with a
   diagnostic) and decode the curve shapes and control points, so rendering and
   its density can be decided later.
7. **Display offset** (2026-11-15). Import on Cubase's **absolute timeline**,
   as its own MIDI export does; do not apply the offset. Record it in the
   source details so it is available later. A likely future use is display
   only: numbering the ruler's bars with the offset when that source supplies
   the tempo map.
