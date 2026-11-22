# Reason song file format (`.reason`)

A baseline of everything this project knows about the file Reason writes when it saves a song, as of 2026-11-22. It is written for a developer who has never seen the project. It describes the file, not the app that reads it.

Nobody has published a specification. Everything here was worked out from files saved by Reason 6 to 14. Reason Studios' own MIDI exports of the same songs serve as ground truth.

## How to read this document

Every statement carries one of these labels:

- **VERIFIED**: shown by code that decodes real files, by a test, or by an analysis of the fixtures that this document names. The evidence is given.
- **INFERRED**: a reasonable conclusion from the evidence named, but not tested directly.
- **UNKNOWN**: not established.

Byte offsets are from the start of the structure named. All integers are **big-endian** unless stated. Ticks are at **15360 per quarter note**.

### Sources

| Source | What it is |
|---|---|
| `midi_interchange/core/reason_format.py` | The decoder: container, index, IFF, records, playback rules |
| `midi_interchange/core/import_reason.py` | How a decoded song becomes MIDI clips |
| `tools/reason_inspect.py` | Research CLI: `copies`, `tree`, `tracks`, `diff` (run as `PYTHONPATH=. .venv/bin/python tools/reason_inspect.py ...`) |
| `tests/test_reason_format.py`, `tests/test_import_reason.py` | Synthetic-file tests, plus every fixture with a Reason MIDI export checked against it |
| `docs/plans/reason-import.md` | The investigation record: phases 0 to 2, decisions, evidence |
| `docs/plans/mirror-mode.md` | Step 0: how Reason writes a file on save |
| `docs/INTEROP_FINDINGS.md`, `docs/ROADMAP.md` | Clipboard capture; open Reason items |
| `samples/reason-probe/` | The r-series (r01 to r27, one change per file) and `mute-tests`, `rampy`, mostly with Reason MIDI exports |
| `samples/reason-check/` | Real songs with Reason MIDI exports. **`Aug01-01-03.reason` is live** (the owner's Reason saves to it) and was not used: scratch copies were used instead |
| `samples/_archive/reason-probe-songs/` | Songs saved by Reason 6, 9, 10, 11, 12, 13 and 14, several songs in more than one version |
| `samples/local/reason/` | `Oct08-01-13-instr-rarity-sd4` (58 MB, with export) |
| Scratch copies of Aug01 | `aug_committed_head.reason` (the version committed in git) and `aug_after_bar16.reason` (after the owner's controlled saves, section 7) |

The analysis for this document covered **104 `.reason` files** (every fixture above except the live Aug01, plus the two scratch copies).

---

## 1. Overview and versions

A `.reason` file is a small **paged store** (the "X15_FILE" container). It holds one or more **streams**. Stream 1 is the song. The other streams are embedded samples. The song stream is IFF: a `FORM X15S` whose `BODY` chunk holds the song proper.

The `BODY` begins with a 128-byte plain header. Its first six bytes name the format **generation**. That generation, not the file extension or the program version, decides whether the song can be read.

| BODY magic | Saved by | Payload after the 128-byte header | `Hash` chunk | Copies seen | How we treat it |
|---|---|---|---|---|---|
| `RSN600` | Reason 6 | High-entropy, not IFF | No | 2 | Refused: "saved by Reason 6 … re-save in Reason 13 or later" |
| `RSN900`, `RSN999` | Reason 9, 9.5 (one `RSN999` copy says `PROGRAMVERSION` 10.0.0) | High-entropy | No | 9 | Refused |
| `RS1000` | Reason 10 | High-entropy | No | 3 | Refused |
| `RX1100` | Reason 11 | High-entropy | No | 6 | Refused |
| `RS1200` | Reason 12 (12.2.x) | High-entropy | No | 14 | Refused |
| `RS1250` | Reason 12.6.0 | **Plain IFF (`CAT RS10`)** | **Yes, verifies** | 2 (one song) | Refused by the reader today (see below) |
| `RS1300` | Reason 13 and 14 | Plain IFF (`CAT RS10`) | Yes, verifies | 113 | **Read** |

- **VERIFIED** (the generation and Hash tally above; a scan of every song stream named by any index page in the 104 files): `RSN600` to `RS1200` payloads are not IFF, and those copies have no `Hash` chunk; `RS1250` and `RS1300` copies have one and it verifies.
- **VERIFIED, new in this study** (`samples/_archive/reason-probe-songs/Reason12/T004-3.2(A hundred Steps)-3(11)(Self).reason`, index page 21): the `RS1250` body is **plain**. Bytes 128 on read `CAT … RS10 APPV`. In-process, with the generation check relaxed, the existing decoder parsed 21 `RS10` children, 12 tracks and 542 notes. There is no Reason export of this song, so the decode is not checked against ground truth.
  - This contradicts `docs/plans/reason-import.md` (Phase 0 and decision 6), which group `RS1250` with the encrypted generations. It agrees with the Reason Studios statement quoted there, that songs were encrypted from Reason 6 to 12.5 and are not from 12.6 (**INFERRED**: 12.6 is when encryption ended and the `Hash` chunk arrived).
  - Whether to read `RS1250` songs is a decision for the owner. Only one song is available.
- **VERIFIED** (`reason_format.read_song`, `import_reason.import_reason`): the reader parses `CAT RS10` only for `RS1300`. For other generations it reads the metadata (`CAT WWWI`) and refuses with the version, taken from `PROGRAMVERSION` or, failing that, from the magic (`generation_version`: `RS1200` → 12, `RSN999` → 9.5).
- **VERIFIED** (Phase 0 of the plan; the `Grandfathered/` fixtures): opening an old song in Reason 14 and saving it again produces `RS1300`.
- **VERIFIED** (Phase 0): `.rns` files (Reason 5) are a different format, uniformly high-entropy from the first byte. Out of scope.
- **INFERRED** (`docs/INTEROP_FINDINGS.md`, "Reason 14: proprietary, compressed or encrypted"; the `REMB` chunk, section 3): Reason's **clipboard** payload and the song file's `REMB` chunk share a layout: the text `Propellerheads Reason …` then `0x1A`, zeros to offset `0x78`, then the words `e7 1f de 31` and `00 00 40 00`, then high-entropy bytes. The clipboard is not readable; the song body (from 12.6) is.

**Confidence and evidence:** high for the generation split and for `RS1300` (113 copies, every Reason export matches). Medium for `RS1250`: one song, structurally decoded, no ground truth.

---

## 2. The container ("X15_FILE")

### 2.1 Layout

```
offset 0      52-byte header
offset 52     page 0
offset 52 + n x page_size     page n
```

- **VERIFIED** (all 104 files): file size = 52 + n × 262144 exactly. The page size is `0x40000` (256 KiB) in every file.
- Pages are numbered from 0. A stream occupies a list of pages, which need not be contiguous or in order (for example `[0, 7, 8, 9, 10]`).

### 2.2 The header

The header holds the magic, the page size, and **two "slots"**, each naming one index page with a generation number and a checksum. This slot structure is the main result of this study (section 7).

| Offset | Width | Field | Value seen | Varies | Status |
|---|---|---|---|---|---|
| 0 | 8 | Magic | `X15_FILE` | Never | VERIFIED (all files) |
| 8 | u32 | Page size | `0x00040000` | Never | VERIFIED (all files; `read_header`) |
| 12 | u32 | `0x24` = 36 | 36 | Never | VERIFIED value. INFERRED meaning: the size of the two slots that follow (2 × 18 = 36; 16 + 36 = 52) |
| 16 | u64 | **Slot 0 generation** | Even: 2, 4, 6 … 40 | Each save that lands in slot 0 | VERIFIED (see below) |
| 24 | u64 | **Slot 0 index page** | A page holding an index | When slot 0 is rewritten | VERIFIED |
| 32 | u16 | **Slot 0 check** | CRC-16/XMODEM of bytes 16 to 31 | With slot 0 | VERIFIED (208 of 208 slots) |
| 34 | u64 | **Slot 1 generation** | Odd: 1, 3, 5 … 41 | Each save that lands in slot 1 | VERIFIED |
| 42 | u64 | **Slot 1 index page** | A page holding an index, or page 0, or a page past the end of the file (stale) | When slot 1 is rewritten | VERIFIED |
| 50 | u16 | **Slot 1 check** | CRC-16/XMODEM of bytes 34 to 49 | With slot 1 | VERIFIED |

The check is CRC-16 with polynomial `0x1021`, initial value 0, no bit reflection and no final XOR (the "XMODEM" variant), computed over the slot's 16 bytes (generation, then page). **VERIFIED**: it matches all 208 slots in the 104 files; the CCITT-FALSE, GENIBUS and AUG-CCITT variants match none. A hint that pointed the way: slots that differ only in the page's low byte (4, 5, 6) have checks differing by `0x1021` and `0x3063`, the signature of that polynomial.

Further facts, **VERIFIED** across all 104 files:

- The two generations always differ by exactly 1. Slot 0's is always even and slot 1's always odd.
- The slot with the higher generation always names a page that holds a valid index listing stream 1. For every `RS1250` and `RS1300` file, that stream's `Hash` verifies.
- In 17 files, slot 1 is `(generation 1, page 0)`, and page 0 is an **empty index** (`FF×8`, count 0, `b0bafe77`, then `0xFE`). These are songs saved once into a fresh file (r01, r02, r03, r08, `rampy`, …). **INFERRED**: a new file starts with an empty index on page 0 as generation 1, and the first save is generation 2.
- In 28 files, the lower-generation slot names a page **past the end of the file** (for example `Sep13-01-02-hallow-01`: slot 1 names page 325 of a 325-page file). **INFERRED**: the file was shortened after that slot was written (section 2.6), so a stale slot can point anywhere.

How the current reader uses the header: `reason_format.read_header` reads bytes 16 to 31 as `a` and `index_hint`. These are **slot 0's generation and page**. The docstring's "5 x u32 (not decoded)" are slot 0's check and the whole of slot 1. That is why `index_hint` "names the older copy in some files and the newer in others": it is only ever slot 0.

Header samples from the Aug01 scratch copies (16-bit groups from offset 8):

```
committed: 0004 0000 0000 0024 | 0000 0000 0000 0002  0000 0000 0000 0006  a6a1 | 0000 0000 0000 0003  0000 0000 0000 000b  9c2f
after b16: 0004 0000 0000 0024 | 0000 0000 0000 0008  0000 0000 0000 0006  4939 | 0000 0000 0000 0007  0000 0000 0000 000b  00c0
           page size   0x24      slot 0 gen           slot 0 page          crc     slot 1 gen           slot 1 page          crc
```

**Confidence and evidence:** very high for the field layout and CRC (208 slots, exact match). High for the meaning of the generation (section 7). The meaning of `0x24` is inferred.

### 2.3 Pages and fill bytes

- **VERIFIED** (`r01` page 0; `rampy`, `SelfDef000`, `Day 15(2019)-002(14)`): never-written page bytes are `0xFE`. Index pages are padded with `0xFE` after their end marker (the Aug01 copies: 262064 bytes of `0xFE` after each index).
- **VERIFIED** (the page-tail survey of `reason-probe`, `reason-check` and the Aug01 copy): the space after a stream's last byte, in its last page, is usually **not** `0xFE`. It holds leftover bytes, for example JSON-like text in Aug01 and other bytes in the r-series. **INFERRED**: Reason writes whole pages from a buffer that it doesn't clear. A reader must cut each stream to its byte size and must not look for fill bytes to find the end.
- **VERIFIED** (`mute-tests`, `r07`, `r17`, `r20`, `r21`, `Day01-0-3(14)`, `SelfDef000(14)`): pages not listed by any valid index can still hold an old song's first page (`FORM …`).

### 2.4 Index pages

An index page lists the streams of one saved state.

| Offset | Width | Field |
|---|---|---|
| 0 | 8 | Marker: `FF FF FF FF FF FF FF FF` |
| 8 | u32 | Entry count |
| 12 | … | Entries, one after another |
| after the last entry | u32 | End marker `0xB0BAFE77` |
| then | … | `0xFE` to the end of the page |

Each entry:

| Offset in entry | Width | Field |
|---|---|---|
| 0 | u32 | Stream id (1 = song) |
| 4 | u64 | Stream size in bytes |
| 12 | u64 | Page count n |
| 20 | n × u64 | Page numbers, in stream order |
| 20 + 8n | u32 | Entry end marker `0xC0CAC01A` |

- **VERIFIED** (`reason_format.read_index`; the raw bytes of the Aug01 index pages 6 and 11; `Day01-0-3(14)` page 39, 13 entries).
- **VERIFIED** (the Aug01 copies, both versions): the two index pages are byte-identical apart from their page lists. **An index page carries no generation, sequence number or timestamp.** In Aug01 the stream sizes are equal too (1,072,118 bytes committed; 1,071,908 after bar 16); in other files they differ.
- **VERIFIED** (`Jun06-01-03`, page 2): a stale index can list stream ids and pages that no longer exist (pages up to `0x20e` in a 9-page file). `read_index` rejects entries whose pages are past the end, and that index is then ignored.
- **VERIFIED** (`Oct08`, `DumDum001-9_mix2(14)-folders`): in a two-copy file, both index pages list the same sample streams on the same pages. Only stream 1 differs. **INFERRED**: a save rewrites the song stream but leaves unchanged sample streams where they are.

### 2.5 Streams

- **Stream 1** is the song: `FORM X15S` then `Hash` (section 3). **VERIFIED** (every index that names stream 1 and verifies).
- **Streams 2 and up** are embedded samples (self-contained songs). Ids need not be contiguous (`s2, s5, s6, s7, s8` in DumDum). **VERIFIED** that they exist and are listed. Their content is **UNKNOWN** beyond a common prefix: the ones looked at in `Day01-0-3(14)` start `05 13 a9 97 bc 01 03 00 00 00 00 00 01 00 00 ac 44`, and `0xAC44` = 44100 suggests a sample rate (**INFERRED**). The plan records that samples are losslessly compressed (from Reason's manual).
- Files reach about 106 MB with samples (`PianoGuitarDrums-v02f(14)-NoEZ`, 405 pages). **VERIFIED**.

### 2.6 How a save changes the file

What is established:

1. **VERIFIED** (the `copies` survey; 35 files hold two hash-verified song copies): a save writes a **new song stream and a new index page** into pages not used by the current state. The previous state's pages are not overwritten by that save, so a file often holds two complete songs.
2. **VERIFIED** (the Aug01 sequence, section 7.3): each save writes generation (higher + 1) into the slot that held the **lower** generation, so the two slots take turns.
3. **VERIFIED** (Aug01 bar 12, 14 and 16 saves, as reported, plus the bar 16 file): in a file whose song size is stable, the new copy reuses exactly the older copy's pages and index page. Copy A = song pages `[1, 2, 3, 4, 5]`, index on page 6; copy B = `[0, 7, 8, 9, 10]`, index on page 11. So the **newest copy alternates between the two page sets on every save**. **INFERRED**: pages are allocated lowest-free-first, with the current copy's pages and the shared sample streams protected.
4. **VERIFIED** (28 files with a stale slot past the end; `Jun06-01-03`'s stale index naming pages up to 525; step 0 saw DumDum shrink from 9,437,236 to 8,650,804 bytes, 36 to 33 pages, in one save): Reason **sometimes shortens the file** so that it ends at the last page in use. **UNKNOWN**: when it does. In the Aug01 sequence the file stayed at 12 pages through every save, although after the bar 12 and bar 16 saves the current copy ended at page 6. In `r07`, the file was cut to 5 pages and the older copy's pages 5 to 7 were lost.
5. **VERIFIED** (`r03` → `r04` → `r05` → `r06`, `r10` → `r11` → `r12`, `r14` → `r15`, `r17` → `r18`, `r21` → `r22` → `r23`): in these Save As chains, the older copy in file *n + 1* is byte-identical to the current song of file *n*, and the slots read `(2, page 4 or 5)` and `(3, page 7 or 9)`. **INFERRED**: each file was made by Save As (a fresh container: generation 1 empty, generation 2 the song as it stood), then one edit and Save (generation 3). Files with only `(2, …)` and `(1, 0)` were saved once after Save As. That the r-series was made this way is not recorded; it is an inference from the bytes.
6. **VERIFIED** (`r08` and `r09`, "save again with no change"): the two song streams are byte-identical. There is no per-save noise in the song stream for that song. Aug01 is different: its Pianoteq device state holds a save timestamp (section 7.3).

### 2.7 Which copy is current

**The current copy is the one named by the header slot with the higher generation.** This is section 7's result, with the evidence and its limits. In short:

- It matches every ordering known from ground truth, including the Aug01 bar 16 file, where the rule the reader uses today (the verified copy on the highest index page) picks the wrong copy.
- It has not yet been confirmed by opening a crafted file in Reason (section 7.6).

**Confidence and evidence (section 2):** layout and index: very high. Allocation and alternation: high for Aug01; inferred in general. Truncation: observed, rule unknown.

---

## 3. The song stream

### 3.1 Top level

```
FORM <size> X15S
    CAT  WWWI   metadata (key/value pairs)
    CAT  ApVC   application version (absent in the Reason 6 file)
    FORM REMB   opaque block (not IFF inside)
    BODY        128-byte header + (RS1250/RS1300) CAT RS10 ...
Hash <37>       BC 01 00 00 00 + SHA-256 of the whole FORM chunk
(1 pad byte)
```

- **VERIFIED** (`reason_format.read_song`, `song_hash_ok`; r02 dump): chunks are IFF: 4-byte id, u32 size, body, padded to even length. `FORM`, `CAT ` and `LIST` are groups with a 4-byte type. The stream length is FORM size + 8 + 45 + 1 pad (r02: 766172 + 8 + 46 = 766226).
- **VERIFIED**: the `Hash` chunk's last 32 bytes are the SHA-256 of the `FORM` chunk (header included). A stale copy whose pages were partly reused fails this check, so a corrupted copy is detected exactly.
- **VERIFIED** (`_metadata`): `CAT WWWI` holds `FORM WWWI` pairs: a `WWID` (`BC 01 00 00 00`, a byte, str32 key) and a `BODY` (str32 value). Keys seen: `WINDOWTITLE`, `MORETEXT`, `WEBPAGE`, `EMAIL`, `SONGLENGTHPPQ`, `SONGSIGNATURE`, `SONGTIMESIGNATURES`, `SONGTEMPO` (milli-BPM), `SONGLENGTHMS`, `PROGRAMVERSION` (for example `14.1.0`).
- **VERIFIED** (r02 bytes): `CAT ApVC` holds one `AppV` record containing the string `Reason` and integers (not decoded, **UNKNOWN**).
- **VERIFIED** (r02 bytes): `FORM REMB` holds `Propellerheads Reason Song File` + `0x1A`, zeros to body offset `0x78`, then `e7 1f de 31 00 00 40 00`, then 148 high-entropy bytes. **UNKNOWN** content. **INFERRED**: the same layout as Reason's clipboard payload (section 1).

### 3.2 The BODY header

- **VERIFIED**: the `BODY` starts with six ASCII bytes naming the generation (`RS1300` …), then `0x1A`, then zeros to 128 bytes, in every generation seen (r02; `RS1200`, `RSN600`, `RS1000` samples).
- For `RS1250` and `RS1300`, a single `CAT RS10` follows at offset 128. **VERIFIED**.

### 3.3 Record conventions inside `RS10`

- **VERIFIED** (the decoder's offsets; the tree dumps): most leaf chunks start `BC <version> <b2> 00 00`. Field offsets in this document count from the start of the chunk body, so they include these 5 bytes. The meaning of `<b2>` is **UNKNOWN**.
- Strings ("str32") are a u32 length followed by UTF-8 bytes, no terminator. **VERIFIED**.
- Note positions and lengths use MSB-first 7-bit varints, as in MIDI files. **VERIFIED** (`varint`; tests).
- Running positions are added modulo 2^32 and read as signed. A note left before its clip's start by a split or trim has a negative position. **VERIFIED** (`wrap32`; exports).

### 3.4 Chunk catalogue (`CAT RS10`, Reason 13 and 14)

Order as seen in every `RS1300` song examined (r02, r24, dec2024-27-02, dec2024-28-01, DumDum folders).

| Chunk | Holds | Decoded | Status |
|---|---|---|---|
| `APPV` | `Reason` string and integers | No | UNKNOWN |
| `HEAD` | 256 bytes; starts `95 af 00 77`, then `(c)2012 Reason Studios, all rights reserved` | No | VERIFIED text; rest UNKNOWN |
| `GLOB` | 9 bytes, zeros after the record header | No | UNKNOWN |
| `USRI` | User info: the `www.yoursite.here` and `your@email.here` placeholders | No | INFERRED from strings |
| `SNGI` | Song info. u32 at 5 = song length in ms (= `SONGLENGTHMS`); u32 at 9 = tempo in milli-BPM (= `SONGTEMPO`); u32 at 13 = song length in ticks ÷ 256 (= `SONGLENGTHPPQ` ÷ 256); bytes 17, 18 = signature 4, 4; then more values (r17 includes 90000, its tempo clip's 90 BPM; Day 15 includes 104000, the static tempo Reason's export uses) | Not used by the reader | First three fields VERIFIED in r02, r17 and Day 15; the rest UNKNOWN |
| `SARF` | 9 bytes | No | UNKNOWN |
| `CAT 45IL` | One `FORM 45In` (with `45Pr`, `45So`) per **Rack Extension** used: id (`se.propellerheads.GainTool`), short name, name, vendor | No | VERIFIED from strings (r02) |
| `CAT DEVL` | The rack: one `FORM DEVI` per device | `DESC` only | See below |
| `RACK` | Rack layout | No | UNKNOWN |
| `PEAK` | 18 bytes | No | UNKNOWN |
| `CAT RCTL`, `FORM PLCL`/`PLNC`, `PLAN` | Not examined | No | UNKNOWN |
| `CAT CCTL` | One `CNCT` (26 bytes) per cable: device and socket numbers | No | INFERRED (plan Phase 0; device ids such as `0x0fee`, `0x0fef` appear in them) |
| `MRBC`, `CAT SLKL`, `LIST SOVL` | Not examined | No | UNKNOWN |
| `CAT SQCT` | **The sequencer** (section 4) | Yes | VERIFIED |
| `CAT SMGC` | Per-placement Block lane mutes. Found inside `SQCT` after the track list (DumDum, dec2024-27-02) | Yes | VERIFIED (section 4.8) |

`FORM DEVI` (a rack device):

| Child | Holds | Status |
|---|---|---|
| `DESC` | u32 device id at 6, str32 name at 10, then the device type (for example `X15 Main Mixer Mix Channel`, `MClass Maximizer`, `se.propellerheads.radicalpiano`) | id and name VERIFIED (`device_names`); type string VERIFIED from strings |
| `DCHL`, `TRIM`, `FORM PTCH`, `BODY`, `FORM BSTT` | Device state; very large in some devices (a Combinator of 687 KB in the empty song r01/r02) | UNKNOWN |
| `PARM` | Parameter values. r20 → r20x (mixer solo) changes one byte, `02 00` → `02 01`, in the `PARM` of the `X15 Main Mixer Mix Channel` device. The bytes look like (parameter number, value) pairs | Location VERIFIED (`reason_inspect diff r20 r20x`); layout INFERRED |

**A sequencer track's name is its device's name**: the track's `TRDC` names a device id, and `DESC` gives the name. **VERIFIED** (`tracks`; every export's track names match).

**Confidence and evidence:** high for the parts the reader uses (every export matches). Most of the rack is undecoded.

---

## 4. The sequencer (`CAT SQCT`)

### 4.1 Contents

| Child | Holds | Status |
|---|---|---|
| `TRDC` (62 bytes) | Song-level sequencer data: u32 tempo (milli-BPM) at 23; signature numerator and denominator at 27 and 28; **Blocks switch** = third byte from the end | VERIFIED (`global_tempo_and_signature`, `blocks_enabled`; r17, r19, SelfDef000, r24, dec2024-27-02) |
| `CAT SACT` | `FORM SAFM`/`SADC` records. The first has id 0 and u32 at 6 = the song length (r02: 11105280 = `SONGLENGTHPPQ`). The rest are **Block definitions** `Block 1` … `Block 32`: id at 5, u32 length in ticks at 6 (r02: 491520 = 32 beats), str32 name at 10, then a byte that varies (perhaps a colour) | Names and lengths VERIFIED from r02 bytes; the first record's meaning and the trailing byte are INFERRED |
| `SQUG`, `STRE`, `STRM` | Small records | UNKNOWN |
| `SQGM` | 41,986 bytes in every song looked at | UNKNOWN |
| `CAT TTCT` | **Reason 14** track list, inside folders | VERIFIED |
| `CAT TSCT` | **Reason 13** track list, flat | VERIFIED (dec2024-28-01, 13.1.0; also the `RS1250` song) |
| `CAT SMGC` | Per-placement Block lane mutes | VERIFIED |

### 4.2 Tracks

- **Reason 14:** `CAT TTCT` → `FORM TFFM` (a folder; `TFDC` holds str32 name at 5; the top one is named `Root`) → `CAT TFCT` → `FORM TRFM` (a track) or a nested `FORM TFFM` (a **track folder**). **VERIFIED** (`tracks`; DumDum folders: `MAIN GROOVE` in folder `Drums`).
- **Reason 13:** `CAT TSCT` → `FORM TRFM` …, no folders. **VERIFIED**.
- Track 0 is the **Transport** track (named after the hardware interface device; Reason's export calls it `Transport`). Track 1 is often the master section, with no lanes. **VERIFIED** (plan; r02, r24).

`FORM TRFM` (a track):

| Child | Holds | Status |
|---|---|---|
| `TRDC` | u16 device id at 11; **track mute** u8 at 13; u8 at 18 varies 0 to `0x0E` across songs (first taken for the track kind; probably the colour) | id and mute VERIFIED (r13 → r14 changes byte 13 from 0 to 1); byte 18 INFERRED |
| `CAT LNCT` | The track's lanes (`FORM LANF`) | VERIFIED |
| `TRSC` | Note track: u32 count, then per performance controller 15 bytes: u16 lane id, i32 **resting value**, u8 flag, i32 min, i32 max. Transport track: u32 count, then per parameter u16 id (`0x80` tempo, `0x81` signature), i32 value, 8 more bytes | VERIFIED (`controller_rest`, `_transport_statics`; mute-tests' sustain rests at 79, r16 at 0; Day 15's static tempo 104000) |

### 4.3 Lanes

`FORM LANF` holds `LASC` (not decoded), `LANC`, and `CAT LCCT` (the clips).

`LANC`: u8 lane kind at 5, str32 name at 6, u8 **lane mute** after the name. **VERIFIED** (`decode_lane`; r15).

| Lane kind | Meaning | Status |
|---|---|---|
| `0x59` | Note lane | VERIFIED |
| `0x5A` | Pattern lane (Redrum, Matrix …) | VERIFIED (r21, DumDum) |
| `0x5B` | Parameter automation lane (also the Transport's tempo and signature lanes) | VERIFIED (r24's Transport has `5b, 5b, 5d`; DumDum's Maximizer and Filter 1) |
| `0x5C` | Audio lane | INFERRED (code comment and plan; no fixture checked here) |
| `0x5D` | Blocks lane (on the Transport track) | VERIFIED (r24, block tests) |

### 4.4 Clips

`CAT LCCT` → `FORM LCFM` (one per Block context) → `LCAI` (u8: 0 = clips on the song timeline, n = clips inside Block n) and `CAT SNCT` → one `FORM SNIF` per clip. **VERIFIED**.

`SNIC` (every clip):

| Offset | Width | Field | Status |
|---|---|---|---|
| 5 | u32 | Start, ticks (song position; inside a Block, Block-relative) | VERIFIED |
| 9 | u32 | Length, ticks | VERIFIED |
| 13 | 8 | Not decoded | UNKNOWN |
| 21 | str32 | Clip name | VERIFIED |
| after name | u8 | **Clip mute** | VERIFIED (r12 → r13; r13 → r14 clears it) |
| +1 | 3 | Not decoded (often `0a 01 07`) | UNKNOWN |
| +4 | u32 | **Loop length**, ticks (0 = no loop) | VERIFIED |
| +8 | i32 | **Loop offset**: where the first loop pass starts relative to the clip start (≤ 0 after a start trim) | VERIFIED |

What the `SNIF` holds besides `SNIC` decides the clip type (**VERIFIED**, `_clip`): `SNTE` notes; `SAUT` automation; `SPTN` pattern; `FORM SASF` audio; `SBLK` Block placement.

### 4.5 Notes (`SNTE`)

| Offset | Field |
|---|---|
| 5 | u32 note count |
| 9 | per note: varint position delta (running, modulo 2^32, signed); u8 pitch; u8 velocity; varint length; u8 flags (bit 0 = **muted note**) |
| then | u32 controller lane count, then the lanes (4.6) |

**VERIFIED** (`decode_notes`; r02 to r07 against exports; every export). Positions are relative to the clip start.

### 4.6 Controller lanes, points and curves

A controller lane inside `SNTE`: 3 bytes with the lane id in the middle, i32 min, i32 max, u32 point count, points. **VERIFIED**.

| Lane id | Controller | Status |
|---|---|---|
| `0x01` | Mod wheel | VERIFIED (r16) |
| `0x0B` | Expression | VERIFIED (plan; Oct08) |
| `0x40` | Sustain | VERIFIED (mute-tests, Day 15) |
| `0xFF` | Pitch bend (-8192 to 8191; plays as -8191 to 8191) | VERIFIED (r16, r27) |
| `0xFD` | Channel pressure (aftertouch) | INFERRED (recorded pressure data; Reason's export resets it as aftertouch) |
| others | Not seen | UNKNOWN |

A point is: varint position delta (running, as for notes), i32 value, then **10 bytes: an 80-bit extended float** (sign and 15-bit exponent, 64-bit mantissa with an explicit integer bit): the curve toward the next point. 0 = straight. Reason's handle spans about -12 to 12; positive bends fast-first. **VERIFIED** (`curvature`; r26: 0.5, 12, -1, -12; Day 15's Swell).

How Reason's export draws curves (12 straight pieces, stepped every 1/32 beat) is in `reason_format.curved` and the plan. **VERIFIED** except an accepted gap at the strongest curves (plan, "Accepted gap").

### 4.7 Automation clips, tempo and signature

`SAUT`: u8 parameter at 5, i32 min at 6, i32 max at 10, u32 count at 14, points from 18 (same point format). **VERIFIED** (`decode_automation`).

- On the **Transport** track, parameter 0 is tempo (milli-BPM) and parameter 2 the time signature (value = denominator << 8 | numerator; `0x0403` = 3/4). **VERIFIED** (r17 to r20; the r20 test).
- On **device automation tracks** the same byte is a parameter of that track's device: DumDum's Maximizer and Filter 1 automation clips both have parameter 0. **VERIFIED** (this study). So the byte is per track, not a global "kind": 0 means tempo only on the Transport track.
- Tempo and signature live **in clips**. Outside any clip the **static** value applies: the Transport `TRSC` value when the parameter is automated, else the sequencer `TRDC` tempo at 23, else the metadata. `SONGTEMPO` is not the static tempo (Day 15: metadata 109000, export 104000). **VERIFIED** (plan, Phase 2; the owner confirmed with r17 and r19).
- Tempo clips cannot be curved (the owner). **VERIFIED** by the owner.

### 4.8 Blocks

- **Definitions:** `CAT SACT` (4.1).
- **Content:** clips under an `LCFM` whose `LCAI` is n belong to Block n, with Block-relative starts.
- **Placements:** `SBLK` clips on the Transport track's Blocks lane (`0x5D`): u16 Block number at 5 (0-based), i32 offset at 7 (where in the Block the placement starts; negative for a split placement's second half). The placement's own `SNIC` gives its song position, length and mute. **VERIFIED** (`_clip`; r24, mute-tests, dec2024-27-02).
- **Blocks switch:** third byte from the end of the sequencer `TRDC`: 1 in r24 and dec2024-27-02, 0 in SelfDef000, whose export plays no Block content. **VERIFIED** on those three; INFERRED in general.
- **Per-placement lane mutes** (shown hatched in Reason): `CAT SMGC` → one `FORM MGDF` per muted spot. `RLRF`: track index u32 at 5, lane kind u8 at 9, lane index among the track's note lanes i32 at 10 (-1 for pattern lanes). `RSRF`: the placement's record number on the Transport lane, u32 at 5, counting duplicates. **VERIFIED** (`block_mutes`; dec2024-27-02 against its export).

### 4.9 Loops

A looping clip repeats its first `loop` ticks, starting `loop offset` from the clip start, until the clip ends. **VERIFIED** (exports; `test_looping_clip_repeats_from_its_loop_offset`).

### 4.10 Pattern clips

`SPTN` (11 bytes). Seen: `bc 01 01 00 00 | 00 00 | ff fe 20 00` and `… | 00 00 | ff fc 40 00`. **INFERRED**, by analogy with `SBLK`: a u16 at 5 (pattern number?) and an i32 at 7 (an offset in ticks: -122880 = -8 beats, -245760 = -16 beats). The plan's "bank/pattern" description is not confirmed. The notes of a pattern live in the **pattern device** in the rack, not in the sequencer. **VERIFIED** (r21: the export has no notes for the pattern track; r22, converted to notes, does). Where and how the device stores its patterns is **UNKNOWN**.

### 4.11 Mute and solo: what is stored where

| Level | Where | Status |
|---|---|---|
| Note | `SNTE` flags bit 0 | VERIFIED |
| Clip | `SNIC`, the byte after the name | VERIFIED (r13) |
| Block placement | The placement clip's `SNIC` mute | VERIFIED |
| Block content at one placement, one lane | `CAT SMGC` | VERIFIED |
| Lane | `LANC`, the byte after the name | VERIFIED (r15) |
| Sequencer track mute | Track `TRDC` byte 13 | VERIFIED (r14) |
| Sequencer track solo | **Not stored**: r20s (solo from the sequencer track) differs from r20 in no `RS10` leaf chunk | VERIFIED (`reason_inspect diff r20 r20s` prints nothing) |
| Mixer channel solo | `PARM` of the track's `X15 Main Mixer Mix Channel` device: parameter 2 goes 0 → 1 | VERIFIED (r20x); the pair layout INFERRED |
| Mixer channel mute | Probably another parameter of the same device's `PARM` | UNKNOWN (no fixture; see 8.2) |

The reader imports note, clip, lane, placement and track mutes. It ignores the mixer by the owner's decision (plan, decision 2): a sequencer track drives a rack device and doesn't own a mixer channel one-to-one.

### 4.12 Time base and song length

- **VERIFIED**: 15360 ticks per quarter note. Reason's MIDI export uses the same resolution.
- Song length: `SONGLENGTHPPQ` (ticks) and `SONGLENGTHMS` in the metadata, mirrored in `SNGI` (4.1, 3.4). **INFERRED**: these follow the End marker, which bounds Reason's MIDI export.

**Confidence and evidence (section 4):** high for everything the reader uses: all 27 songs with exports render the exported notes (`test_r_series_matches_reason_midi_export`, `test_probe_song_round_trip_matches_reason_export`). Low for `SPTN` and the undecoded records.

---

## 5. Mapping to MIDI, and how it differs from Reason's export

The reader turns each visible stretch of a note clip into a MIDI clip holding what Reason plays there. The rules are in `reason_format.pieces` and the plan:

- loops written out;
- hidden notes and covered parts left out;
- later-starting clips cover earlier ones;
- a covering clip cuts sounding notes, but a clip's own end does not;
- a restruck pitch ends a ringing note;
- Block content rendered at each placement;
- controllers held from before the clip and returned to their resting value at the end;
- mod wheel and pitch bend drawn as 1/32-beat steps.

Lanes merge into their track, folders are flattened, and everything is on channel 1. Controller lanes map to CC 1, CC 11 and CC 64, pitch bend, and channel pressure.

Known differences from Reason's own MIDI export (**VERIFIED** unless marked):

| Difference | Evidence |
|---|---|
| The reader keeps muted clips, lanes and placements as muted clips; the export leaves them out | Plan, decision 2 |
| The reader keeps track mute; the export ignores track mute and solo | Plan |
| The export leaves out controllers the device doesn't accept (aftertouch on pianos, expression on the Seq Trigger player); the reader keeps them | Day01, Oct08 |
| The export writes **device parameter automation as CCs**; the reader skips it | ChanEQ CC 29, Gain CC 40, Day 15's PAD as CC 64 (plan); **DumDum: Maximizer → CC 7 (515 events), Filter 1 → CC 74 (391 events)**, from 2-point `SAUT` clips at beat 288 to 312, stepped every 1/32 beat, with the static value at beat 0 and again at the clip end (this study) |
| The export writes **CC 3 at each pattern clip start** on pattern tracks, plus one at the song end, all value 0 in DumDum; the reader writes nothing for pattern lanes | DumDum: `MAIN GROOVE` 24 events = 23 song-level pattern clips + 1 at beat 312; `GROOVE +` 22 = 21 + 1 (this study). What the value means is INFERRED (a pattern select) |
| The export leaves out values equal to the current one; the reader keeps them so each clip stands alone | Plan |
| The strongest curves (k about 12) differ by up to one mod-wheel step or 64 of 16383 bend | Plan, "Accepted gap"; `test_strong_curves_are_close` |
| The export truncates tempo to whole microseconds per beat; the reader does the same | Plan |
| The export adds note-less `Transport` and `Master Section` tracks | INTEROP_FINDINGS |
| Hidden notes and loop structure can't be recovered after import | Plan, decision 1 |

---

## 6. How Reason writes the file on save

From `docs/plans/mirror-mode.md`, step 0 (owner-run on the development MacBook, 2026-11-22; Reason version not recorded; files `Aug01-01-03.reason` 3.1 MB and `DumDum001-9_mix2(14)-folders.reason` 9.4 MB; folder polled every 50 ms):

- **In place.** The inode never changed, and no temp, backup or extra files appeared. **VERIFIED** (step 0 log).
- **Fast.** Each write showed as a single change within one 50 ms poll at these sizes. Because it is in place, a reader could in principle catch a write half-done. **VERIFIED** observation; the risk is INFERRED.
- **mtime-only changes happen:** Aug01 changed its mtime four times with the size unchanged; DumDum once, then once more with a size change (9,437,236 → 8,650,804 bytes, about five seconds later). **VERIFIED**. Whether Reason rewrote identical bytes or only touched the file is **UNKNOWN**.
- **Combined with section 2** (**INFERRED**): a save writes new song pages and a new index page into free pages, rewrites one header slot, and sometimes shortens the file. **UNKNOWN**: the order of these writes (the safe order would be data, then index, then slot) and whether a reader racing a save can see a slot that names an index not yet written. A torn song stream would fail its `Hash`.

**A consequence worth knowing** (**INFERRED**): a reader that picks the highest index page, as `current_song` does today, gets the **previous** save whenever the new one lands on the lower page set. In Aug01 that is every other save. Whether this accounts for all of the misses reported in the mirror-mode studio run (`docs/plans/mirror-mode.md`, "Diagnostics") is not established here.

---

## 7. Open question 1 (top priority): which saved copy is current?

### 7.1 The question

A file often holds two complete, hash-verified songs. Reason opens the right one, so the information must be in the file. The reader takes "the verified copy whose index is on the highest page" (`reason_format.current_song`). That rule was adopted because it fitted every case known at the time (plan, Phase 1).

### 7.2 Answer found: the header's two slots, higher generation wins

The 52-byte header holds two slots (section 2.2), each `{u64 generation, u64 index page, u16 CRC-16/XMODEM}`. **The current copy is the one indexed by the slot with the higher generation.** Each save writes the next generation into the other slot, pointing at the new index page.

Status: **VERIFIED against all available ground truth; not yet confirmed by Reason itself** (7.6, experiment 1 is the decisive test). Confidence: high.

### 7.3 The Aug01 controlled saves

The owner moved one muted clip on track `Ambient Piano - Upliftin Ch5` and saved after each move. Copy A = index page 6, copy B = index page 11.

| State | Clip start | Newest copy (owner's observation) | Slot 0 (gen, page, crc) | Slot 1 (gen, page, crc) | Higher-generation slot names | Highest-page rule picks |
|---|---|---|---|---|---|---|
| Committed in git | beat 4 in both copies | (both copies identical in notes) | 2, 6, `a6a1` | 3, 11, `9c2f` | page 11 | page 11 |
| Bar 10 | beat 36 | B (page 11) | 4, 6 (reported) | not recorded; 5 by the pattern | page 11 (if 5) | page 11 |
| Bar 12 | beat 44 | **A (page 6)** | 6, 6, `3a4e` (reported) | 5, 11, `c6a7` (reported) | **page 6 ✓** | page 11 ✗ |
| Bar 14 | beat 52 | B (page 11) | 6, 6, `3a4e` (reported) | 7, 11, `00c0` (reported) | page 11 ✓ | page 11 ✓ |
| Bar 16 | beat 60 | **A (page 6)** | 8, 6, `4939` | 7, 11, `00c0` | **page 6 ✓** | page 11 ✗ |

- The committed and bar 16 rows were checked on the scratch files for this document. The bar 12 and bar 14 headers were reported by the session that ran the saves; their CRCs are consistent with the rule (`3a4e` = CRC of (6, 6), `c6a7` = CRC of (5, 11), which also occurs in `dec2024-28-01`, `00c0` = CRC of (7, 11)).
- **VERIFIED** on `aug_after_bar16.reason`: copy A (page 6) has the clip at **beat 60**, copy B (page 11) at **beat 52**. Both are hash-verified, 1,071,908 bytes.
- **VERIFIED**: the two song streams differ in exactly three regions:
  1. the clip start (`0x0E1000` = 921600 ticks = 60 beats, against `0x0C3000` = 52 beats);
  2. an ISO timestamp inside the Pianoteq device state: copy A `…23:12:44.076Z`, copy B `…23:11:19.861Z`. Copy A's is later, an independent check that page 6 is newer, but it is Pianoteq's own data and not general;
  3. the `Hash`.

### 7.4 Hypotheses tested

| # | Hypothesis | Result | Evidence |
|---|---|---|---|
| H1 | The verified copy on the highest index page is current | **Refuted** | Aug01 bar 16 file (and bar 12 as reported): the newest copy is on page 6, below page 11 |
| H2 | The u64 at offset 24 (`index_hint`) names the current index | **Refuted** | It is slot 0's page. It stayed at 6 throughout Aug01 while the newest alternated between 6 and 11 |
| H3 | The u64 at offset 16 (`a`) alone orders the copies | **Refuted** as a standalone rule; **explained** | It is slot 0's generation (2, 4, 6, 6, 8 in Aug01). It increases only when slot 0 is written; it means something only when compared with slot 1's generation at offset 34 |
| H4 | The header holds two `{generation, page, check}` slots; the higher generation is current | **Survives every test** | (a) CRC-16/XMODEM matches all 208 slots. (b) The generations differ by exactly 1 in all 104 files, with slot 0 even and slot 1 odd. (c) The higher slot always names a valid index with stream 1, hash-verified in every `RS1250`/`RS1300` file. (d) Aug01: matches bar 10, 12, 14 and 16. (e) r13 and r22, the two-copy fixtures where only one copy matches Reason's export: the higher slot names that copy (r13 page 7, r22 page 9). (f) Save As chains (2.6): the higher slot names the edited copy, not the one identical to the previous file. (g) Files mixing versions: the higher slot names the newer program version every time (Day 1, Day 15 and T004 Self in `Reason13/`, an `RS1200` or `RS1250` copy → `RS1300`; `Grandfathered/2011/vocoder-test-007d(14)` 14.0.0 → 14.1.0; Jun14 14.0.1 → 14.1.0; `Reason9/T004…-3` 9.2.0 → 10.2.0; `Reason11/Day 15` 11.1.0 → 11.2.1; PianoGuitarDrums `Reason13/` `RS1200` → `RS1300`). (h) The owner's note that r04 opens with velocity 64 (plan, question 4): the higher slot names page 7, velocity 64. (i) Pianoteq timestamp in Aug01 bar 16 |
| H5 | The index page carries a sequence number | **Refuted** | Aug01's two index pages are identical apart from their page lists (2.4) |
| H6 | A Reason-level save timestamp or counter in the song stream decides it | **Refuted for Aug01** (no such field differs) | The only differences between the bar 14 and bar 16 copies are the clip, a Pianoteq-specific timestamp and the Hash. r08 and r09 song streams are byte-identical |
| H7 | Something in the `0xFF`/`0xFE` regions or the end markers | **Refuted** | The markers are constant (`c0cac01a`, `b0bafe77`); page tails hold leftover bytes that don't correlate with order (2.3) |
| H8 | The unexplained values at offsets 32 to 51 (`a6a1…`, `0x000bc6a7`, `0x000b00c0`, `0x000b9c2f`) encode a generation | **Explained** | Bytes 32–33 are slot 0's CRC; bytes 34–41 slot 1's generation; bytes 42–49 slot 1's page (`0x0b` = 11); bytes 50–51 slot 1's CRC (`c6a7`, `00c0`, `9c2f`). Read as big-endian u32s they had seemed to be counts with odd high halves |
| H9 | Reason picks a copy by validity alone (for example the only one whose hash verifies) | **Insufficient**, though validity checks likely apply as well | In 35 files both copies verify. Validation can't choose between them |

Before this study, the old rule matched every two-copy fixture because those were mostly Save As files with one save after it: generation 3 lands on the higher page set. Many files do have the newest copy on the lower index page (for example `Nov01-01-01`, `Aug02-01-00`, `mute-tests`, `r07`). But there the other slot names a page past the end of the file (28 files), or its index fails validation (`Jun06-01-03`), so the highest *verified* copy was still the newest and both rules agreed. The Aug01 bar 12 and bar 16 states are the first files seen where both copies are intact and the newest is on the lower page.

### 7.5 Not yet tested

1. **That Reason itself uses the generations.** All the evidence above agrees with the rule, but nothing yet shows that Reason reads it, rather than following some other signal that happens to agree. A crafted file opened in Reason settles it (7.6, experiments 1 and 2).
2. **Reason's fallback.** If the higher slot's CRC fails, or its index or song is damaged (a torn save), does Reason fall back to the other slot, refuse the file, or repair it? This is **UNKNOWN**. Classic double-buffered headers fall back, which would be **INFERRED** behaviour only.
3. **Whether Reason checks the `Hash`** when opening.
4. **The write order within a save**, and so what a reader can see mid-save.
5. **When Reason shortens the file** (2.6, point 4).
6. **What Save As does:** a fresh container (as the bytes suggest) or a copy of the old file.
7. **Whether an mtime-only change** (step 0) rewrites the header or anything else.

### 7.6 Experiments for the owner

Each uses a scratch copy of a song, never a project in use. Experiments 1 and 2 need files prepared by a developer from a copy; a developer can make them on request. Readers in this project never modify project files; these are hand-made test files.

1. **Decisive test of the rule.** Take a copy of `aug_after_bar16.reason` (slot 0 = generation 8, page 6, clip at bar 16; slot 1 = generation 7, page 11, clip at bar 14). Make a test copy whose slot 1 generation is set to 9, with its CRC recomputed. Open it in Reason. The rule predicts the clip at **bar 14**. Opening the untouched copy should show bar 16.
2. **Fallback tests**, from the same base, one change each:
   - (a) break slot 0's CRC only (generation 8 kept);
   - (b) keep the header but damage one byte inside copy A's song stream (its `Hash` then fails);
   - (c) make slot 0 name a page that isn't an index.

   For each, note whether Reason opens bar 14, bar 16 or refuses. This shows whether Reason validates the CRC and the `Hash`, and whether it falls back to the older slot.
3. **Live alternation, without any crafted file.** Save As a small song to a new name, then do four saves, each moving one clip to a known bar. After each save, duplicate the file in Finder (`-s1` … `-s4`) and send the duplicates. Predicted: slots step `(2, 3)` → `(4, 3)` → `(4, 5)` → `(6, 5)` … with the newest copy alternating page sets, and each duplicate opening in Reason at the bar just saved.
4. **Save with no edit.** Open a song, save without changing anything, and duplicate before and after. Does the generation step and the copy move? r08/r09 suggest the song bytes stay the same.
5. **Open and close without saving.** Duplicate before opening and after closing. Do the header or any page change (the mtime-only changes in step 0)?
6. **Save As.** Save As an unedited song to a new name and duplicate it at once. Predicted: slot 1 = `(1, page 0)`, page 0 an empty index, slot 0 = `(2, …)`.
7. **Shortening.** In a song with an embedded sample, delete the sample's device and save; then save twice more. Duplicate after each save. This shows when the file shrinks and whether a stale slot then points past the end.

### 7.7 Verdict

The rule Reason uses is almost certainly **"the header slot with the higher generation names the current index page."** The format is a classic two-slot ("ping-pong") header with a CRC per slot. Every fixture and every known ordering agrees with it, the highest-page rule is refuted by the bar 16 file, and every previously unexplained header byte is now accounted for. What remains unconfirmed is that Reason reads it this way, and how Reason behaves when the newer slot or its copy is damaged. Experiments 1 and 2 settle both.

---

## 8. Other open questions

| # | Question | What would settle it |
|---|---|---|
| 8.1 | **`RS1250` (Reason 12.6) is plain and hash-verified** but refused by the reader | An `RS1250` song with a Reason 12.6 MIDI export, compared with the decode; then the owner's decision whether to accept 12.6 |
| 8.2 | **Mixer mute and solo.** Solo is parameter 2 in the mix channel device's `PARM` (r20x); mute is not located. The reader ignores the mixer by decision | Two saves of one song differing only in a mixer channel's mute, run through `reason_inspect diff`; and the `PARM` layout decoded |
| 8.3 | **DumDum's extra CC data** (ROADMAP, 2026-11-21) | **Largely explained** (section 5): CC 7 and CC 74 come from device parameter automation clips (`0x5B` lanes, `SAUT`) on the Maximizer and Filter 1 tracks; CC 3 marks pattern clip starts on pattern tracks. Still unknown: where Reason gets the CC number for a device parameter (probably each device's fixed MIDI implementation, not the song), and what the CC 3 value means. Settle by comparing a few devices' automation exports and a pattern track whose clips use different patterns |
| 8.4 | **Pattern devices:** how Redrum, Matrix and similar devices store their patterns in `DEVI`, and the `SPTN` layout | Fixtures with one pattern device whose patterns differ by one step each, plus converted-to-notes exports (as r21/r22) |
| 8.5 | **When the file is shortened** (2.6) | Experiment 7.6.7 |
| 8.6 | **Save As behaviour** (fresh container or copy) | Experiment 7.6.6 |
| 8.7 | **Undecoded fields:** `SNIC` bytes 13 to 20 and the 3 bytes after the mute; `TRDC` byte 18 (colour?); `LASC`; `SADC`'s trailing byte; `SNGI` beyond byte 18; `APPV`, `HEAD`, `GLOB`, `SARF`, `PEAK`, `RACK`, `SQGM`, `SQUG`, `STRE`, `STRM`, `MRBC`, `SLKL`, `SOVL`, `RCTL`, `PLCL`, `PLAN`; the `<b2>` byte of record headers | One-change fixtures, as for the r-series, and `reason_inspect diff` |
| 8.8 | **Audio lanes** (`0x5C`, `FORM SASF`) are inferred, not checked on a fixture | A song with one audio clip |
| 8.9 | **Lane ids other than the five known** (`0xFD` is inferred) | A clip with each performance controller recorded |
| 8.10 | **Embedded sample streams:** layout beyond the first bytes | Not needed for MIDI; only if samples are ever wanted |
| 8.11 | **The strongest-curve gap** (k ≈ 12) | Plan's proposed r28 fixture |
| 8.12 | **Controller #254 lane** that Reason adds when importing a channel-overridden file (INTEROP_FINDINGS) | About Reason's MIDI import, not this format; deferred by agreement |
| 8.13 | **Test fixtures don't model the slots.** The synthetic builder in `tests/test_reason_format.py` (`container`) writes slot 0 with a zero CRC and slot 1 as zeros. A future reader that checks slots will need the builder updated | Noted for whoever implements a change; not a format question |

---

## Appendix: tools for checking this document

- `tools/reason_inspect.py copies FILE` lists the index pages and song copies. It prints the header as `a` (slot 0 generation) and `index_hint` (slot 0 page) only. Slot 1 is bytes 34 to 51; read it with `struct.unpack('>QQH', header[34:52])`.
- CRC check for a slot: CRC-16, polynomial `0x1021`, initial 0, no reflection, no final XOR, over the slot's 16 bytes; compare with the u16 that follows.
- `tools/reason_inspect.py diff A B` lists the `RS10` leaf chunks that differ between the current songs of two files. It doesn't compare the two copies inside one file, the metadata or the `Hash`.
