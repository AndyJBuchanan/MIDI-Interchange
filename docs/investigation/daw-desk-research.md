# Desk research: native readers for Logic, Bitwig, Reaper, Ableton and FL Studio

Status: web research only (2026-11-15), no files examined. **How to read the verdicts:** public sources are only one input. Two others count as evidence of viability: (1) **our own probing method has worked** (Reason, a format with no public documentation, decoded note for note against its own MIDI exports from a short differential series; Cubase before it), so "nothing documented" is not a blocker; (2) **commercial tools that read a format show it can be read.** **Corrected the same day:** the first pass missed [DAWbro](https://dawbro.com), a commercial app that reads these formats natively (see [below](#dawbro-evidence-that-native-readers-are-possible)); the Bitwig verdict changed. Everything here is from public sources and is unverified until fixtures confirm it. It extends the summary table of [direct-daw-import.md](../plans/0.4.0/direct-daw-import.md). Covers Logic and Bitwig first, then Reaper, Ableton and FL Studio. Method for the next step: the [Reason plan](../plans/0.4.0/reason-import.md) (probe, then decode against the DAW's own MIDI export).

**Priorities (user, 2026-11-15):** the user actually uses **Reason and Cubase**, both done. DAWproject was a proof of concept. **Logic** may be worth doing but is secondary. **FL Studio** (the user has 26 but doesn't use it) and the rest are low priority; the user can't say which versions of Reaper or Ableton they have. So nothing below is scheduled; it is a reference for when a DAW is picked up. The ranking by effort in [Suggested order](#suggested-order) is about difficulty, not priority.

## Logic Pro (`.logicx`)

**Verdict: feasible, medium effort; the best-documented native format of the remaining DAWs, and also read by DAWbro. The risks are version drift and "what is current".**

What the sources add to the existing plan:

| Source | Licence | What it gives us | Limits |
|---|---|---|---|
| [LogicProFormatWriter](https://github.com/jonkubis/LogicProFormatWriter) | MIT | `PROJECTDATA_FORMAT.md`: record framing, tempo, meter and marker encodings, audio-region and MIDI-note layouts. A *writer*, so its layouts are ones it can reproduce. | Tied to **one unnamed Logic version**; the author warns a new release may change the layout. 7 commits. No mention of track mute or alternatives. |
| [logic2ableton notes](https://github.com/Evilander/logic2ableton/blob/master/docs/reverse-engineering-logic-pro-midi.md) | MIT | Note record found by signature; 960 ticks per quarter note. | Signature scanning (false matches); relative positions only; no channel. Three Apple demo projects. |
| [lpx-explorer / lpx-parser](https://github.com/rhydlewis/lpx-explorer) | **GPL-3.0** | Metadata (key, BPM, signature), tracks (kind, names), regions, plug-in references. Roughly 150 projects tested. Notes quirks that matter to us: **undo-history duplicates and phantom plug-ins from other alternatives show up in the data.** | Whether it decodes MIDI notes is not stated. GPL: read it to learn, do not copy code. macOS-only app. Test count is a README placeholder. |
| [bravoh-daw](https://docs.rs/crate/bravoh-daw/0.1.0) | MIT | A deliberately conservative parser (BPM, signature, tracks, markers, plug-ins). | **No MIDI**: it reports none for Logic and drops fields it can't read dependably. Not a source for notes. |
| [logicx-analyzer](https://github.com/geoffmyers/logicx-analyzer) | not checked | Chunk scanning on Logic 10/11 projects. | Not read in this pass. |

Findings that change the plan:

1. **No parser found decodes MIDI notes with absolute positions, mute, and the current alternative together.** LogicProFormatWriter is the only byte-level MIDI spec, and it is version-bound. Expect our own differential series, as for Reason.
2. **"Current arrangement only" is the risk.** The one tool with real-world mileage (lpx-explorer) reports data from *other alternatives* and the undo history leaking into what it reads. Our reader must pick the current alternative and ignore stale records. This needs fixtures that save a project with an extra alternative and an edited-then-undone region.
3. **Version drift is real.** Both writers warn the layout may change per release. Support only the version the user has, with a clean "unsupported version" message, as for Cubase and Reason.
4. **Logic has no DAWproject export** (existing plan; several 2026 sources agree, mostly vendors selling converters). Logic's own **MIDI export** exists as a test reference, as with Reason.
5. **Legal:** MIT sources can be read and reused with attribution. The GPL lpx-explorer can be read for understanding only. Studying files saved by the user's own Logic is the same position as Reason and Cubase; the Ghidra forum approach is out.

**Suggested probe (before committing):** save from the user's Logic, `ProjectData` unmodified: (L1) empty, (L2) one note, (L3) notes with velocity/pitch/length variations, (L4) a muted region and a muted track, (L5) two alternatives with different content, (L6) a tempo and a signature change, (L7) a region split and a loop, plus Logic's MIDI export of each. Questions for the user: which Logic version(s); is a Logic 11/12 split likely.

## DAWbro: evidence that native readers are possible

[DAWbro](https://dawbro.com) (closed source, EUR 35, macOS and Windows, reads files locally) indexes a library of projects and lets you search, play and drag out MIDI clips. It lists **20 formats, including Bitwig `.bwproject`, Logic `.logicx`, Reason (to 14), Cubase `.cpr`, Reaper, Ableton, FL Studio and Studio One.** The user has used it and confirms it finds the MIDI inside Bitwig projects. So reading the MIDI in a native Bitwig file is demonstrably possible, and my earlier "low feasibility" came only from the absence of *open* work.

What it does and doesn't tell us:
- **It is a clip database, by design.** It shows a note picture, plays it, and carries tempo and length when a clip is dragged out. It knows where in the project each clip was found but doesn't use that (user, who knows the author and sends him Cubase files that fail). It states it does not transfer arrangement, mixer or automation, and doesn't mention mute. Positions, mute and whole-song import are what our reader adds, so it shows the *clip data* is readable but not that the arrangement is; that part is ours to probe.
- **It is a possible reference.** For a Bitwig or Logic fixture, the clips it shows (and a dragged-out MIDI clip) can be compared with what our reader decodes, in the way Reason's own MIDI export was.
- **We don't inspect it.** Same rule as the DAWs: we study project files the user saved, never the applications (no decompiling).
- **Not a dependency.** It is commercial and closed; nothing here relies on it.

## Bitwig (`.bwproject`)

**Verdict (revised): probably feasible, to be proven by a probe like Reason's. Reasons for confidence: the commercial reader above, and our method's record. DAWproject remains a working fallback.**

- **The native format is proprietary and undocumented.** Bitwig has not published it, and one 2026 guide notes tools refuse it rather than guess ([Doseedo](https://doseedo.com/guides/bitwig-mcp-server), a vendor).
- **What exists is thin.** [bwEdit-Python](https://github.com/jaxter184/bwEdit-Python) (licence not stated): the author reports being "unsuccessful in my attempts to document stuff more", and in v0.3 `.bwproject` "still doesn't work, but lists all the tracks and their names/types." [Music-Organiser-Rust](https://github.com/Silkie86/Music-Organiser-Rust/pull/12) (licence not stated) decodes a `BtWg` header, metadata and an object tree and extracts track names and **one clip per note clip at 960 PPQ**, tested on nine projects. Its note/position/mute decoding is not described in what was readable.
- **The file shape is unclear.** Sources conflict on whether there is a zip wrapper after the `BtWg` object tree. Needs a real file.
- **Bitwig already gives us what we need through DAWproject**, which it co-authored. `File ▸ Export DAWproject…` (Bitwig 5.0.9+) and our [DAWproject reader](../plans/0.4.0/dawproject-import.md) carries notes, tempo, signature and markers today. Caveat from the exercise above: it is an *export*, not the saved file, so it fails the "native files, no export step" aim; but for Bitwig users it is a single menu command and the format is an open spec. The FAQ doesn't state whether clip enable/loops survive. Our reader reads `enable` and loops, so a Bitwig fixture would settle it.

**Recommendation (revised):** run a probe (below). In parallel, check the DAWproject route with one or two real Bitwig exports (a muted clip, a loop) so Bitwig users have something that works now.

**Suggested probe:** from the user's Bitwig, save (B1) empty, (B2) one note, (B3) varied pitch, velocity, length, (B4) a muted clip and a muted track, (B5) a tempo and a signature change, (B6) a clip split and a loop, a second clip on the same track overlapping the first, plus the DAWproject export of each (the only open reference Bitwig has) and DAWbro's view of the MIDI. First questions: is there a zip wrapper after the `BtWg` object tree, and where notes, positions and the clip-enable flag sit in it. Questions for the user: Bitwig version(s); does DAWbro's drag-out MIDI come with absolute or clip-relative positions?

## Reaper (`.rpp`)

**Verdict: the easiest native format of all; plain text, free to test, and the MIDI event syntax is visible in sample files. Feasible with low effort.**

- **Format:** plain, human-readable text, nested `<CHUNK ... >` blocks. A real sample (a project saved by REAPER 5.77, [ddf/evaluator](https://github.com/ddf/evaluator/blob/main/reaper/dev_evaluator.RPP)) shows a MIDI item exactly as it is stored:
  ```
  <ITEM
  POSITION 0
  LENGTH 128
  LOOP 1
  SOFFS 0 0
  MUTE 0
  <SOURCE MIDI
  HASDATA 1 960 QN
  POOLEDEVTS {59A59CCA-...}
  e 0 90 30 7f
  e 122880 80 30 00
  E 0 b0 7b 00
  ```
  So: **960 ticks per quarter note**; event lines are *offset (ticks), status, data bytes in hex*; the item has `POSITION`, `LENGTH`, `LOOP`, `SOFFS` (start offset) and an item-level **`MUTE`** line; the track has `MUTESOLO` (mute, solo, ...). The offset on each event line is almost certainly *from the previous event* (the note-off's 122880 is far larger than any position in the item, while the next line restarts at 0), but that and the `e` versus `E` distinction (probably selected or not) are inferences, not documented. Muted *notes* are probably a variant prefix; to check.
- **Shared copies:** `POOLEDEVTS {guid}` marks pooled MIDI items (edits shared between copies), which maps onto our shared event lists. To verify against a fixture.
- **Timing:** item `POSITION` and `LENGTH` are in seconds (general knowledge, not seen in these sources), so converting to beats needs the tempo map (`TEMPO`, tempo envelope); items can also be beat-attached. A source of conversion bugs; Reason and Cubase taught us to test it against a ramp.
- **Prior work:**
  - [`rpp`](https://pypi.org/project/rpp/) (BSD-3, Perlence): parses RPP text to a tree and back; last release 0.5 in April 2023, beta, one maintainer; doesn't say it understands MIDI items. Reading the tree is a few lines of our own, so we may not need it.
  - [`rppxml`](https://pypi.org/project/rppxml/): couldn't be read this pass.
  - A REAPER MCP server and a note-clip exporter ([toneflix PR](https://github.com/toneflix/studio/pull/40)) exist and write the same `<SOURCE MIDI` / `HASDATA 1 960 QN` form; the exporter says ticks follow the tempo map.
  - [DawVert](https://github.com/SatyrDiamond/DawVert) lists Reaper only as an *output*.
  - **DAWbro lists Reaper**, so a commercial reader exists.
- **Reference:** Reaper exports MIDI itself (item or project), which gives the usual comparison; Reaper is also free to evaluate, so fixtures are cheap. The plan already notes Reaper hasn't been tested with this app (DESIGN_NOTES risk 3).
- **Reaper can also import and export other formats** (DAWproject only through third-party tools per the existing plan).
- **Hard parts to expect:** media items that reference `.mid` files on disk; takes and comping (the active take); tempo envelopes; items with `LOOP` and `SOFFS`.

## Ableton Live (`.als`)

**Verdict: feasible, low to medium effort. Plain gzipped XML with documented MIDI structure. The risks are version drift (Live 11 vs 12.x), and getting the *arrangement* clips and clip mute right (neither was confirmed in these sources).**

- **Format:** gzip-compressed XML (no encryption). Ableton publishes no spec; the best community document is [ableton-als-structure](https://tangled.org/aesthetic.computer/core/blob/main/docs/ableton-als-structure.md), analysed from **Live 12.1.5 Suite**:
  - `<MidiClip>` has `Time` and `Duration`; loop data in `<Loop>` (`LoopStart`, `LoopEnd`, `StartRelative`, `LoopOn`, `OutMarker`, `HiddenLoopStart/End`).
  - Notes: `<MidiKey><Notes><KeyTrack><Notes><MidiNote Time Duration Velocity OffVelocity IsEnabled>`; **pitch is implied by the KeyTrack**, times in **beats**. `IsEnabled` is note mute.
  - Tempo: `<MasterTrack>...<Mixer><Tempo><Manual Value>`; time signature: `<TimeSignature>` in the same mixer; `<Scenes>` carry their own tempo and signature (session view).
- **Not confirmed by these sources (to verify with fixtures):** where **arrangement** clips sit (that doc shows only session scenes and `<ArrangerAutomation><Events>` as "automation events with timing"; from general knowledge arrangement clips live under each track's `MainSequencer` in an arranger events list, which must be told apart from session clip slots), the **clip mute** flag (general knowledge: a `Disabled` value on the clip), **track mute** (general knowledge: the mixer's `Speaker` value), **locators**, and tempo automation.
- **Prior work:**
  - [AbleSharp](https://github.com/theokyr/ablesharp) (MIT, .NET): reads and writes `.als` for **Live 11 to 12.1**; 85 commits, no releases; doesn't state MIDI/clip/mute support.
  - [pyableton](https://pypi.org/project/pyableton) (Python; saves as MIDI), [alsmuse](https://pypi.org/project/alsmuse/), and an [ALS to MIDI Pythonista script](https://abwiki.loopypro.com/pythonista_als_to_midifile_converter). The `loive` tool was tested only on Live 8.1.3 and 9.0.4.
  - [DawVert](https://github.com/SatyrDiamond/DawVert) (GPL-3.0) reads **Ableton Live 11**.
  - **DAWbro lists Ableton Live (including pre-Live 8)**, so a commercial reader exists across versions.
  - `daw-schemas` reports **1,798 element types** across the sets it analysed: the full schema is large, but we only need a small part.
- **The SDK you remembered:** Ableton launched the **Extensions SDK** in June 2026 ([blog](https://www.ableton.com/en/blog/introducing-extensions-sdk)): free, public beta, JavaScript on Node.js, for **Live 12.4.5 or later, Suite only**, macOS and Windows. Extensions run *alongside Live*, triggered from the Set, and can read and edit tracks, clips, parameters, MIDI and tempo. It **does not say it can read a `.als` from disk**, needs Live running (Suite beta), and so doesn't give us a standalone reader; it is not a route for this app. Ableton's other SDKs don't fit either: the Link SDK is tempo sync, and the export SDK is for iOS apps (the [Sets exported by iOS apps](https://help.ableton.com/hc/en-us/articles/206905710) page). The Live Object Model used by Max for Live and remote scripts is officially undocumented.
- **No DAWproject support found for Ableton** in 2026 sources (nor for FL Studio or Logic).
- **Reference:** Live exports MIDI per clip, not whole arrangements, so ground truth is less convenient than Reason's; per-clip MIDI plus the fixture design (known notes) would do.
- **Hard parts to expect:** distinguishing arrangement from session clips; unrolling clip loops and `StartRelative`; warped audio is out of scope; group tracks; return and master tracks.

## FL Studio (`.flp`)

**Verdict: feasible but the hardest and most fragile of the five; the format shifts with versions, the open parsers have fallen behind, and FL's data model (notes in patterns, patterns placed on a playlist) means the reader has to *render* the arrangement. Do it last, and only with fixtures from the user's version.**

- **Format:** a proprietary, undocumented binary: an `FLhd` header chunk (format, channel count, PPQ) then an `FLdt` chunk of **type-length-value events**, with type IDs 0-63 holding 1 byte, 64-127 2 bytes, 128-191 4 bytes and 192-255 a length-prefixed (varint) value, containing structs and sub-events ([PyFLP's format notes](https://pyflp.readthedocs.io/en/latest/architecture/flp-format.html)). Its own page calls the format messy and "essentially undocumented", and says every FL version changes it.
- **Prior work:**
  - [PyFLP](https://github.com/demberto/PyFLP) (GPL-3.0): the main open parser. Reads channel rack, mixer, **patterns with notes**, the **playlist**, time markers and plug-ins; supports writing. **Upstream unmaintained since mid-2023.** The maintenance badge says 2023.
  - [A fork](https://github.com/Meowrium/PyFLP) (GPL-3.0, 2-4 stars, tested on FL 26.1.1 and 20.5 saves) says upstream **cannot parse FL 24 / 25 / 26**, and fixes it: event `0xAC` became a varint-length field in FL 26; playlist items now come as 80-byte (FL 2024/25) and 88-byte (FL 26) records alongside the older 32- and 60-byte layouts; a header `NotesEvent` in FL 26 shows up as a phantom pattern. This is the fork author's own claim.
  - [`flpkit`](https://pypi.org/project/flpkit/): patches only the bytes it needs, preserving the rest.
  - [DawVert](https://github.com/SatyrDiamond/DawVert) (GPL-3.0) reads `.flp`; whether it recovers notes and arrangement wasn't stated.
  - **DAWbro lists FL Studio, including FruityLoops**, so a commercial reader exists.
- **Licence consequence:** the open FLP parsers are **GPL-3.0**: read them to learn the event layout; do not copy code into this app.
- **What a reader must do (general knowledge, unverified):** collect each pattern's notes, then place pattern instances from the **playlist** (with start, length, trims, mute per item and per playlist track) onto a timeline. That is the same shape of problem as Reason's Blocks; Reason taught us the rendering rules need a MIDI export per fixture to pin down. Step-sequencer data is notes in a pattern. Audio clips and automation clips share the playlist and must be reported as skipped.
- **Version drift is the headline risk.** Support only the version(s) the user has, with a clean unsupported-version message.
- **Reference:** FL exports MIDI itself (generally per pattern or per channel, so how it renders an arrangement is a question for the fixtures). Trial-mode FL can't reopen its own saved projects, but our reader never needs to; check whether the user has a licensed version.
- Questions for the user: which FL version(s) (24, 25, 26?); do they use patterns and the playlist the usual way.

## Suggested order

Ranked by effort and risk, easiest first (all subject to a probe, as for Reason):

1. **Reaper**: plain text with visible MIDI syntax; free fixtures; biggest unknown is tempo and time units.
2. **Ableton**: gzip XML with community docs; risk is arrangement versus session clips and clip mute location.
3. **Logic** and **Bitwig**: both need probes. Logic has the better public prior work (version-bound). Bitwig has less prior work, but DAWproject gives it a reference export and a fallback. Logic's risk is version drift and "current alternative"; Bitwig's is the unknown container.
4. **FL Studio**: binary, drifting, GPL-only prior work, arrangement must be rendered from patterns and playlist.

## Sources

- [DAWbro](https://dawbro.com), [ddf/evaluator sample RPP](https://github.com/ddf/evaluator/blob/main/reaper/dev_evaluator.RPP), [rpp](https://pypi.org/project/rpp/), [Ableton Extensions SDK](https://www.ableton.com/en/blog/introducing-extensions-sdk), [ableton-als-structure](https://tangled.org/aesthetic.computer/core/blob/main/docs/ableton-als-structure.md), [AbleSharp](https://github.com/theokyr/ablesharp), [PyFLP](https://github.com/demberto/PyFLP), [PyFLP fork](https://github.com/Meowrium/PyFLP), [DawVert](https://github.com/SatyrDiamond/DawVert)
- [LogicProFormatWriter](https://github.com/jonkubis/LogicProFormatWriter), [bravoh-daw](https://docs.rs/crate/bravoh-daw/0.1.0), [lpx-explorer](https://github.com/rhydlewis/lpx-explorer), [logicx-analyzer](https://github.com/geoffmyers/logicx-analyzer)
- [bwEdit-Python](https://github.com/jaxter184/bwEdit-Python), [Music-Organiser-Rust PR 12](https://github.com/Silkie86/Music-Organiser-Rust/pull/12), [Bitwig DAWproject FAQ](https://www.bitwig.com/support/technical_support/system-requirements-62/), [Bitwig: exporting projects](https://www.bitwig.com/userguide/latest/exporting_projects), [DAWproject spec](https://github.com/bitwig/dawproject)
