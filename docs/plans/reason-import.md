# Plan: native Reason song import (`.reason`), feasibility

Status: **Phase 1 (format decoding) done** (2026-11-15): the r-series decodes
note-for-note against Reason's MIDI exports; see [Phase 1 findings](#phase-1-findings).
Phase 0 probe: GO for Reason 13 and 14 songs.
Those are plain, structured IFF. Songs saved by Reason 12 and earlier have an
encrypted payload and are out of scope (see [Phase 0 result](#phase-0-result-go)). The
desk study below was written before any file was examined; where it conflicts
with the probe, the probe wins. Work is on `feature/direct-daw-import-reason`.

The scope and rules come from the [roadmap entry](../ROADMAP.md) and the
[direct DAW import plan](direct-daw-import.md): read the saved song, import the
current arrangement through the normal reader registry, keep track and clip
mute, never modify the file. The Cubase reader ([plan](cubase-import.md)) is
the model for method, fixtures and evidence.

## What is known without files

### The format

- **No public format documentation or prior work found.** Searches find no
  parser, specification or reverse-engineering notes; Archive Team's format
  wiki says only that `.reason` replaced `.rns` and the differences are
  undocumented. DawVert does not read Reason.
- **Encryption: unresolved, and the first thing to settle.**
  - A Reason Studios post quoted in a KVR thread says songs were encrypted
    from Reason 6 to 12.5 and are not from 12.6 (see
    [direct DAW import plan](direct-daw-import.md#reason-reason)). That is the
    only source, and it is second-hand.
  - Our own capture points the other way for current versions: Reason 14's
    **clipboard** payload is high-entropy (7.6–7.9 bits/byte), doesn't
    decompress with any common codec, and looks encrypted
    ([INTEROP_FINDINGS](../INTEROP_FINDINGS.md#reason-14-proprietary-compressed-or-encrypted)).
    Song files may be protected the same way.
  - **Rule:** if song files are encrypted, stop. We study files we saved, but
    we do not break encryption (fragile, and a licence concern). Reason then
    stays on the routes that already work: drag-and-drop and MIDI export.
- Reason 13 lists many openable song types (`.reason`, `.rns`, `.rps`,
  `.rsb`, demo and Reason Essentials/Lite variants). Only `.reason` saved by
  the user's Reason (14) is in scope at first.
- **Self-contained songs embed samples** (losslessly compressed), so files
  can be large: the reader must be path-backed and read only what it needs,
  like the DAWproject and Cubase readers.

### What a song holds (from Reason's manual)

The song holds the rack, mixer and sequencer. Sequencer concepts the reader
would meet:

| Concept | Relevance |
| --- | --- |
| Instrument tracks with **several note lanes** each; each lane has its own Mute | Lane mute is a third mute level, between clip and track |
| **Note clips**, clip mute (Mute tool) | Map to clips and `Clip.muted` |
| Track mute/solo | Map to track state |
| Recorded **performance controllers** (mod wheel, pitch bend, sustain…) in note clips | MIDI data, should import |
| **Parameter automation lanes** (device knobs) | Not MIDI; skip with a diagnostic |
| **Pattern lanes** on pattern devices (Redrum, Matrix…): clips hold bank + pattern number | The notes are in the device, not the sequencer; report as skipped unless converted to notes in Reason |
| **Player** devices (MIDI effects generating notes) | Generated at playback; report, don't render |
| **Blocks mode**: a Blocks track whose Block automation clips choose which Block section plays | The arrangement may be built from Blocks; needs a rule (see questions) |
| **Transport track**: tempo automation lane and time-signature automation lane | The tempo map. Tempo and time-signature automation live in **clips**; outside any clip the song's global tempo and signature apply (confirmed by the user, r17 and r19). Ramps are lines between automation points |
| Left/Right locators, **End marker** | MIDI export runs from song start to the End marker |
| Alien clips (imported data that doesn't fit a lane) | Report |
| No MIDI channels in the sequencer | Every imported track is channel 1, as Reason's own export does |

No marker or lyric track is described in the manual; to confirm with files.

### Reason's MIDI export (the ground truth for comparisons)

From the manual: Type 1, one MIDI track per sequencer track with the same
names, **all on channel 1**, all instrument and automation tracks, tempo and
tempo/time-signature automation included, **from song start to the End
marker**. Not stated: PPQ, and whether muted clips, lanes or tracks are
exported. The fixtures below settle that. Two consequences for fixtures: set
the End marker after the last note, and expect channel 1 everywhere.

## Phase 1 findings

Decoder: `midi_interchange/core/reason_format.py`; research CLI:
`tools/reason_inspect.py` (`copies`, `tree`, `tracks`, `diff`); tests:
`tests/test_reason_format.py` (synthetic files, plus the r-series against the
MIDI exports when the local fixtures are present).

**Result: all 16 exported r-files and six real songs (51 tracks, Reason 13
and 14) render exactly the notes Reason exported** (position, pitch,
velocity, length). The rules are in `played_notes()`. Every Reason 13 and
14 real-world song in the probe set decodes in hundredths of a second.

### Container: a paged store, not a single song

- Header: `X15_FILE`, u32 page size (0x40000), u32 0x24, u64, u64 (an index
  page, but not reliably the newest), 5 x u32 not decoded.
- An **index page** (8 x 0xFF) lists streams: id, byte size, page list. Stream
  1 is the song; other streams are embedded samples. Pages need not be
  contiguous.
- The song stream is `FORM X15S` + `Hash`; **the Hash is SHA-256 of the FORM
  chunk**, so stale or partly overwritten copies are detected exactly.
- A save writes a new song and index to free pages; the previous ones survive
  until reused. **Many files hold two verified songs.** Rule adopted: the
  newest is the verified copy whose index is on the **highest page**. It fits
  every case with known order (10 two-copy r-files checked against exports,
  a folders/no-folders pair, and the files mixing an older Reason's copy with
  a 13/14 copy). The header pointer named the older copy in some files and
  the newer in others, so it is not used. *To confirm (question 4 below).*
- Note: an early pass took the last copy in the file and wrongly suggested the
  r-saves lagged by a step. They did not; the fixtures are as described.

### Song structure (RS1300)

Records mostly start `BC <version> 00 00 00`. Times are ticks at **15360 PPQ**
(Reason's MIDI export uses the same). Varints are MSB-first 7-bit (as MIDI).

| Chunk path | Meaning |
| --- | --- |
| `CAT WWWI` | Metadata: `PROGRAMVERSION`, `SONGTEMPO` (milli-BPM), `SONGSIGNATURE`, song length |
| `CAT RS10/CAT DEVL/FORM DEVI/DESC` | Rack device: u32 id at 6, name. **A track's name is its device's name** |
| `CAT SQCT/CAT TTCT/FORM TFFM/CAT TFCT` | Reason 14 track list, inside a `Root` folder; nested `FORM TFFM` are **track folders** (`TFDC` holds the name) |
| `CAT SQCT/CAT TSCT` | Reason 13 track list (no folders) |
| `FORM TRFM/TRDC` | Track: u16 device id at 11, **mute** at 13, kind at 18 (0x0A instrument, 0x0B pattern device) |
| `CAT LNCT/FORM LANF/LANC` | Lane: kind at 5 (0x59 notes, 0x5A pattern, 0x5B/0x5D automation), name, **lane mute** (last byte) |
| `CAT LCCT/FORM LCFM/LCAI` | Clip's Block: 0 = in the song, n = belongs to Block n |
| `FORM SNIF/SNIC` | Clip: u32 start at 5, u32 length at 9, name at 21, **clip mute** after the name, 3 bytes, u32 **loop length** (0 = none), i32 **loop offset** |
| `SNTE` | Notes: u32 count, each (varint delta, added modulo 2^32 and read signed, pitch, velocity, varint length, flags: bit 0 = **muted note**); then u32 controller lane count, each (id: 0x01 mod wheel, 0x0B expression, 0x40 sustain, 0xFF pitch bend, 0xFD unknown; i32 min, max; points) |
| `SAUT` | Automation clip: kind (0 tempo, 2 time signature, others are device parameters), i32 min, max, points |
| `SPTN` | Pattern clip (Redrum, Matrix...): bank/pattern; notes live in the device |
| `SBLK` | Block placement on the Transport track's Blocks lane |
| `FORM SASF` | Audio clip (skip) |
| `CAT SACT/SADC` | Block definitions (`Block 1`...: id, length, name) |

Points (controllers and automation): varint delta, i32 value, 10 bytes. The 10
bytes are zero for straight lines; non-zero values appear in a few songs and
look like a float curve factor (to decode later; Cubase decision 6 applies).

### Musical rules confirmed by the exports

- **Notes are relative to the clip start** and may be negative: splitting or
  trimming a clip leaves hidden notes before its start. A note sounds if it
  starts inside the visible part of its clip.
- **A clip's own end does not cut a sounding note**; the note keeps its length.
- **Overlapping clips on a lane: the later start wins** (ties: later in the
  lane) and cuts notes still sounding where it starts.
- **Looping clips** repeat their first `loop` ticks, starting `loop offset`
  from the clip start (negative after a start trim).
- **Muted notes** (flag bit 0) don't export.
- **Muted clips and muted lanes do not export; muted and soloed tracks do**
  (Reason's export ignores track mute and solo).
- **Tempo:** global tempo (metadata) outside tempo clips; inside, points joined
  by straight lines (a ramp is two points). Exported as 1/32-beat steps.
- **Time signature:** clip-based like tempo; value = denominator << 8 | numerator.
- **Controllers:** points joined by straight lines; exported at 1/32 beat.
- **Pattern clips are not exported** (r21); converting to notes is (r22).
- **Blocks are rendered** at each placement (r24).
- **Blocks:** placements (`SBLK`) name their Block (u16 at 5, 0-based) and an
  i32 offset at 7 (where in the Block the placement starts: a split
  placement's second half has a negative offset). Identical duplicate
  placements occur and play once. The **Blocks switch** is the third byte from
  the end of the sequencer's `TRDC`: off in SelfDef000 (its export plays no
  Block content), on in r24 and dec2024-27-02. Song clips on the same lane
  cover Block content (user: also empty clips, to silence a Block locally).
  r24 and SelfDef000 match their exports. **Open: dec2024-27-02** plays Block
  content on some tracks only at some placements (Arps silent at beats 0-40
  and 128-140, Bassy Swells' second lane never), with no covering clip in the
  saved song.
- **Transport track** is track 0 (named after the hardware interface device in
  the rack; Reason's export calls it `Transport`). Track 1 is the master section.

### Not found yet

- **Track solo:** r20s (solo from the sequencer track) saves nothing different
  from r20. r20x (solo from the mixer) changes one parameter of the track's
  mixer channel device (`X15 Main Mixer Mix Channel`, parameter 2). Mapping a
  mixer channel to its sequencer track is not decoded yet.
- Controller id 0xFD; curve bytes; what decides a Block placement shorter than
  its Block.

### Next: phase 2 (reader)

`core/import_reason.py` mapping songs onto the workspace through the reader
registry, as for Cubase: tracks named from devices, folders kept as path
names, clips with trims and mute, lanes merged into their track with lane mute
applied as clip mute, Blocks rendered, tempo map and signatures from the
Transport clips (ramps as steps, as for Cubase decision 5), controllers
rendered at Reason's density, pattern and audio clips reported as skipped,
pre-13 songs refused with a re-save message.

## Phase 0 result: GO

Probed 2026-11-15 with 62 `.reason` files (Reason 6, 9, 10, 11, 12, 13 and 14,
several songs saved in more than one version) plus r01 (empty) and r02 (one
note), kept locally in the git-ignored `samples/reason-probe/`.

- **Split by the BODY magic, not by file extension.** The container is plain IFF
  in every version, but the song's `BODY` chunk begins with a 128-byte plain
  header whose magic names the generation, and after it:
  - `RS1300` (Reason 13 and 14; 83 copies seen): `CAT RS10` follows in plain
    IFF at +128. **Readable.**
  - `RSN600` (6), `RSN900`/`RSN999` (9/9.5), `RS1000` (10), `RX1100` (11),
    `RS1200` (12; 33 copies seen in all): random-looking bytes follow at +128.
    **Payload encrypted.**
  This matches the Reason Studios statement quoted earlier (encrypted from
  Reason 6 up to 12.5). In a file saved by 13.x the stale second copy may still
  be an old `RS1200` save, which is why one file can show both.
- **Rule applied:** we do not break encryption. A song whose BODY magic is not
  `RS1300` is refused with a clear message ("saved by Reason N; open and re-save
  in Reason 13 or later"). Re-saving works: the `Grandfathered/` songs were
  opened and re-saved in Reason 14 and are all `RS1300`.
- `.rns` songs (Reason 5) are a different format, H = 8.00 from the first byte;
  out of scope. Reason 14's *clipboard* payload is still unexplained and unrelated.
- **Container:** a 52-byte header starting `X15_FILE`, then 256 KiB pages
  (file size = 52 + n x 262144). Header fields (big-endian u32 from offset 8):
  page size 0x40000, 36, 0, then two small counts that vary per file (meaning
  not yet decoded). Unused page space is filled with `0xFE`.
- **Songs are IFF:** at a page start, `FORM` + length + `X15S`, containing a
  metadata `CAT WWWI` (song length, tempo, signature, program version, e.g.
  `14.1.0`), `CAT ApVC`, an `REMB` block, one `BODY` (the song proper, starts
  `RS1300` in Reason 14), and a trailing `Hash`. The BODY is itself IFF:
  `CAT RS10` holding `HEAD`, `GLOB`, `USRI`, `SNGI`, `CAT 45IL`, `CAT DEVL`
  (rack devices, as `FORM DEVI`; this is where the high-entropy bytes are:
  embedded device assets, one chunk of 687 KB in the empty song), `RACK`,
  `CAT CCTL` (cables), then **`CAT SQCT`, the sequencer**: `TRDC` (track data),
  `CAT SACT` (one `FORM SAFM`/`SADC` per automation lane or track record).
- **Two copies.** Superseded by the page-store description in Phase 1 below.
- **A one-note change** rewrites the song body but not the container: r01 and
  r02 have identical headers and metadata layout; only the BODY and `Hash` differ.
- **Sizes:** self-contained songs reach about 100 MB (samples embedded); the
  reader stays path-backed and walks chunk headers without loading it all.

Next: inspector (chunk tree, like `tools/cpr_inspect.py`), identify the current
copy, decode `TRDC`/`SACT`/note clips on r02 and the r03-r25 series, then the
reader. The `.reason` probe set is also the real-world set (SQCT sizes range
from 44 KB upward).

## Phase 0: go/no-go probe (done, kept for the record)

1. Save an **empty song** and the **same song with one note** (r01, r02
   below) from Reason 14.
2. Measure byte entropy across each file and look for structure: container
   magic (RIFF/IFF `FORM`, zip, chunk headers), readable class or chunk names,
   and whether the one-note change is a small local difference or rewrites the
   whole file.
3. **Go** if the files are structured and the note appears as a local change
   (as with Cubase). **No-go** if they are uniformly high-entropy (encrypted or
   compressed-and-encrypted): record the result and close Reason as a native
   format. A plainly compressed file (zlib/deflate that decompresses) is still
   a go.

Only if the probe is a go do the rest of the catalogue and the Cubase-style
phases (inspector, framing, musical mapping, reader) follow.

## Fixture requests (for when Reason work starts)

Reason 14, saved as `.reason` (not self-contained), from a neutral folder,
**Save As** a numbered file per step so each differs from the previous by one
change. Start from an empty song (no template) at 120 BPM, 4/4, with one
instrument (e.g. Europa or Subtractor) on one track. Set the **End marker**
after the last note before each ✱ MIDI export (File ▸ Export MIDI File), and
keep export options the same throughout.

| # | Change from the previous file |
| --- | --- |
| r01 | Empty song, no tracks |
| r02 ✱ | One instrument track, one note clip bars 1–2, one note: C3, velocity 100, bar 1 beat 1, one beat |
| r03 | Move the note to beat 2 |
| r04 | Velocity 64 |
| r05 | Pitch D3 |
| r06 | Length two beats |
| r07 ✱ | Second note E3, velocity 90, bar 2 beat 1, half a beat |
| r08 | Rename the track `Lead` and the clip `Riff` |
| r09 | Save r08 again with no change (per-save noise) |
| r10 ✱ | Move the clip to bar 5 |
| r11 | Trim the clip's start by one beat |
| r12 ✱ | Trim its end by one sixteenth |
| r13 ✱ | Mute the clip |
| r14 ✱ | Unmute it; mute the track |
| r15 ✱ | Unmute; add a second note lane with one clip, then mute that lane |
| r16 ✱ | Unmute the lane; add a mod wheel move and a pitch bend in the first clip |
| r17 ✱ | Tempo automation clip on the Transport track, bars 3-18, at 90 BPM (global tempo 120 applies outside the clip); End marker after bar 18 |
| r18 ✱ | Same clip: points 120 at bar 3 and 90 at bar 5 (a ramp), then 90 to the clip end; End marker after bar 18 |
| r19 ✱ | Time-signature automation clip, 3/4, from bar 5 to bar 23 (bar numbers as shown after the change; global 4/4 outside); End marker after both clips |
| r20 ✱ | Second instrument track with one clip; solo it |
| r21 ✱ | A Redrum (pattern) track with a one-bar pattern (expect: reported as skipped) |
| r22 ✱ | r21 with the pattern track converted to notes in Reason |
| r23 ✱ | A Player device on the first track (expect: reported) |
| r24 ✱ | Blocks: Block 1 (two bars) holds a new clip on one of `Lead`'s two note lanes with one note, A3 velocity 100, block beat 1, one beat; Blocks track enabled, Block 1 placed at bars 25 and 27; song extended, End marker after bar 29 |
| ~~r25~~ | Dropped: r20 uses only factory-library content, so a self-contained save embeds nothing. Large files are covered by real Reason 14 songs (`Sep13-01-02-hallow-01`, 85 MB; `PianoGuitarDrums-v02f(14)-NoEZ`, 100 MB) |

Real-world: two or three of your own songs, each with a MIDI export (End
marker after the last note), as for Cubase.

## Questions for later

1. **Solo:** r20 was saved without its solo. Fixtures requested: r20s (solo
   from the sequencer track's S button) and r20x (solo from the mixer).
2. **Blocks:** do you use Blocks mode? If so, should an import render the song
   as the Blocks track arranges it (current plan, matching Reason's export)?
3. ~~Pattern devices~~: reported as skipped for now; rendering them is on the
   roadmap as a later maybe (user).
4. ~~Which copy Reason opens~~: r04 opens with velocity 64 (user), matching
   the highest-page rule.
5. **Versions:** Reason 13 and 14 read; older songs refused with "re-save in
   Reason 13 or later". Agreed?

## Sources

- [Reason 13 manual: Song File Handling](https://docs.reasonstudios.com/reason13/song-file-handling) (song contents, self-contained songs, MIDI export behaviour)
- [Reason 13 manual: Sequencer Functions](https://docs.reasonstudios.com/reason13/sequencer-functions) (note lanes, clip mute, pattern lanes, Blocks, Transport track)
- [Archive Team: Propellerhead Reason Project File](http://fileformats.archiveteam.org/wiki/Propellerhead_Reason_Project_File)
- Encryption change: KVR thread cited in the [direct DAW import plan](direct-daw-import.md#reason-reason)
- Our clipboard capture: [INTEROP_FINDINGS](../INTEROP_FINDINGS.md#reason-14-proprietary-compressed-or-encrypted)
