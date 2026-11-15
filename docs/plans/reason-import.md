# Plan: native Reason song import (`.reason`), feasibility

Status: **Phase 0 probe done: GO** (2026-11-15). Song files are plain,
structured IFF, not encrypted (see [Phase 0 result](#phase-0-result-go)). The
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
| **Transport track**: tempo automation lane and time-signature automation lane | The tempo map; ramps likely (automation curves) |
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

## Phase 0 result: GO

Probed 2026-11-15 with 62 `.reason` files (Reason 6, 9, 10, 11, 12, 13 and 14,
several songs saved in more than one version) plus r01 (empty) and r02 (one
note), kept locally in the git-ignored `samples/reason-probe/`.

- **Not encrypted.** The "encrypted from Reason 6 to 12.5" claim does not hold
  for song files: every `.reason` from Reason 6 to 14 has the same container and
  parses. (Reason 14's *clipboard* payload is a different matter and stays
  unexplained.) `.rns` songs (Reason 5) are a different format, H = 8.00 from the
  first byte (compressed or encrypted); out of scope.
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
- **Two copies.** Most files hold two generations of the song at different
  pages (journalled saves), usually of equal or near-equal size. Some copies
  fail to walk (a stale, partly overwritten earlier generation). The reader
  must choose the current copy; the header counts are the first thing to
  decode for that.
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
| r17 ✱ | Tempo automation: 90 BPM from bar 3 (a step) |
| r18 ✱ | Make it a ramp from bar 3 to bar 5 |
| r19 ✱ | Time signature 3/4 at bar 5 |
| r20 ✱ | Second instrument track with one clip; solo it |
| r21 ✱ | A Redrum (pattern) track with a one-bar pattern (expect: reported as skipped) |
| r22 ✱ | r21 with the pattern track converted to notes in Reason |
| r23 ✱ | A Player device on the first track (expect: reported) |
| r24 ✱ | Blocks: one Block with the first clip, placed twice on the Blocks track |
| r25 | A self-contained save of r20 (size and structure only) |

Real-world: two or three of your own songs, each with a MIDI export (End
marker after the last note), as for Cubase.

## Questions for later

1. **Blocks:** do you use Blocks mode? If so, should an import render the song
   as the Blocks track arranges it, or import only clips placed directly in
   the song?
2. **Pattern devices and Players:** how often do your songs rely on Redrum,
   Matrix or Players without converting to notes? This decides whether
   "reported as skipped" is acceptable.
3. **Versions:** Reason 14 only at first, with a clean "unsupported version"
   message for others?

## Sources

- [Reason 13 manual: Song File Handling](https://docs.reasonstudios.com/reason13/song-file-handling) (song contents, self-contained songs, MIDI export behaviour)
- [Reason 13 manual: Sequencer Functions](https://docs.reasonstudios.com/reason13/sequencer-functions) (note lanes, clip mute, pattern lanes, Blocks, Transport track)
- [Archive Team: Propellerhead Reason Project File](http://fileformats.archiveteam.org/wiki/Propellerhead_Reason_Project_File)
- Encryption change: KVR thread cited in the [direct DAW import plan](direct-daw-import.md#reason-reason)
- Our clipboard capture: [INTEROP_FINDINGS](../INTEROP_FINDINGS.md#reason-14-proprietary-compressed-or-encrypted)
