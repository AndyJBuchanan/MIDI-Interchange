# Cubase project file format (`.cpr`)

A baseline of what this project knows about Steinberg Cubase's native project file, written 2026-11-22. It is for a developer who has never seen the project. It describes the **file format**. How the format becomes MIDI is covered only briefly, in section 6.

Everything here comes from files the project owner saved, from Cubase's own MIDI and DAWproject exports of some of them, and from the decoding code. No Cubase code was decompiled, and no Steinberg documentation of the format exists or was used.

## How to read this document

Every statement carries one of three labels:

- **VERIFIED**: shown by code that decodes the fixtures, by a test, or by a check run for this document. The source is named.
- **INFERRED**: a reasonable reading of the evidence that has not been checked directly. What it rests on is named.
- **UNKNOWN**: not established.

Offsets are decimal unless written `0x…`. "Archive offset" means a byte offset from the start of an archive body (section 2.2), not from the start of the file. All multi-byte integers are big-endian unless stated otherwise.

### Sources

| Source | What it is |
| --- | --- |
| `midi_interchange/core/cpr_format.py` | Container, object and field decoding (the reference implementation) |
| `midi_interchange/core/import_cubase.py` | Maps decoded data onto MIDI tracks and clips |
| `tools/cpr_inspect.py` | Research CLI: `roots`, `tree`, `classes`, `notes`, `timeline`, `diff`, `hex` |
| `tests/test_cpr_inspect.py`, `tests/test_import_cubase.py` | Regression tests pinning the findings to fixtures |
| `docs/plans/cubase-import.md` | The investigation record and decisions (phases 1 to 4) |
| `docs/DAWPROJECT_DITTY_FINDINGS.md`, `docs/DAWPROJECT_OTHER_PAIRS_FINDINGS.md` | Cubase's MIDI and DAWproject exports compared |
| `docs/plans/mirror-mode.md`, "Step 0 results" | How Cubase writes the file on save |
| Checks run for this document | Read-only Python against the fixtures with `cpr_format`. They are flagged "(check, 2026-11-22)" |

### Fixtures

56 Cubase containers were examined: 53 `.cpr` files under `samples/` and 3 Cubase auto-save `.bak` files in `samples/project-cubase-phases/Verify/Auto Saves/`.

| Fixture | Cubase | Container | What it shows | Ground truth beside it |
| --- | --- | --- | --- | --- |
| `project-cubase-phases/Tier 1/Cubase15/c01`–`c09`, `c02-1` | 15.0.30 | RIF2 | Empty project; one note edited step by step; display offset | `c02.midi`, `c07.midi` |
| `Tier 1/Cubase16/` (same steps) | 16.0.5 | RIF2 | The same steps in 16 | `c02.midi`, `c07.midi` (byte-identical to the 15 exports) |
| `Tier 2/Cubase16/c10`–`c18is` | 16.0.5 | RIF2 | Part move, trims, mute, copies, MIDI track, folders, solo, instrument stack | MIDI exports for c10, c12–c14, c16–c18, c18is |
| `Tier 3/Cubase16/c19`–`c26` | 16.0.5 | RIF2 | Tempo jump and ramp, 3/4, markers, CC1, pitch bend, program change, linear time base | MIDI exports for c19–c22, c24–c26 |
| `project-sets/Ditty-04-Macbook.cpr` | 15.0.21 | RIFF | 176 parts, controllers, pitch bends, chord track, MIDI inserts | `.mid` and `.dawproject` (exported later from 15.0.30, see caveat) |
| `project-sets/GA & Padshop 2-(alt instr 2)-01.cpr` | 15.0.30 | RIFF | 182 parts, muted notes, tempo ramps, MIDI Modifiers transpose, chord track | Whole-song `.mid`, range `.dawproject.midi`, `.dawproject` |
| `project-sets/indy-001x.cpr` | 15.0.30 | RIF2 | Range markers, Pattern Editor parts | `.mid`, `.dawproject` |
| `Verify/argontest003.cpr` | **13.0.41** | RIFF | Real project from Cubase 13 | None |
| `Verify/Scaler3Test-001(14).cpr` (local, git-ignored) | **14.0.20** | RIF2 | Cubase 14 project with no MIDI parts | None |
| `Verify/BBCSO_Woodwinds101-App01-MacBook.cpr` (local) | 15.0.10 | RIFF | 25 MB; expression-map articulations; markers declared past 16 MB | `.midi` export |
| `Verify/Beat003vs.cpr` | 15.0.30 | RIF2 | Omnivocal lyric properties; varied mixer tail | None |
| `Verify/orchestral-import-test-01.cpr` (local) | now 16.0.5 (see section 8) | RIFF | 173 MB, mostly plug-in state; one out-of-range aftertouch | None |
| `Verify/seqtest-001.cpr` | 16.0.5 | RIF2 | Drum and melodic Pattern Editor parts only | None |
| `Verify/vocalfun001(16).cpr` | 16.0.5 | RIF2 | Drum Track, Omnivocal, score lyrics, ARA track, chord track | None |
| `_archive/…` (`GA … -01x.cpr`, `delete-me-reimport.cpr`) | 15.0.30, 16.0.5 | RIFF, RIF2 | A re-save of GA; a scratch file | GA re-save has `.mid`, `.dawproject` |
| `Verify/Auto Saves/BBCSO…-X-0n-(…).bak` (3) | 16.0.5 | RIFF | Cubase auto-saves of the BBCSO project | None |

**Caveat (from the plan, "Fixture caveats").** The three `project-sets` projects were saved before their exports were made, so a mismatch against those exports is not by itself evidence of a decoding fault.

---

## 1. Overview and versions

### 1.1 What is in a `.cpr`

A `.cpr` is a single file with a RIFF-like outer container (section 2.1). Inside it is a fixed series of named **archives**, each a serialised object graph of Cubase's internal C++ classes. **VERIFIED** (`read_container`, all 56 containers).

| Archive | Root class | Holds | Read by us |
| --- | --- | --- | --- |
| `Version` | `PAppVersion` | Application name, version, build date, platform, text encoding, language | Yes (version check) |
| `Arrangement1` | `PArrangement` | The song: tracks, parts, MIDI events, tempo, signatures, markers, chord track. Also mixer channels with plug-in states, automation, the audio pool and paths, drum maps, expression maps, score settings | Yes (MIDI and timing only) |
| `ComputerGuid` | `CmString` | An identifier of the saving computer: a GUID string with a `!` prefix. Two distinct values appear across the fixtures | No |
| `Devices` | `FAttributes` | Device and plug-in setup (plug-in names and UIDs, buses, panners, Quick Controls) | No |
| `WindowLayouts`, `ProjectLayouts` | `UWindowLayout`, `FAttributes` | Window sizes, zoom, workspaces, tool settings | No |
| `Metadata` | `StMedia::PAttributes` | Sample format, rate and size; `MediaAuthor`; `MediaProjectName`; `MediaType` = `Prj`; signature; tempo | No |
| `Previewdata` (optional) | `StMedia::PAttributes` | `ProjectPreview`: an `AudioMemoryStreamPersistent` audio preview, about 960 KB | No |

- **VERIFIED** for the archive list and order, by `cpr_inspect.py roots` on all 56 containers. `Previewdata` is present in Ditty, GA, indy, BBCSO, Beat003vs, orchestral and the auto-saves. It is absent from every tier file, argontest003, Scaler3Test, seqtest and vocalfun.
- **VERIFIED** for the contents column by the strings in each archive (check, 2026-11-22). `MediaAuthor` and `MediaProjectName` are empty strings in the fixtures checked (c08, Ditty, argontest003, Scaler3Test, orchestral), so `Metadata` does **not** give a song title in practice. The plan's open item "Metadata: possibly the song title; to check" is answered for these files.
- **INFERRED** for `ComputerGuid`, from the two distinct values: one is shared by Ditty, the tier files and orchestral, and the other by argontest003 and Scaler3Test.

### 1.2 Versions observed

| Cubase | Fixtures | Container | Decoded by the format code | Accepted by the reader |
| --- | --- | --- | --- | --- |
| 13.0.41 | argontest003 | RIFF | Yes: no decode problems, 1,513 notes in unshared parts, tempo, signature, markers, track flags (check, 2026-11-22) | **No** |
| 14.0.20 | Scaler3Test | RIF2 | Walks; it has no MIDI parts, so notes can't be checked | **No** |
| 15.0.10, 15.0.21, 15.0.30 | BBCSO; Ditty; GA, indy, Beat003vs, tier 1 (15) | RIFF and RIF2 | Yes | Yes |
| 16.0.5 | Tiers 1–3 (16), seqtest, vocalfun, orchestral (re-saved), auto-saves | RIFF and RIF2 | Yes | Yes |

**VERIFIED** by `cf.app_version` and `cpr_inspect.py notes` / `timeline` (check, 2026-11-22), and by `SUPPORTED_MAJOR = (15, 16)` in `import_cubase.py`.

### 1.3 Class versions per Cubase version

Each class declaration carries a u16 version (section 2.4). The table gives the versions seen for the classes that matter. Classes not listed have the same version everywhere they occur. **VERIFIED** by a census of every class declaration in every fixture (check, 2026-11-22).

| Class | 13.0.41 | 14.0.20 | 15.0.x | 16.0.5 |
| --- | --- | --- | --- | --- |
| `PArrangement` | 3 | 4 | 4 | 5 |
| `PArrangeSetup` | 8 | 8 | 8 | 9 |
| `MInstrumentTrackEvent`, `MMidiTrackEvent` | 3 | 4 | 4 | 4 |
| `MInstrumentTrack` (mixer channel) | 9 | 9 | 10 | 11 |
| `MMidiTrack` (mixer channel) | 7 | 7 | 7 | 8 |
| `MTempoTrackEvent` | 2 | 3 | 3 | 3 |
| `MDrumTrackEvent` | – | – | – | 4 |
| `MRangeMarkerEvent` | – | – | 15.0.30 only | 0 |
| `MChordTrackEvent`, `MChordEvent`, `MScaleEvent`, `ChordData` | – | – | 0, 0, 0, 3 | same |
| `MMidiPartEvent` 2, `MMidiPart` 2, `MMidiNote` 1, `MMidiEvent` 2, the six other MIDI event classes 0, `MSignatureTrackEvent` 3, `MMarkerEvent` 0, `MFolderTrack` 0, `MTrackEvent` 2, `MRoot` 6 | same in every version where present | | | |

A dash means not seen in our files, which is not the same as absent from that version.

### 1.4 Why Cubase 13 and 14 are refused

- **VERIFIED**: the refusal is a version check, not a decoding failure. `import_cubase` reads `Version x.y.z` from the `Version` archive and refuses any major version outside `(15, 16)` with "Cubase N projects are not supported; supported: Cubase 15, 16" (`test_unsupported_version_fails_cleanly`, `test_verify_cubase14_rejected_until_validated`).
- **VERIFIED**: the plan's decision 2 (2026-11-15) limits support to 15 and 16 until real-world 14, 13 and 10.5 projects are checked. Cubase 14 stays unsupported "until a project with parts is checked" (plan, spot-test fixes).
- **VERIFIED (check, 2026-11-22)**: Cubase 13's argontest003 decodes completely with the current code. Its class versions differ from 15's (table above), but every field the reader uses decoded plausibly: part windows, mute flags, notes, controllers, track flags, tempo, signature.
- **UNKNOWN**: whether the decoded values are *correct* for 13, because there is no Cubase MIDI export of argontest003 to compare against. One oddity: its two markers have empty names (ids 4 and 3, both at tick 0). This may be genuine or a layout difference. The tempo track's single point (102 BPM) also differs from its trailing tempo field (120); see section 4.8.

### 1.5 RIFF or RIF2

- **VERIFIED**: both container variants occur in 15.0.30 and in 16.0.5. Size doesn't select the variant: every tier file is RIF2, even the 100 KB empty project, and the 173 MB orchestral file is RIFF (`roots` on all files; plan, "What the fixtures already show").
- **INFERRED** (medium confidence): a project keeps the variant it was created with. The orchestral project was re-saved by 16.0.5 and stayed RIFF. The BBCSO project (15.0.10, RIFF) produced 16.0.5 auto-saves that are RIFF. The GA re-save by 15.0.30 stayed RIFF. Projects created fresh for the tiers in 15.0.30 and 16.0.5 are RIF2, as is the Cubase 14 file. The Cubase 13 file is RIFF. That fits "new projects are RIF2 from some version (14 or earlier); older projects stay RIFF", but no fixture shows a project's creation version.

### Confidence and evidence (section 1)

High for the archive list, versions observed and class versions: these come directly from all fixtures. The reason older versions are refused is certain (it's policy in the code). Whether 13 and 14 decode *correctly* is unknown. The RIFF/RIF2 selection rule is a hypothesis.

---

## 2. The container

### 2.1 File header

| Offset (RIFF) | Offset (RIF2) | Width | Field | Notes |
| --- | --- | --- | --- | --- |
| 0 | 0 | 4 | Magic `RIFF` or `RIF2` | ASCII |
| 4 | 4 | 4 (RIFF) / 8 (RIF2) | Size | Big-endian. **Equals file size − 12 (RIFF) or − 16 (RIF2)**: it counts the bytes *after* the form type, unlike standard RIFF |
| 8 | 12 | 4 | Form type `NUND` | ASCII |
| 12 | 16 | … | First chunk | |

- **VERIFIED**: magic, form type and widths come from `is_cubase_project` and `read_container` (`cpr_format.py` lines 80–119).
- **VERIFIED (check, 2026-11-22)**: the size semantics hold in all 56 containers.
- Our reader does not check the size field.
- **VERIFIED**: the whole file is big-endian, unlike standard little-endian RIFF.

Example headers:

- c01 (16.0.5): `52 49 46 32 | 00 00 00 00 00 01 95 C0 | 4E 55 4E 44`. The size is 103,872 and the file is 103,888 bytes.
- Ditty: `52 49 46 46 | 00 83 62 BE | 4E 55 4E 44`. The size is 8,610,494 and the file is 8,610,506 bytes.

### 2.2 Chunks

After the header comes a flat run of chunks, with no nesting at this level:

| Field | Width |
| --- | --- |
| Chunk id (`ROOT` or `ARCH`) | 4 |
| Body size | 4 (RIFF) / 8 (RIF2), big-endian |
| Body | size bytes |

- **No padding.** Chunks follow each other directly, even after odd sizes (for example, c01's 141-byte `Version` body). **VERIFIED**: `read_container` steps exactly by the size and reaches the file end in all 56 files, and it raises an error on any other id.
- **Pairs.** Each `ROOT` chunk names the `ARCH` chunk that follows it. **VERIFIED** (`read_container`).
- **ROOT body.** Two strings, each a u32 length followed by that many bytes, with **no terminator**: the archive name, then its root class name. For example, c01's first `ROOT` has size 26: `00 00 00 07 "Version" 00 00 00 0B "PAppVersion"`. **VERIFIED** by the hex dump of c01 (check, 2026-11-22). The code comment saying ROOT names "end `\0`" is slightly wrong (section 8), but `_pstring` copes either way.
- **ARCH body.** One archive: a serialised object stream (section 2.4). The first object fills the archive exactly. **VERIFIED**: `cpr_inspect.py tree` reports "top-level bytes outside objects: 0" for c02, c23 and the others checked.

### 2.3 Strings

Four string forms occur. **VERIFIED** by hex dumps (check, 2026-11-22) and by `_pstring`, `_bomstring_at` and `_cstring_at`.

| Form | Layout | Where |
| --- | --- | --- |
| Bare | u32 n · n bytes, no terminator | `ROOT` bodies |
| C string | u32 n · (n−1) bytes · `00` | Class names in object tags; `Version` archive fields; MIDI port names; ASCII names in named-record trees (section 2.5) |
| BOM string | u32 n · UTF-8 · `00` · `EF BB BF` (n counts all of it) | User-facing text in the arrangement: track, part, folder and marker names; `MediaType` value `Prj` |
| Empty | u32 0 | Empty values in named records (`MediaAuthor` in c08) |

- Text is UTF-8. **VERIFIED**: the `Version` archive declares `UTF-8`, and port names with non-ASCII characters decode in the synthetic test `test_state_flags_found_by_structure_not_port_name`.
- **INFERRED**: the trailing UTF-8 BOM marks a Unicode (user) string, as opposed to an ASCII identifier. Both forms appear with the same named-record type code.

### 2.4 The object stream

This is the binary serialisation used inside `ARCH` bodies. The **tag width W** is 4 in RIFF files and 8 in RIF2 files. **VERIFIED** (`Walker`, `cpr_format.py` lines 146–254; plan, "Object framing"; all fixtures).

| Element | Layout (RIFF, W = 4) | Layout (RIF2, W = 8) | Meaning |
| --- | --- | --- | --- |
| BASE | `FF FF FF FE` · u32 nameLen · name`\0` · u16 version | `FF`×7 `FE` · same | Declares a base class of the next NEW class. No body. A run of BASE tags lists the parents, nearest first |
| NEW | `FF FF FF FF` · u32 nameLen · name`\0` · u16 version · u32 length · body | `FF`×8 · same · **u64** length · body | First object of a newly declared class |
| REF | u32 (`0x80000000` \| declOffset) · u32 length · body | u64 (`0x8000000000000000` \| declOffset) · u64 length · body | Object of an already declared class |
| Back-reference | u32 identity (top bit clear) | u64 identity | Refers to an object already written (see below) |

Field widths: name length is always u32, version always u16, and object lengths are W bytes. **VERIFIED.**

How the pieces fit together:

- **Class identity.** `declOffset` is the archive offset of the class's declaration tag: the NEW tag, or the BASE tag when the class was first declared as a base.
  - **VERIFIED** in c07 (16): every `MMidiNote` REF has target `0x9DA`, the offset of its declaration (`test_class_refs_are_declaration_offsets`).
  - **VERIFIED** in GA: `MMidiNote` is first declared as a base of `MScaleEvent` and later referenced (plan).
  - **VERIFIED** in c02: the track's `MListNode` REF points at offset 231, where `MListNode` is declared as a base in front of `MTrackList` (check, 2026-11-22).
  - Target 0 never occurs as a real reference (plan).
- **REF tags past 16 MB.** Because the tag holds an offset, a class declared past 16 MB gives REF tags starting `0x81` or higher, not `0x80`. **VERIFIED**: BBCSO's markers are declared at 23 MB, and missing this lost 7 of its 8 markers until the scanner accepted any byte from `0x80` up (`TAG_START`; `test_verify_bbcso_score_symbols_and_named_flags_tail`).
- **Object identity.** An object's identity is the archive offset of its **length field**: just after the name and version for a NEW object, at tag + W for a REF. **VERIFIED** (`Walker.by_identity`; shared copies in c16, section 4.5; node headers, section 4.2).
- **Inline on first reference.** A field that refers to an object holds either the whole object (a NEW or REF tag, length and body) the first time that object is written, or a W-byte back-reference after that.
  - **VERIFIED** for part contents in `MMidiPartEvent`: an inline `MMidiPart`, or a back-reference for a shared copy (c15, c16).
  - **VERIFIED** for the tempo and signature references in node headers: in all 52 fixtures of 30 MB or less, the `MTempoTrackEvent` object is serialised inline exactly at the tempo-reference field of the first node header that refers to it, and back-referenced everywhere else (check, 2026-11-22).
  - **INFERRED**: this is the general rule for object-valued fields.
- **Nesting.** Lengths nest exactly: children lie wholly inside their parent's body, and `PArrangement` fills `Arrangement1`. **VERIFIED.**
- **Bodies.** A body mixes class-specific scalar fields with child objects. There is no per-field framing, so a body can't be parsed field by field without knowing its class. **VERIFIED** (plan, phase 1). Our walker finds children by scanning for byte positions that parse as valid tags whose lengths fit inside the parent (`Walker.walk`, `try_object`). It runs the regex `TAG_START` over bytes `0x80`–`0xFF`, and validates names against `NAME_RE` (`[A-Za-z_][A-Za-z0-9_:]{0,95}\0`).
- **False tags.** Named records inside named-record trees (section 2.5) can parse as NEW tags. Seen: `Name`, `Max`, `Title`, `SummingMode`, `Start1`, `flags`, `staveIndex`, `RepeatRate` and others. So the walker reports some "classes" that are really record names. **VERIFIED**: the plan, and the class census, which lists them. A reader must descend by structure where it can, and treat scan results as candidates.

The `Version` archive as a complete example (c01, 16.0.5, RIF2):

```
FF FF FF FF FF FF FF FE  00 00 00 09 "CmObject\0"  00 00          BASE CmObject v0
FF FF FF FF FF FF FF FF  00 00 00 0C "PAppVersion\0" 00 02         NEW PAppVersion v2
00 00 00 00 00 00 00 54                                           length 84
00 00 00 07 "Cubase\0"  00 00 00 0F "Version 16.0.5\0"
00 00 00 0C "Oct 26 2026\0"  00 00 01 90  00 00 00 09 "MAC64 LE\0"
00 00 00 00  00 00 00 06 "UTF-8\0"  00 00 00 03 "us\0"
```

`PAppVersion` body: C string application · C string `Version x.y.z` · C string build date · u32 `0x190` (400 in every file, meaning **UNKNOWN**) · C string platform · u32 0 · C string encoding · C string language. **VERIFIED** (hex of c01, Ditty, argontest003, Scaler3Test, orchestral). `app_version` finds the strings by regex rather than by this layout.

### 2.5 Named-record trees (attribute form)

A second encoding sits inside `FAttributes` objects, `StMedia::PAttributes` archives and many object bodies: mixer records, MIDI Modifiers, pattern data, expression maps, score attributes. It is self-describing.

| Element | Layout |
| --- | --- |
| Record | u32 nameLen · name`\0` · u16 type · value |
| type `0x0001` | i64 |
| type `0x0004` | f64 |
| type `0x0008` | string: u32 n · bytes (a C string or a BOM string); n = 0 for empty |
| type `0x0002` | container: u16 sub-kind · u32 count · entries. Sub-kind `0x0006` = a struct of named records. Sub-kind `0x00C9` = a list of class-named objects |
| Class-named object (an entry) | u16 `0x0014` · u32 nameLen · class name`\0` (may start with `!`) · u64 identity · u32 record count · records |

- **VERIFIED** for the instances decoded by hand (check, 2026-11-22):
  - c08's whole `Metadata` archive. Example: `AudioSampleRate` is type 4, f64 44100.0. `MusicalTempo` is f64 120.0. `MusicalSignature` holds a `CmRational` with `Numerator` and `Denominator`.
  - GA's MIDI Modifiers block. Example: `Transpose` · `00 02` · `00 06` · `00 00 00 03` · records `Value` (i64 24), `Min` (i64 −127), `Max`.
- **INFERRED**: the general grammar, from those instances.
- **INFERRED**: the u64 identities are in-memory addresses. They change between two saves with no edits (section 5.3), they are 8 bytes even in RIFF files (GA), and they step by `0x50` between consecutive records in c08's `Metadata`.
- The reader uses this form only through fixed byte patterns: `SoloFlag`, MIDI Modifiers parameters, the folder `Solo` property. **VERIFIED** (`cpr_format.py` lines 637–697).

### 2.6 Tagged property lists

MIDI events, chord events, track events and the tempo and signature tracks carry a compact property list. **VERIFIED** (`_props`, `cpr_format.py` lines 312–344, and the census below).

| Field | Layout |
| --- | --- |
| Count | u16 |
| Each property | 4-byte key · u16 type · value |

- **Key.** A FourCC stored **byte-reversed**: `OffV` is stored as the bytes `VffO`, `Lock` as `kcoL`, `Solo` as `oloS`. Some keys are not text (hashes, high-bit bytes). **VERIFIED.** **INFERRED**: these are 32-bit constants written little-endian inside an otherwise big-endian file.
- **Type.** The low byte is the kind; higher bits look like flags.

| Kind (low byte) | Value | Seen with type words |
| --- | --- | --- |
| `0x01` | i64 | `0x0001`, `0x0801` (`Lock`) |
| `0x04` | f64 | `0x0004` |
| `0x02` | an embedded NEW/REF object | `0x0002` (`cuOb`), `0x0022` (`ScAr`, `TVCi`) |
| `0x08` | an embedded object (a `CmString`), or for some keys a plain BOM string | `0x0008`, `0x0408` |

The kind numbers 1, 4, 8 and 2 match the named-record types in section 2.5. **INFERRED**: one type system underlies both.

### 2.7 Compression, encryption, checksums

- **Compression and encryption: none at container or archive level.** **VERIFIED**: class names, track names and strings are readable in place, and every archive walks with no unexplained bytes at the top level. **UNKNOWN**: the format of opaque blobs inside objects, such as VST plug-in state chunks in mixer channels (the reader never opens them).
- **Checksums: none found.** **INFERRED** with high confidence: between c08 and c09, saved twice with no change, the only differences are four named-record identities, the project's own file name (`c08.cpr` → `c09.cpr` in an `FNPath`), a GUID string in `WindowLayouts`, and identities in `ProjectLayouts` and `Metadata` (check, 2026-11-22). A checksum over the content would also have changed. The reader verifies nothing, and Cubase-saved files read back unchanged.

### 2.8 How a loader walks the file

The reader's procedure (`import_cubase.import_cubase`, `cpr_format.walk_archive`). **VERIFIED.**

1. Refuse files over 256 MB (`MAX_CPR_BYTES`), then read the file once.
2. Check the magic (`RIFF`…`NUND` at 8, or `RIF2`…`NUND` at 12). Set W to 4 or 8.
3. Walk the `ROOT`/`ARCH` chunks. Keep each archive's name, root class and body.
4. Read `Version` and refuse versions other than Cubase 15 or 16.
5. For `Arrangement1`, first register **every** class declaration with a regex pass over the BASE/NEW tags (`declare_all`), so that REF tags resolve even inside bodies that are skipped.
6. Walk the object tree by tag scanning, **without** descending into the mixer-channel objects `MInstrumentTrack`, `MMidiTrack` and `MAudioTrack` (`READER_SKIP`). They hold plug-in states: the orchestral project's arrangement is 172 MB, mostly these. Skipping cut its load from 3.5 s to 0.18 s with identical results (`test_skipping_mixer_bodies_does_not_change_imports`).
7. Find the objects of interest by class name anywhere in the tree, then decode their bodies with class-specific layouts (sections 4.x).

### Confidence and evidence (section 2)

High for the header, chunks, strings, the object framing, identities and back-references: they are pinned by tests and decode 56 containers. Medium for the named-record grammar, which comes from hand-decoded instances. The absence of a checksum is inferred from a no-change save diff.

---

## 3. Object and class catalogue

"Decoded" means the reader decodes the fields named. "Located" means the reader finds the object but treats its body as opaque or reads one value by pattern. Versions are given as 13/14/15/16 where they differ. Bases are as declared in the stream (section 2.4).

| Class (bases) | Where | Holds | Status | Evidence |
| --- | --- | --- | --- | --- |
| `PArrangement` (`GDocument`, `CmObject`) v3/4/4/5 | Root of `Arrangement1` | Everything below | Walked | `tree`, all files |
| `MRoot` (`MGroupEvent`, `MPartEvent`, `MEvent`, `CmIDLink`) v6 | Child of `PArrangement` | The top `MTrackList` and project-wide objects | Walked | `tree` c02, c23 |
| `MTrackList` (`MListNode`, `MDataNode`) v0 | Under `MRoot`; inside each folder | Ordered track events; body starts with a name | Walked; folder name read | `folder_name` |
| `MListNode` v0 | First child of every track event | Node header (section 4.2), then the track's timeline events (parts, markers) | Name and time base decoded | `track_name`, `track_time_base_linear` |
| `MTrackEvent` v2 | Base class of track events | Common track-event fields | Base only | census |
| `MFolderTrack` (`MTrackEvent`) v0 | In a track list | A folder or an instrument stack: its own `MTrackList`, a `Solo` property, an `MTrack` | Name, nesting and state flags decoded | `folder_path`, `folder_state_flags`; c18, c18fm, c18is |
| `MInstrumentTrackEvent` (`MMidiTrackEvent`) v3/4/4/4 | In a track list | Instrument track: `MListNode`, editor settings, `PChordTrackParam`, mixer channel `MInstrumentTrack`, automation | Name, parts, flags and MIDI Modifiers decoded | tests, all tiers |
| `MMidiTrackEvent` v3/4/4/4 | In a track list | MIDI track; mixer channel `MMidiTrack` | As above | c17, argontest003 |
| `MDrumTrackEvent` (`MInstrumentTrackEvent`) v4 (16 only) | In a track list | Cubase 16 Drum Track | Name and flags decoded; its pattern part is skipped | `test_verify_drum_track_is_a_track_and_lyric_project_imports` |
| `MInstrumentTrack` (`MMidiTrack`) v9/9/10/11 | Last large child of an instrument track event | Mixer channel: inserts, plug-in state, ports, channel state flags | Flags located by structure (section 4.3) | `state_flags_offset`; every fixture track |
| `MMidiTrack` v7/7/7/8 | Child of a MIDI track event | Mixer channel of a MIDI track: output port, input port, a u32, flags | Flags located by structure | c17, c17m, argontest003 |
| `MDeviceTrackEvent` v0 | In the I/O folder | Input/output channel tracks (for example "Stereo Out") | Not read | `tree` c02 |
| `MMidiPartEvent` v2 | In a track's `MListNode` | A part placed on the timeline: flags, start, length, content offset, contents | Decoded | `part_event_info`; c10–c16 |
| `MMidiPart` (`MPartNode`) v2 | Inside `MMidiPartEvent`, or back-referenced | Part contents: name, node header, event-class table, events | Decoded (musical time); linear layout found, not in the reader | `decode_part_events`; section 4.6 |
| `MMidiEvent` v2 | Base class | Common MIDI event fields | Base | census |
| `MMidiNote` (`MMidiEvent`) v1 | In parts | Note | Decoded | tier 1 tests |
| `MMidiController` v0 | In parts | Control change | Decoded | c24, c25, Ditty |
| `MMidiPitchBend` v0 | In parts | Pitch bend | Decoded | c24, c25 |
| `MMidiProgramChange` v0 | In parts | Program change | Decoded | c25 |
| `MMidiAfterTouch` v0 | In parts | Channel pressure | Decoded | orchestral: 1,853 events (check, 2026-11-22) |
| `MMidiPolyPressure` v0 | In parts | Poly pressure | Assumed layout, never seen | `DATA_BYTES` comment |
| `MMidiSysex` v0 | In parts | SysEx | **Not decoded** (variable length); decoding stops at the first one | `parse_event_body` raises; plan |
| `MScoreEvent` v1 | In parts, as framed objects | Score symbols and text, including expression-map articulation texts and Cubase 16 lyrics (`ScLyricAttrib`) | Stepped over; layout partly found (section 4.14) | BBCSO 669, vocalfun 69 |
| `MParamEventCurveRationalBezier` (`MParamEventCurveBase`) v0 | In controller and pitch-bend property `cuOb` | The curve shape between two stored points | Detected; not rendered | c24–c26, Ditty |
| `CmAttribCollection`, `ScAttrib`, `ScTextAttrib`, `ScLyricAttrib`, `ScCommonAttrib` | In property `ScAr` of notes, score events and chord events | Score attributes: articulations, lyrics (Omnivocal), chord data | Not decoded | Beat003vs, BBCSO, vocalfun |
| `MTempoTrackEvent` v2/3/3/3 | Inline at the first node header that refers to it (section 4.2) | Tempo points and ramps, trailing tempo, properties | Points decoded | `tempo_points`; c19, c20, GA |
| `MSignatureTrackEvent` v3 | Inline next to the tempo track | Time-signature points; an `FAttributes` child | Points decoded | `signature_points`; c21 |
| `MTimeSignatureEvent` | Only as a class name inside the signature track's `FAttributes` tree | Signature events in attribute form | Not read | check, 2026-11-22 (indy) |
| `MMarkerTrackEvent` v0 | In a track list | Marker track; `MListNode` holds markers | Decoded via markers | c22, c23 |
| `MMarkerEvent` v0 | In the marker `MListNode` | Plain marker | Decoded | c22, BBCSO |
| `MRangeMarkerEvent` (`MMarkerEvent`) v0 | Same | Cycle (range) marker | Decoded | c23, indy |
| `MRegionMarker` | One file | **UNKNOWN** | Not read | census |
| `PArrangeSetup` v8/8/8/9 | Child of `PArrangement`, after `MRoot` | Arrangement settings, including the display bar offset at body + 84 | One field decoded | `display_bar_offset` |
| `MChordTrackEvent` (`MTrackEvent`) v0 | In a track list (15+) | Chord track | Detected; reported as skipped | GA, Ditty, Beat003vs, BBCSO, vocalfun |
| `MChordTrackNode` v0 | First child of `MChordTrackEvent` | Node header, then chord and scale events | Not read | GA `tree` |
| `MChordEvent` v0 | In `MChordTrackNode` | A chord: note-like event with a `ChordData` attribute | Partly understood (section 4.12) | check, 2026-11-22 |
| `ChordData` (`ScAttrib`) v3 | In the chord event's `ScAr` | Chord type data | Hypothesis only | check, 2026-11-22 |
| `MScaleEvent` (`MMidiNote`, `MMidiEvent`) v0 | In `MChordTrackNode` | Scale events (chord track scale lane) | Not decoded | GA |
| `MPatternEvent` v0 (15.0.30+) | In drum and pattern tracks | A Pattern Editor part: named records `Start`, `Length`, `priority`, `vertical`, `patternNr` | Detected; reported as skipped | indy 40, seqtest 2, vocalfun 1 |
| `PatternEditorProjectData` | Arrangement | Last scale and root key | Not read | plan, phase 4 |
| `AXtProjectTrackEvent` (15+) | Track list | ARA track (for example Synthesizer V); the notes live in the plug-in | Not read | vocalfun, GA, Beat003vs |
| `MAudioTrackEvent`, `MAudioEvent`, `MAudioPartEvent`, `MAudioPart`, `MAudioTrack`, `PAudioClip`, `AudioFile`, `AudioCluster`, `MHitPointEvent`, `PPool`, `FNPath` | Arrangement | Audio tracks, events, the pool, file paths, hit points | Detected; reported as skipped | indy (1,681 hit points), BBCSO |
| `MAutomationNode`, `MAutomationTrackEvent`, `MAutomationTrack`, `MParamEvent` | Under track events | Automation lanes | Not read | `tree` |
| `MTrack` v2 | Inside folders and track events | **UNKNOWN** (small, 10–43 bytes) | Used only as a landmark for the folder `Solo` property | `folder_state_flags` |
| `MTrackVariationCollection`, `MTrackVariation` | Track events (property `TVCi`) | Track versions | Not read | census |
| `TrackParaEffect` (named record) / `PDuplicator`, `PMidiEffectBase` | Inside instrument and MIDI track event bodies | MIDI Modifiers slots and their parameter trees | Transpose, Velocity Shift and Delay read by pattern | `track_midi_modifiers`; GA |
| `PInstrumentPool` v0 | Under `MRoot` | Instrument pool, including expression-map definitions (`PSoundSlot` records) | Not read | BBCSO (check, 2026-11-22) |
| `PDrumMapPool`, `PDrumMap`, `PDrumMapEntry` | Under `MRoot` | Drum maps | Not read | `tree` c02 |
| `ScMeasureTrack`, `ScGlobalPart`, `GlobalScoreSymbolsTrack` | Under `MRoot` | Score layout | Not read | `tree` c23 |
| `ChordPadsModelCubaseWrapper`, `ScaleNoteAssistantObject`, `ProjectLyricsSettings`, `UColorSet`, `MidiRemoteSaved…`, `PMarkerAttributeSettings`, `MAutoFadeSetting` | Under `MRoot` / `PArrangement` | Chord pads, scale assistant, lyrics, colours, MIDI Remote, marker settings, fades | Not read | `tree` c23 |

There is **no** expression-map *class* (`PExpressionMap` or similar) and no mute-lane or transpose-track class in any fixture. Expression maps are named-record trees (section 4.14). Whether Cubase's arranger, transpose and video tracks have classes is **UNKNOWN**: no fixture uses them. **VERIFIED** by the census.

### Confidence and evidence (section 3)

The class names, versions, bases and counts are VERIFIED by the census. The "Holds" column is VERIFIED where the status is "Decoded". Elsewhere it is INFERRED from the class name and the strings inside.

---

## 4. The arrangement model

### 4.1 Shape of the tree

```
PArrangement
└─ MRoot
   ├─ MTrackList                      top-level track list (order = Project window order, INFERRED)
   │  ├─ MFolderTrack                 e.g. "Input/Output": I/O channel device tracks
   │  │  ├─ MTrackList "Input/Output" → MDeviceTrackEvent → MListNode "Stereo Out" → (MTempoTrackEvent, MSignatureTrackEvent written inline here)
   │  │  └─ MTrack
   │  ├─ MMarkerTrackEvent → MListNode "Markers" → MMarkerEvent / MRangeMarkerEvent …
   │  ├─ MChordTrackEvent → MChordTrackNode → MScaleEvent, MChordEvent …
   │  ├─ MInstrumentTrackEvent
   │  │  ├─ MListNode "<track name>" → MMidiPartEvent → MMidiPart → events
   │  │  ├─ SNADynamicDefinition, PSNAParamSelection, PControllerLaneSetup, PChordTrackParam, …
   │  │  ├─ MInstrumentTrack          mixer channel (plug-ins, ports, state flags)
   │  │  └─ MAutomationNode …
   │  └─ MFolderTrack "Folder 01" → MTrackList "Folder 01" → track events … ; "Solo" property ; MTrack
   ├─ PInstrumentPool, PMarkerAttributeSettings, PDrumMapPool, ScMeasureTrack, UColorSet, ChordPadsModel…, PPool …
├─ PArrangeSetup
└─ ProjectLyricsSettings
```

**VERIFIED** by `cpr_inspect.py tree` on c02 and c23 (check, 2026-11-22) and the plan's "Arrangement structure". The reader doesn't depend on this shape beyond the parent/child links it names. It finds track events, parts, tempo, signatures and markers by class anywhere in the tree.

### 4.2 Node header: `MListNode` and `MMidiPart`

Both a track's `MListNode` and a part's `MMidiPart` start with the same header:

| Field | Width | Notes |
| --- | --- | --- |
| Name | BOM string | Track name (`MListNode`) or part name (`MMidiPart`) |
| Time base | u32 | 0 = musical (ticks), 1 = linear (seconds) |
| Musical: tempo reference | W (or the whole object) | Back-reference to the `MTempoTrackEvent`; the object itself, inline, in the first node written |
| Musical: signature reference | W (or the whole object) | Back-reference to the `MSignatureTrackEvent`; inline in the first node written |
| Linear instead: f64 | 8 | 1.0 in all three linear nodes seen; meaning **UNKNOWN** |

- **VERIFIED (check, 2026-11-22)**:
  - Across the fixtures of 30 MB or less, this holds in every musical-time node: 883 `MMidiPart`, 342 `MListNode` (track, device and marker lists) and 6 `MChordTrackNode` objects.
  - In 1,176 of them the two fields are back-references to the `MTempoTrackEvent` and `MSignatureTrackEvent`.
  - In the other 52 (one per file: the first node written), the two objects themselves are serialised inline at those positions.
  - The linear form occurs in c26's Lead track node and Riff part, and in one empty, unowned part in BBCSO.
- **Code disagreement.** `decode_part_events` reads these bytes as "uW, u32, uW (unknown)". That spans the same 4 + 2W bytes, so musical parts decode correctly. A linear part, with an f64 in place of the references, fails (section 8).
- **INFERRED**: tracks and parts carry their own time base and a link to the tempo and signature maps used to convert between musical and linear time.

### 4.3 Tracks

**Track event classes read**: `MInstrumentTrackEvent`, `MMidiTrackEvent`, `MDrumTrackEvent` (`TRACK_EVENTS`). **VERIFIED.**

- **Name**: the first field of the track's `MListNode`. **VERIFIED**: GA, Ditty and indy names match their DAWproject tracks (plan).
- **Order**: the reader orders tracks by file position. **INFERRED** to be Project window order. Tier 2 gives `Lead` before `MIDI 01` as created (`test_tier2_midi_track_channel`), but no fixture reorders tracks.
- **Time base**: the u32 after the name in the `MListNode` (section 4.2). Only c26's Lead track is linear. **VERIFIED** (`track_time_base_linear`, `test_tier3_linear_time_base_track_reported_not_imported`).
- **Mute and solo**: a u32 **channel state flags** word in the mixer-channel object. Bit 0 = solo, bit 2 = mute. **VERIFIED** on c14, c17s, c17m, c18fm and GA's two muted tracks. Every instrument and MIDI track in every fixture yields a value with only those bits (`test_state_flags_every_fixture_track`). It is located by structure, not by name (`state_flags_offset`):
  - `MInstrumentTrack` (v9–v11): the flags follow the **last** MIDI input *port record* in the body's final 512 bytes. A port record is `00 03` · C string id · `00 00` · C string name. For the default input both strings are "All MIDI Inputs".
    - What follows the flags varies: a u16 count (0 or 1) with optional BOM strings (Ditty's Groove Agent names its pattern), 14 bytes and `FF`×8; a u32 count and the track's own name (BBCSO, 15.0.10); or `FF FF FF FF 00 00 00 00` (Beat003vs).
    - v11 (Cubase 16) appends a short `FAttributes` object.
    - **VERIFIED** (plan, spot-test fixes; tests).
  - `MMidiTrack` (v7, v8): the body starts with the output port (`00 03` · id · 4 bytes · name), then the input port record, then a u32 (1 for c17's track on channel 2), then the flags. **VERIFIED.** Whether that u32 is the MIDI channel is **UNKNOWN**. The plan wrote "v8, Cubase 16 only", but v7 in argontest003 (13) and in 15 decodes the same way (check, 2026-11-22).
- **`SoloFlag`**: a mixer record (C-string name `SoloFlag`, type 1, i64). It is 1 when an instrument track is **muted**, and a `Solo` record appears when soloed. **VERIFIED** on c13 and c14 (`test_tier2_mixer_solo_flag_record_follows_mute`). Treated as a secondary copy; the flags word is primary.
- **MIDI channel**: stored per event, not read from the track (section 4.6). A MIDI track on channel 2 writes channel byte 1 into each event; instrument tracks write 0. **VERIFIED** (c17).
- **MIDI Modifiers**:
  - Layout. Each track event body holds `TrackParaEffect` named-record objects. Those named "MIDI Modifiers" hold a `PDuplicator` parameter tree: Transpose, Velocity Shift, Delay, Length Compression, Velocity Compression, Channelizer, Scale and others. They sit in slots by `Index`. **VERIFIED** (GA).
  - Integer parameters. Each is a named record of type 2, sub-kind 6, holding `Value`, `Min` and `Max` records (section 2.5). **VERIFIED.**
  - Transpose. Every GA track has slot 0 with Transpose 0. Prologue 01 also has slot 1 with **Transpose 24**, and Cubase's MIDI export plays Prologue 24 semitones up. **VERIFIED** (`test_ga_whole_song_matches_cubase_midi_export`).
  - Bypass state, negative values and the Inspector's own Transpose field are **UNKNOWN** (plan; planned fixtures c31 and c32 were never received).
- **Disabled and hidden tracks, lanes and takes**: **UNKNOWN**. The tier 4 fixtures (c27–c29) were not received.

### 4.4 Folders and instrument stacks

- An `MFolderTrack` holds its own `MTrackList`, whose body starts with the folder name, and then an `MTrack`. No folder is special: the I/O folder ("Input/Output", or "Input/Output Channels" in older saves) is an ordinary folder of device tracks. **VERIFIED** (c18; `test_tempo_track_found_inside_or_outside_folders`).
- **Folder mute and solo**: a property-list entry `Solo` (stored `oloS`, type 1, i64) among the folder's own fields, between its `MTrackList` and its `MTrack`. It is 4 when muted. It is absent in some folders (Ditty), meaning 0. **VERIFIED** (c18fm; `folder_state_flags`).
- **Muting a folder also sets the mute bit on every track inside it**, so the saved track flags already carry the inherited state. **VERIFIED** (c18fm; `test_tier2_folder_mute`).
- **Instrument stack** (Cubase 16): also an `MFolderTrack`. It contains a MIDI track named after the stack, which now holds the parts. The member instrument track is left empty. Extra objects `VstInstrumentMidiChannel`, `SoloManager` and `NodePath` appear. **VERIFIED** (c18is; Cubase's MIDI export names the track "Instrument Stack 01").
- **Where tempo and signature tracks sit**: see section 8. Their byte position reflects the first node header that refers to them, not the folder the user placed them in.

### 4.5 Parts on the timeline (`MMidiPartEvent`)

| Body offset | Width | Field |
| --- | --- | --- |
| 0 | 2 | u16 flags: bit 1 (`0x0002`) = **part muted** |
| 2 | 8 | f64 start |
| 10 | 8 | f64 length (visible) |
| 18 | 8 | f64 content offset |
| 26 | … | Contents: an inline `MMidiPart` object, or a W-byte back-reference to one (shared copy) |

- **Units**: musical tracks use ticks at **480 per quarter note**, from the project's absolute zero. Linear tracks use seconds. **VERIFIED** (tier 2 tests; c26, section 4.7).
- **Mute**: **VERIFIED** on c13. Muted-part counts equal the DAWproject exports (Ditty 52, indy 2, GA 0). No other flag bit is set in any fixture.
- **Trims**: an end trim changes only the length (c12: 3240). A start trim moves the start and sets the content offset (c11: start 8160, offset 480). The visible window is `[start, start + length)`, and a note's absolute time is `start − offset + position`. **VERIFIED** (`test_tier2_part_window_and_mute`).
- **Negative offset**: a part extended *before* its content. GA's "Where Are We" part has content zero at beat 392, visible from 376; argontest003's parts have offsets of −172 and −9930. **VERIFIED** (`test_ga_matches_dawproject_before_tempo_ramp_and_stays_on_grid_after`; check).
- **Shared copies**: the contents field is a back-reference to the first part's `MMidiPart` (c16). An independent copy writes its own `MMidiPart` (c15). **VERIFIED** (`test_tier2_copies`).
- **Loops and repeats**: no loop field was identified. Repeated parts in the fixtures are separate part events (for example argontest003's Groove Agent parts every 7680 ticks). **INFERRED**: copies, not loops.

### 4.6 Part contents and MIDI events (`MMidiPart`)

| Field | Width | Notes |
| --- | --- | --- |
| Node header | section 4.2 | Name; time base; tempo and signature references (or f64) |
| Event count | u32 | |
| Event-class count | u8 | **Absent when the event count is 0** |
| Event-class table | count × (NEW or REF tag · W-byte length 0) | Declares the event classes, all with empty bodies. The first part in a file declares the seven MIDI event classes in the order Note, PolyPressure, AfterTouch, ProgramChange, Controller, PitchBend, Sysex |
| Events | event count × event | |

**VERIFIED**: c02 hex (check, 2026-11-22); every part's declared count is consumed exactly to the part's end (`test_realistic_projects_decode_completely`).

**Each event** is one byte, then a body:

- A MIDI status byte (`90` note, `A0` poly pressure, `B0` controller, `C0` program, `D0` channel pressure, `E0` pitch bend, `F0` SysEx) means a compact body whose class is implied.
- `00` means a full NEW or REF object header comes next, with the same body inside it. The object's length gives a free consistency check.
  - Notes just drawn or edited use this form. **INFERRED** (tier 1: framed notes in c02–c09).
  - Objects of non-MIDI classes (`MScoreEvent`) also appear this way, and the reader steps over them using their length.
  - **VERIFIED** (`decode_part_events`; BBCSO).

**Event body** (positions relative to the start of the body):

| Offset | Width | Field |
| --- | --- | --- |
| 0 | 8 | f64 position: ticks (or seconds on linear tracks), relative to the part's **content start** |
| 8 | 1 | Channel, 0–15 |
| 9 | 2 | Data bytes: note pitch, velocity · CC number, value · pitch bend LSB, MSB · program, 0 · channel pressure value, 0 |
| 11 | 4 | u32 flags: `0x20000` = **note muted** (drawn hollow). No other value seen |
| 15 | 2 | u16 property count, then properties (section 2.6) |
| … | 8 | Notes only: f64 length |
| … | 17 | Notes only: 16 bytes, then a byte equal to the 7-bit **release velocity** |

Evidence for this layout:

- **VERIFIED** for the layout in general (`parse_event_body`; tier 1–3 tests). Pitch bend `3C 10` decodes to 2108 = −6084 from centre, as exported (c24, c25). Program change: program 31 (c25).
- **VERIFIED** for the note mute flag: all 2,399 flagged notes on GA's kit are absent from Cubase's MIDI export, and all 2,548 unflagged ones are present. 5,019 flagged notes exist across the fixtures (plan; check).
- **VERIFIED** for the tail byte: it equals the release velocity derived from `OffV` in all 17,464 notes where `OffV` > 0. It is 0 in all 2,923 notes where `OffV` = 0.0 (check, 2026-11-22).
- **UNKNOWN** for the other 16 tail bytes: they are zero except in 105 notes (Ditty 76, Beat003vs 25, argontest003 4), where the first 8 bytes form a small f64 (for example 9.707, −7.68, 23.565).
- **Fractional ticks**: positions and lengths are f64 and can be fractional (for example 102.953). Cubase rounds them on MIDI export. **VERIFIED** (plan, phase 2).
- **Out-of-range values**: stored values aren't clamped. The orchestral project has one channel-pressure value of 201. **VERIFIED.**

**Event properties seen** (census of 32,865 events in 52 fixtures, check 2026-11-22):

| Reader key (on-disk bytes) | On | Type | Values and meaning |
| --- | --- | --- | --- |
| `OffV` (`VffO`) | notes | f64 | Release velocity as (v − 1) / 126. 64 → 0.5 **VERIFIED**. At v = 0 the stored value is 0.0 (see section 6.2) |
| `HRDT` (`TDRH`) | all | f64 | Normalised velocity or value. Both (v − 1) / 126 and v / 128 occur, even within one file (c02: 100 → 0.7857; c04: 64 → 0.5). Channel pressure: value / 128. Not used by the reader. Meaning **INFERRED** (a high-resolution value) |
| `XFLG` (`GLFX`) | all | i64 | 0 in every event |
| `relP` (`Pler`) | notes | f64 | 0.0 in every note |
| `ncda` (`adcn`) | notes | i64 | `0x20_0000_0000` in 16,685 notes. Otherwise the high u32 is 9–105 and the low 16 bits often equal the pitch. **UNKNOWN** |
| `VOCE` (`ECOV`) | notes | i64 | 0–7, Ditty only (375 notes). **INFERRED**: a voice number |
| `cuTy` (`yTuc`) | controllers, pitch bend | i64 | 1 or 3. The 12 events with 3 match the 12 `cuOb` objects. **INFERRED**: curve type |
| `cuOb` (`bOuc`) | controllers, pitch bend | object | `MParamEventCurveRationalBezier`: the curve shape to the next point. Cubase renders the curve on export (c24: 2 CC1 and 12 pitch-bend points stored; 36 and 251 messages exported). **VERIFIED** (plan) |
| `rAcS` (`ScAr`) | notes, score events, chord events | object (`0x22`) | `CmAttribCollection` of score attributes: articulation techniques (BBCSO: `pt.spiccato`, `PlaybackTechniqueID`), Omnivocal lyric text (`ScTextAttrib`, Beat003vs: "Kettles[k eh]"), `ChordData` |
| two non-text keys (bytes `C2 CA D3 C6`, `C8 CD D0 CD`) | notes in Beat003vs, vocalfun (132) | `CmString`, i64 | The string is an Omnivocal syllable with phonemes ("Tea[t iy]") or empty; the int is always 1 |
| `STSt`, `STLe` | notes, vocalfun only | f64 | **UNKNOWN** |

**What the reader does with each kind** (`import_cubase._clip_events`). **VERIFIED.**

- Notes: note-on at the position, with velocity 1 if the stored velocity is 0. Note-off at position + length, with release velocity `round(1 + 126 × OffV)`, or 64 if `OffV` is missing.
- Controllers, pitch bend, program change and both pressures map one to one.
- Muted notes are dropped.
- Out-of-range events are skipped with a warning.
- The track's MIDI Modifiers transpose is added to note and poly-pressure pitches; a note pushed outside 0–127 is skipped.
- SysEx stops decoding of that part, with a warning.
- There are **no text or meta events** in MIDI parts. The event-class table only ever declares the seven MIDI classes. Text that Cubase *exports* comes from `MScoreEvent` objects (section 4.14). **VERIFIED.**

### 4.7 Time base and the linear layout

- Musical positions are f64 ticks at **480 PPQ** (`TICKS = 480`). **VERIFIED**: tier 1 positions (480 per beat) match the exports.
- **Linear time base** (c26, the Lead track switched to linear): **VERIFIED (check, 2026-11-22)**.
  - The part event holds seconds: start 9.2659, length 4.5000, offset 0.66664.
  - The part's node header is `u32 1 · f64 1.0` instead of the two references.
  - The rest of the part body is the normal layout, with event positions and note lengths in **seconds**.
  - Decoded this way, c26's Riff part gives two notes: (0.66664 s, pitch 62, velocity 64, 1.3333 s) and (2.66664 s, 64, 90, 0.3333 s). That is exactly c07's notes (480 and 1920 ticks; 960 and 240 long) at 90 BPM, and the bytes are consumed exactly to the part's end.
  - The reader skips linear tracks with a warning. The code comment "part body layout differs; not decoded" overstates the difference (section 8).
- **INFERRED**: converting linear positions to beats needs the tempo map, because the part sits after c26's tempo changes. Not implemented.

### 4.8 Tempo track (`MTempoTrackEvent`)

| Field | Width | Notes |
| --- | --- | --- |
| Point count n | u32 | |
| Each point (22 bytes) | f32 seconds per beat · f64 seconds · f64 ticks · u16 type (1 = ramp into this point) | |
| Trailing tempo | f32 BPM | See below |
| (unknown) | 4 | 0 in all files |
| Properties | u16 count · properties (section 2.6) | `TLID`, `TVCi`, `Lock`, `XEUI`, `AXtT`, `TTlB`, `TTuB`, `Eths` |

- **VERIFIED** for points, ramps and the trailing f32 (`tempo_points`; `test_tier3_tempo_points`). **VERIFIED** for the properties (check, 2026-11-22).
- **Ramps are linear in beats.** The stored seconds match 60 · beats / (bpm₁ − bpm₂) · ln(bpm₁ / bpm₂) to 1 µs (c20). GA has two ramps (93 → 97 over beats 264–272; 97 → 93 over 384–432). **VERIFIED** (`test_tier3_tempo_ramp_is_linear_in_beats`).
- **Trailing f32.** It equals the first point in most files, but differs in four:

  | File | First point (BPM) | Trailing f32 |
  | --- | --- | --- |
  | Ditty | 80 | 106 |
  | Beat003vs | 96 | 120 |
  | vocalfun | 112 | 120 |
  | argontest003 | 102 | 120 |

  Ditty's MIDI export runs at 80 BPM, so in the one checkable case Cubase plays the **points**, not the trailing value. **INFERRED**: the trailing f32 is the fixed tempo used when the tempo track is off.
- **Property `TLID`** (stored `DILT`, i64 1):
  - It is present in c19–c26 (tempo track switched on, per the fixture steps) and in Ditty, GA and Beat003vs. It is absent in c01–c18 (left in fixed mode), vocalfun, argontest003 and indy.
  - The signature track carries `TLID` = 1 from c21 on (when a signature change was added), and in Ditty, BBCSO and Beat003vs, which have a single 4/4. So it is probably **not** a "tempo track on" flag.
  - **INFERRED** (low confidence): `TLID` marks that a visible Tempo or Signature track exists in the track list.
- **"Tempo track active" flag: UNKNOWN.** The reader always uses the points.
  - If a project with the tempo track switched off has points that differ from its fixed tempo, the import would follow the points while Cubase plays the fixed tempo.
  - vocalfun (16.0.5, accepted by the reader) imports at 112 BPM. Whether Cubase plays it at 112 or 120 is not known.
  - Experiment in section 7, Q1.
- `TTlB` −10 and `TTuB` 180 (GA): **INFERRED** to be the tempo editor's display range. `Lock`: **INFERRED** track lock. `TVCi`: track versions (`MTrackVariationCollection`). `XEUI` and `AXtT` (`CmString` objects), and `Eths` (i64 −260498236): **UNKNOWN**.

### 4.9 Signature track (`MSignatureTrackEvent`)

| Field | Width |
| --- | --- |
| Point count n | u32 |
| Each point (16 bytes) | u32 ticks · u16 numerator · u16 denominator · 8 bytes (zero in all files; **UNKNOWN**) |
| (unknown) | 2 |
| Properties | u16 count · properties (`TLID`, `LocS`, `TVCi`, `Clks`, `XEUI`, `AXtS`, `Eths`) |

- **VERIFIED**: c21 stores (0, 4/4), (7680, 3/4) (`test_tier3_signature_points`). The property list was decoded for every file (check, 2026-11-22).
- An `FAttributes` child holds the signature events again in named-record form (`SignatureEvent` → `MTimeSignatureEvent`). **VERIFIED** (indy). The reader uses the binary points.
- **Ticks are a u32 here**, unlike the f64 positions elsewhere. **VERIFIED.**

### 4.10 Markers

- The marker track's `MListNode` holds its name ("Markers"), header fields, a u32 count, then `MMarkerEvent` / `MRangeMarkerEvent` objects. **VERIFIED** (c23 hex; plan).
- Marker body: BOM string name · u32 id · u16 (0) · f64 start · f64 **length** (ticks; 0 for a plain marker). A range marker ends at start + length. **VERIFIED**: indy's six contiguous 32-beat sections each end where the next starts (`test_indy_range_markers_are_contiguous_sections`), and c23's cycle marker "Intro" covers bars 1–3 (0 + 12 beats).
- Markers have a property list (`FAttributes` child); not read.
- Cubase's MIDI export writes plain marker meta events at each start, including the start of a range. **VERIFIED** (c23, BBCSO).

### 4.11 Display bar offset

- `PArrangeSetup`, i32 at body offset 84 (v8 and v9, both containers). 0 normally; −1 when the project shows a blank bar before bar 1 (c02-1). Ditty −3, indy −1, GA 0, Beat003vs −2, Scaler3Test −3. **VERIFIED** (`display_bar_offset`; `test_display_bar_offset`).
- **The absolute timeline is unaffected, and Cubase's MIDI export ignores the offset.** Ditty's six-beat pickup sits at absolute beat 6, before its displayed bar 1 (beat 12), and its export has it at beat 6. **VERIFIED** (plan, phase 2).

### 4.12 Chord track (not read; hypothesis)

The reader only reports "Chord track events are not imported". The rest of this subsection was found while writing this document (check, 2026-11-22).

- `MChordTrackEvent` → `MChordTrackNode`. The node starts with a name ("Chord Track") and the node header. In GA it is the first node to refer to the tempo and signature tracks, so their objects are serialised inline inside it. **VERIFIED.**
- **`MChordEvent` is serialised like a note.** f64 position (absolute ticks in GA: 0, 32, 40 … beats) · channel · two data bytes · u32 flags · properties (`CHRD` i64, `XFLG`, `IUEX` a GUID string, `relP`, `ScAr` a `CmAttribCollection` holding `ChordData` v3, `HRDT`, `OffV`, `ncda`) · f64 length (0.0) · 17-byte tail · one extra byte `00`. **VERIFIED**: `parse_event_body` consumes every chord event in GA, Ditty, Beat003vs and vocalfun, leaving exactly 1 byte.
- **Data byte 0 looks like the chord root as a MIDI note number.** GA: 67 G, 62 D, 64 E, 69 A, 60 C, 66 F♯. Ditty: 31 G, 26 D, 28 E, 24 C. **INFERRED**, medium confidence (plausible progressions; no names to check against).
- **`ChordData` body (20 bytes)**, for example `00 48 00 FF 00 00 00 00 00 00 00 00 00 00 00 00 FF 30 00 00`. The first u16 looks like an **interval bitmask**, with bit n−1 set for an interval of n semitones above the root:
  - `0x0048`: major third and fifth (major triad).
  - `0x0044`: minor third and fifth (minor triad).
  - `0x0248`: major third, fifth and minor seventh (dominant 7th, vocalfun).
  - The next byte (00, 01, 07) may be a chord-type index. Some Ditty chords carry a string `min`. **INFERRED**, low to medium confidence.
- `CHRD` values 0, 1, 2, 4 or absent: **UNKNOWN**.
- **`MScaleEvent`** (derived from `MMidiNote`) sits at chord positions in the same node. Its body is *not* note-shaped after the properties. **UNKNOWN.**
- Experiment in section 7, Q2.

### 4.13 Pattern Editor, Drum Track, lyrics, ARA, audio

| Material | What is known | Status |
| --- | --- | --- |
| Pattern Editor parts | `MPatternEvent` placements hold named records `Start`, `Length` (ticks), `priority`, `vertical`, `patternNr` (an index into a pattern bank). Definitions are named records elsewhere (`Lanes`, `LaneInfo`, `NrOfSteps`, `Steps`, `Velocity`, `StepResolution`, `ActivePattern`), probably in the track's mixer object | **VERIFIED** (indy strings, check 2026-11-22; plan, phase 4). Not decoded. indy loses 644 drum notes that Cubase's export renders |
| Drum Track (16) | `MDrumTrackEvent`, same mixer object as an instrument track | Name and flags **VERIFIED**; its pattern part is skipped |
| Omnivocal lyrics | Per note: `ScAr` with `ScTextAttrib` objects, and a hashed-key `CmString` with syllable and phonemes | **VERIFIED** to exist (Beat003vs, vocalfun); not imported |
| Cubase 16 score lyrics | `MScoreEvent` with `ScLyricAttrib` in parts (vocalfun: 69) | **VERIFIED** to exist; stepped over |
| ARA tracks | `AXtProjectTrackEvent`; the notes live inside the plug-in | **INFERRED** (plan, phase 4); not read, and not reported separately |
| Audio | Audio tracks, events, pool, paths, hit points, fades, warp | Detected and reported as skipped |

### 4.14 Expression maps and articulations

These findings are from this document's checks on BBCSO (check, 2026-11-22). The plan recorded the location as "not investigated".

- **Definitions** are named-record trees under `PInstrumentPool` (183 records there, and 249 in further named-record trees). They are `PSoundSlot` entries with `remote` (`PSlotThruTrigger`), `action` (`PSlotMidiAction` with `POutputEvent` status, data1, data2), a note changer, `name` (for example "Legato"), `color`, `slotType` and `visualIndexes`. There is no expression-map class. **VERIFIED.**
- **Placed articulations in parts** are `MScoreEvent` objects written framed among the part's events:
  - Body: u16 0 · f64 position (ticks from the part's content start) · f64 16777215.0 (2²⁴ − 1; perhaps "no length") · 14 zero bytes · a property list with `XFLG` and `ScAr`.
  - The `ScAr` collection holds either a text articulation (a `String` record such as "Legato", "Spiccato", "StacSs", "Tenuto", "long") or a symbol (`Symbol`, `SMuFLCodepoint`, `pt.staccatissimo`).
  - **VERIFIED**: the 617 text-type and 52 symbol-type score events account for all 669 of BBCSO's `MScoreEvent`s.
- **These are what Cubase's MIDI export writes as text events.** On all 15 BBCSO tracks that carry text in the export, the text-type score events of unmuted parts match the exported text events **exactly** in text and position (within 1 tick): 426 events. Symbol-type events are not exported. **VERIFIED.** The other 18 tracks with score events are absent from that export altogether.
- **Per-note articulations** ("attribute" type): notes carry `ScAr` collections naming a playback technique (`PlaybackTechniqueID` = `pt.spiccato`, `pt.user.Spic` …). **INFERRED**: per-note articulations. Whether Cubase exports them as text is **UNKNOWN**.
- **Consequence**: the reader's warning "Score Editor symbols and text in parts are not imported" covers these articulations. The data needed for the roadmap item "Cubase expression-map articulations as text" is in the file and largely decoded.

### 4.15 What the reader applies, and what it deliberately doesn't read

**VERIFIED** (`import_cubase.py`; plan, phase 3 and decisions).

| Applied | Deliberately not read (reported) |
| --- | --- |
| Part window, trims, content offset (including negative) | Audio tracks and media |
| Part mute → clip mute; track mute and solo; folder mute and solo folded into contained tracks | Pattern Editor parts (`MPatternEvent`) |
| Shared copies share one event list | Chord track |
| Muted notes dropped | Score events (articulations, symbols, lyrics) |
| MIDI Modifiers **transpose** (summed over slots) added to pitches | MIDI Modifiers velocity shift and delay (read, reported, not applied); other modifiers; MIDI inserts (for example Arpache 5); instruments |
| Tempo points (ramps stepped once per beat at the midpoint tempo); signatures | Controller curve shapes (`cuOb`): only stored points imported |
| Markers (cycle markers: start, plus a closing "name \|" marker) | Linear-time-base tracks |
| Display offset recorded, not applied | SysEx, and anything after it in that part |
| Fractional ticks kept as exact fractions (denominator ≤ 10⁶) | Automation, expression maps, track versions, ARA |

### Confidence and evidence (section 4)

- **High**: parts, trims, mute (part, track, folder, note), shared copies, event layout, tempo points and ramps, signatures, markers, display offset, the node header. Each rests on a one-change fixture and a test, and most also on agreement with Cubase's MIDI export.
- **Medium**: the linear-time-base layout (one fixture, exact consumption, values consistent with c07), and the articulation storage (one large project, exact match with its export).
- **Low**: the chord encoding, the meaning of `TLID`, and the remaining property keys.

---

## 5. How Cubase writes the file on save

Source: `docs/plans/mirror-mode.md`, "Step 0 results". This was an owner-run log on the owner's MacBook (2026-11-22), with each folder polled every 50 ms. The Cubase version wasn't recorded.

| Observation | Detail | Label |
| --- | --- | --- |
| Temp file, then rename | Every save created a new file in the same folder with the **next number** (`Ditty-04-Macbook-01.cpr`; `orchestral-import-test-02.cpr` for the `-01` project). It grew over two or three polls, then was renamed over the project in a single poll: the temp name went GONE in the same poll that the project's **inode changed** | VERIFIED (log) |
| Project never missing | The project path never disappeared and was never seen half-written. It changed only by a whole-file replace | VERIFIED (log) |
| Timing | Ditty (8.6 MB): the temp file lived about 0.1–0.2 s. Orchestral (173 MB): about 0.17 s from first appearance to rename (12 MB, 100 MB, 173 MB over four polls) | VERIFIED (log) |
| Size is not a change signal | Re-saves of the same project differed by about a byte (9,083,371 / 9,083,372 / 9,083,371) | VERIFIED (log) |
| No backups beside the project | No `.bak` or auto-save files appeared in the watched folders during these saves | VERIFIED (log) |

### 5.1 Auto-saves

The repository holds three Cubase auto-saves in `Verify/Auto Saves/`, named `<project>-X-01-(Move Track BBCSO Bassoon - Bas).bak` and so on.

- They are complete `.cpr` containers, RIFF, written by 16.0.5, although the project file itself is 15.0.10. **VERIFIED** (`roots`, check 2026-11-22).
- **INFERRED**: auto-saves go to an `Auto Saves` subfolder with a numbered `.bak` name that includes a truncated description of the last edit.

### 5.2 Saving in a newer version

The local orchestral file was saved by 16.0.5 (its `Version` archive says so) and stayed RIFF. **VERIFIED.** **INFERRED**: this was a step 0 save (its modification date is the step 0 day). Its tests and README still say 15.0.5 (section 8).

### 5.3 Per-save noise

Two saves with no edits (c08 → c09) differ in 53–66 bytes (plan). The differences are named-record identities, the project's own file name in an `FNPath`, and a GUID string in `WindowLayouts`. **VERIFIED** (check, 2026-11-22). Single-field edits alter a similar number of bytes. Diffs between fixtures must filter this noise (`cpr_inspect.py diff` prints the owning object for each change).

### 5.4 Privacy note

The arrangement stores the project's own path and file name (`FNPath`), media paths, and a machine GUID (`ComputerGuid`). **VERIFIED.** The plan's decision 3 accepted this for the committed fixtures.

### Confidence and evidence (section 5)

High for the replace-by-rename pattern on this Mac: it was seen on every save of two projects. The Cubase version, Windows behaviour and network volumes are **UNKNOWN**.

---

## 6. Mapping to MIDI, and differences from Cubase's own MIDI export

### 6.1 Mapping, briefly

**VERIFIED** (`import_cubase.py`).

- One track per instrument, MIDI or Drum track that has parts. Track names come from the `MListNode`; an instrument stack's parts arrive under the stack track's name.
- Each part becomes a clip:
  - Clip zero is the part's content zero (`start − offset`), or its visible start when the offset is negative.
  - Trims come from the window; mute from the part flags.
  - Shared copies share events.
- Times are converted to quarter notes (ticks / 480) as exact fractions.
- PPQ is 480. The source records `input_format = 'cubase'`, the version and the display offset.
- Markers go on an auxiliary Markers track.
- The tempo map comes from the tempo track; ramps become one step per beat at the tempo of the step's midpoint.
- Limits: 1,000,000 events; positions within 1,000,000 quarter notes.
- Damaged or unsupported files fail before the workspace changes (`test_damaged_projects_fail_without_workspace_change`).
- A project with no MIDI parts and no markers fails with "no supported MIDI parts or markers" (seqtest, check 2026-11-22).

### 6.2 Known differences from Cubase's MIDI export

| Area | Cubase's MIDI export | Our reading | Label and evidence |
| --- | --- | --- | --- |
| Notes, positions, velocities | — | Match exactly on indy's four tracks in [3, 196) (663 notes), and on every track of GA's whole-song export (3,909 notes) | VERIFIED (`test_indy_export_matches…`, `test_ga_whole_song_matches…`) |
| Fractional ticks | Rounded to whole ticks | Kept as fractions | VERIFIED (plan) |
| Muted notes | Left out | Left out | VERIFIED (GA kit 2,399) |
| Muted parts and tracks | No events for them | Kept, marked muted | VERIFIED (GA muted tracks absent from export) |
| Note tails past the part end | Kept (indy Texture Bed: 2 notes one beat longer) | Cut at the visible part end (project-wide clip-edge policy) | VERIFIED; policy deferred (roadmap) |
| Release velocity when `OffV` = 0 | Note-on with velocity 0 (release 0): 39 of 46 matched Ditty notes; the other 7 show 64 | Note-off with velocity 1, from `round(1 + 126 × 0)`; the tail byte stores 0 | INFERRED (check, 2026-11-22). Minor; see Q5 |
| Default release | 64 (Groove Agent tracks often 100, as stored) | From `OffV`, so the same | VERIFIED (GA export: kit 100, others 64) |
| Controller and pitch-bend curves | Rendered as dense messages (c24: 36 CC1 and 251 bends) | Stored points only (2 and 12), with a warning | VERIFIED (plan, decision 6) |
| Tempo ramps | A step every beat | A step every beat at the midpoint tempo, within about 0.02 BPM of Cubase's steps; GA identical | VERIFIED (plan; `DAWPROJECT_OTHER_PAIRS_FINDINGS`) |
| Display offset | Ignored (absolute timeline) | Ignored; recorded | VERIFIED (Ditty pickup) |
| Track transpose (MIDI Modifiers) | Applied | Applied (summed over slots) | VERIFIED (GA Prologue +24) |
| Velocity shift, delay, other modifiers | **UNKNOWN** whether applied | Not applied; reported | — |
| MIDI inserts (Arpache 5 etc.) | Rendered only with Export Inserts on | Not rendered | INFERRED (Ditty findings; export settings unconfirmed) |
| Pattern Editor parts | Rendered as notes (indy: 644 drum notes) | Skipped | VERIFIED |
| Expression-map articulations | Text events at each text-type articulation | Not imported | VERIFIED (BBCSO, section 4.14) |
| Cycle markers | A marker at the start only | Start, plus a closing "name \|" marker (decision 4) | VERIFIED (c23) |
| Linear-time-base tracks | Exported | Skipped with a warning | VERIFIED (c26.midi exists) |
| Chord track | **UNKNOWN** (the plan expects it is not voiced unless converted to MIDI) | Skipped | — |
| Instrument stack naming | Stack name ("Instrument Stack 01") | Same | VERIFIED (c18is) |

Cubase's **DAWproject** export, for comparison:

- It keeps muted notes without marking them.
- It reduces tempo ramps to one step at each ramp's end, while keeping positions in seconds, so positions drift after a ramp.
- It omits controllers and pitch bend.
- It rounds positions through seconds.

**VERIFIED** (Ditty and other-pairs findings; GA tempo verified by the owner in Cubase, 2026-11-16).

### Confidence and evidence (section 6)

High for the rows marked VERIFIED, which rest on exact comparisons in tests. The `OffV` = 0 row rests on 46 matched notes in a project saved before its export.

---

## 7. Open questions

Each question says what would settle it. Where a Cubase experiment helps, it gives exact steps.

**Conventions for all experiments** (from the plan's fixture rules):

- Use Cubase 16.0.5 unless stated.
- Save into a neutral folder with no audio.
- Use **Save As** a new name for each step; never save over a previous file.
- MIDI export: File ▸ Export ▸ MIDI File, whole project, Export Inserts **off**, the same options each time.

### Q1. Which field says the tempo track is on or off, and what is the trailing tempo?

**Why it matters.** The reader always uses the tempo points. In vocalfun (accepted, 16.0.5) the first point is 112 but the trailing tempo is 120, and the file has no `TLID`.

**Settled by.** Two fixtures that isolate "tempo track mode" from "a tempo track exists in the track list".

1. Open `Tier 3/Cubase16/c19.cpr` (tempo track active, 90 BPM from bar 3). Save As `q1-a.cpr` with no change.
2. In the Transport, switch the tempo mode to **Fixed** and set the fixed tempo to **100**. Save As `q1-fixed.cpr`. Export MIDI as `q1-fixed.mid`.
3. Switch the tempo mode back to the tempo track. Remove the **Tempo track** from the Project window (select it and delete it, or use Remove Selected Tracks) without changing the tempo events. Save As `q1-notrack.cpr`. Export MIDI as `q1-notrack.mid`.
4. Take a screenshot of the Transport tempo section for each file.

### Q2. How is a chord stored?

**Settled by.** Chords whose names are known, to confirm the root byte and the `ChordData` bitmask hypothesis (section 4.12).

1. New empty project, 120 BPM, 4/4. Add a **Chord Track**.
2. Add one chord per bar on bars 1–10: C, Cm, C7, Cmaj7, Cm7, Cdim, Caug, Csus4, C/E (slash bass), D.
3. Save As `q2-chords.cpr`. Take a screenshot of the chord track showing the names.
4. Change only bar 10's chord from D to D♭. Save As `q2-chords-b.cpr`.
5. Add an instrument track. Drag the chord track onto it (or use **Chords to MIDI**) to create a MIDI part. Save As `q2-chords-midi.cpr` and export MIDI as `q2-chords-midi.mid`.
6. Optional: set a scale on the chord track's scale lane. Save As `q2-scale.cpr`.

### Q3. Expression-map articulations: are attribute-type ones exported, and is the layout general?

**Background.** Direction-type text articulations are decoded from BBCSO (section 4.14).

1. New project with one instrument track and any expression map that has at least one **Direction** and one **Attribute** articulation.
2. Four notes, one per beat. Assign a Direction articulation at beat 1 and an Attribute articulation to the note on beat 3.
3. Save As `q3-art.cpr`. Export MIDI as `q3-art.mid`.

### Q4. Linear time base in the reader

**Status.** The layout is decoded (section 4.7). Converting seconds to beats needs the tempo map.

1. Open `c26.cpr`. Move the Lead part so that it starts before bar 3 and ends after bar 5, spanning the tempo change and ramp. Save As `q4-linear-span.cpr`. Export MIDI as `q4-linear-span.mid`.

### Q5. Release velocity 0

**Settled by.** Confirming that Cubase exports a stored release of 0 as a note-on with velocity 0, so that the reader can map `OffV` = 0 (and the tail byte 0) to release 0.

1. One instrument track with two notes. In the Key Editor info line, set note 1's **Off Velocity** to 0 and note 2's to 64.
2. Save As `q5-offvel.cpr`. Export MIDI as `q5-offvel.mid`.

### Q6. Cubase 13 and 14 correctness

**Settled by.** Real projects from 13 and 14 **with MIDI parts**, each with a MIDI export made from the same version and the same session (plan, decision 2). argontest003 already decodes, but has no export. A 14 project with parts doesn't exist yet.

1. In Cubase 13 (and separately in 14), open a real project with MIDI parts, tempo changes and markers.
2. Without changing anything, Save As `q6-cb13.cpr` (`q6-cb14.cpr`). Export MIDI from that version.
3. Optional, for argontest003: open it in Cubase 13 and export MIDI as `argontest003.mid`. This also settles the two empty-named markers.

### Q7. The tier 4 material that was never received

The plan's fixture catalogue c27–c34 specifies these; the steps are as written there:

- c27: lanes and takes (comping)
- c28: Disable Track
- c29: hidden track
- c30: one-bar drum pattern
- c31: Inspector Transpose +12
- c32: velocity shift +20
- c33: Arpache 5, exported twice
- c34: chord track (Q2 supersedes it)

Add one step: **c32b**, the MIDI Modifiers slot bypassed with Transpose +12 left in it. That settles the bypass question in section 4.3.

### Q8. SysEx and poly pressure

**Status.** SysEx is not decoded, and decoding of a part stops at it. Poly pressure is never seen.

1. One MIDI part containing one note, one SysEx event (any short message, for example `F0 7E 7F 09 01 F7`), then a second note after it, and one poly pressure event.
2. Save As `q8-sysex.cpr`. Export MIDI.

### Q9. Which variant, RIFF or RIF2, does a save produce?

1. In 16.0.5, create a new empty project and save it as `q9-new.cpr`.
2. Open `samples/project-cubase-phases/Verify/argontest003.cpr` (Cubase 13, RIFF) and Save As `q9-argon-16.cpr`.
3. Report nothing else; the files show the answer.

### Q10. Where tempo and signature tracks sit, and track order

Section 8 explains why the byte position of the tempo track is not evidence of folder placement.

1. From c18 (tracks in "Folder 01"), add a Tempo track and drag it into Folder 01. Save As `q10-tempo-in-folder.cpr`.
2. From c17, move the MIDI track above the Lead track. Save As `q10-reordered.cpr`.

### Q11. Fields still unknown, lower priority

These need no experiment unless a feature needs them:

- `PAppVersion` u32 `0x190`.
- The `MMidiPart` field after the time base on linear parts (f64 1.0).
- The 16 note-tail bytes (a small f64 in 105 notes).
- Properties `ncda`, `VOCE`, `STSt`, `STLe` and `CHRD`; tempo and signature `XEUI`, `AXtT`/`AXtS`, `Eths`, `Clks`.
- The 8 bytes in each signature point.
- The u16 in marker bodies.
- The `MMidiTrack` u32 before the flags (channel?).
- `MTrack`.
- `MScaleEvent` after its properties.
- The rest of `PArrangeSetup`.

`VOCE` (Ditty only) and the tail f64 might be checked by asking the owner what Ditty uses (voices in the Score Editor? note detune?) before designing an experiment.

### Q12. Other open items from the plan

- Pattern Editor rendering (decision 8, phase 4): its fixture requests are listed in the plan.
- Controller curve shapes: decode `MParamEventCurveRationalBezier` and decide the rendering density (decision 6).
- Lyrics import: Omnivocal `ScTextAttrib` and Cubase 16 `ScLyricAttrib` (scope to agree).
- Hidden, disabled and inactive material rules (plan, "Current arrangement vs everything stored"): pending Q7.

---

## 8. Where the plans, the code and the evidence disagree

None of these changes what the reader imports today, except where noted.

1. **`MMidiPart` header.** Code and plan describe it as "uW, u32, uW (unknown)". The evidence shows u32 time base · W-byte tempo reference · W-byte signature reference (section 4.2), the same byte count. It matters for linear parts, where an f64 replaces the references and the current code reports a problem.
2. **Linear time base.** The `PartEvent` docstring and the plan say "the part body layout differs; not decoded". The only difference is the header; the events then decode in seconds (c26, section 4.7).
3. **Tempo and signature tracks "inside the I/O folder".** The plan, the `folder_path` docstring and `test_tempo_track_found_inside_or_outside_folders` read their byte position as folder placement ("GA has them loose; the other fixtures have tempo and signature inside the I/O folder").
   - The evidence: in all 52 files checked, the `MTempoTrackEvent` is written inline at the first node header that references it. That is "Stereo Out" in the I/O folder for most files, and the chord track node in GA (section 2.4).
   - So the position says nothing about where the user put the track. The reader finds them by class, so imports are unaffected. The test asserts a fact about byte positions, not about folders.
4. **ROOT strings.** The `_pstring` docstring says ROOT names "end `\0` only". In the fixtures they have no terminator at all (section 2.2).
5. **MIDI Modifiers record.** The `_param_value` docstring says "`00 | u16 0x0206 | u32 3`". The bytes are the name's NUL, then u16 type 2 (container), u16 sub-kind 6, u32 count 3 (section 2.5). The code matches the literal bytes, so behaviour is right.
6. **Property key spelling.** The plan lists `GLFX` (the on-disk byte order) beside `relP`, `OffV` and `HRDT` (the reader's reversed order). The code docstring calls the score-attribute key `ScAr` (on-disk), while the reader's dictionary key is `rAcS`. This document gives both forms (section 4.6).
7. **Channel pressure.** The `DATA_BYTES` comment says channel pressure is "assumed, no fixture". The plan's spot-test notes and the orchestral project (1,853 events) confirm it.
8. **`MTimeSignatureEvent`.** The plan lists it among the arrangement's classes. It occurs only as a class name inside the signature track's named-record tree, not as a binary object (section 4.9).
9. **`MMidiTrack` version.** The plan says "v8, Cubase 16 fixtures only". v7 occurs in 13 and 15 (argontest003 has MIDI tracks) and decodes the same way.
10. **The orchestral verify file's version.** `test_verify_out_of_range_value_skipped_not_fatal` and `samples/project-cubase-phases/README.md` say 15.0.5. The local copy now reports **16.0.5** (RIFF), consistent with being re-saved during mirror-mode step 0. It still imports 605 notes with the out-of-range warning (check, 2026-11-22).
11. **Release velocity at 0.** The plan gives `OffV` as (v − 1) / 126, which can't represent 0. Cubase stores 0.0 for a release of 0 (the tail byte is 0) and exports velocity-0 note-offs. The reader produces 1 (section 6.2, Q5).
12. **`HRDT`.** The plan gives it as "velocity in the same form" ((v − 1) / 126) for notes and value / 128 for aftertouch. Both scalings occur for notes, even within one file (section 4.6). The reader doesn't use it.
13. **The "Score Editor symbols" warning.** In BBCSO the skipped `MScoreEvent`s are mostly expression-map articulation texts that Cubase exports (section 4.14), not only Score Editor symbols.

---

## Appendix: reproducing the evidence

Run from the repository root. All commands are read-only.

```
PYTHONPATH=. .venv/bin/python tools/cpr_inspect.py roots    "samples/project-cubase-phases/Tier 1/Cubase16/c01.cpr"
PYTHONPATH=. .venv/bin/python tools/cpr_inspect.py tree     "samples/project-cubase-phases/Tier 3/Cubase16/c23.cpr" --depth 7 --offsets
PYTHONPATH=. .venv/bin/python tools/cpr_inspect.py classes  "samples/project-sets/indy-001x.cpr"
PYTHONPATH=. .venv/bin/python tools/cpr_inspect.py notes    "samples/project-cubase-phases/Tier 2/Cubase16/c16.cpr"
PYTHONPATH=. .venv/bin/python tools/cpr_inspect.py timeline "samples/project-sets/GA & Padshop 2-(alt instr 2)-01.cpr"
PYTHONPATH=. .venv/bin/python tools/cpr_inspect.py diff     "samples/project-cubase-phases/Tier 1/Cubase16/c08.cpr" "samples/project-cubase-phases/Tier 1/Cubase16/c09.cpr"
PYTHONPATH=. .venv/bin/python tools/cpr_inspect.py hex      "samples/project-cubase-phases/Tier 1/Cubase16/c02.cpr" 2335 2910
```

The checks marked "(check, 2026-11-22)" were one-off scripts built on `midi_interchange.core.cpr_format`. They aren't committed. Their method is described where each result is given, so they can be rewritten in a few lines.
