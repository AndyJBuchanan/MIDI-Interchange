# Plan: direct DAW project import (investigation)

Status: **initial research gathered; target DAWs and first new reader agreed** (2026-11-14). DAWproject will validate the pluggable import model alongside MIDI. Detailed implementation and native-reader feasibility remain to be scoped. This document collects the web research, observations on the current code, and open questions, ready for fixtures.

Branch: `feature/direct-daw-import`, created from `release/0.4.0`. Its PR will target `release/0.4.0`, following [the branching rules](../RELEASING.md#branches).

The scope and rules are in the [roadmap entry](../ROADMAP.md) ("Investigate direct DAW project import"). They aren't repeated here. In short: drop a saved project in, get the current arrangement as MIDI through the normal import, preserve track and clip mute, and never modify the project.

Agreed target DAWs: **Cubase, Reason, Logic, Reaper, Bitwig, Ableton and FL Studio**. FL Studio support is subject to native-format feasibility investigation. Studio One is deferred because it is not currently available for testing. Bitwig, Ableton and FL Studio native formats still need investigation; their absence from the initial research below is not a scope exclusion. DAWproject is the first new reader, primarily to validate the shared importer design, and also useful as a format in its own right.

## The point: native files, not exports

The aim is to read the file the DAW saves anyway: `.cpr`, `.reason`, `.logicx`. **Any route that needs an export from the DAW is no gain.** Exporting a DAWproject from Cubase takes the same effort as exporting MIDI. I suggested otherwise once and was corrected (2026-11-14).

Exports still matter in two ways:

- **As test references.** For each fixture project, your MIDI export (and DAWproject export, where one exists) is the known answer we compare a native reader's output against, programmatically.
- **DAWproject as a format in its own right.** People receive `.dawproject` files from collaborators using Bitwig, Studio One or Cubase. Reading those is useful, but it doesn't replace the native readers.

## Summary

| Format | What the file is | Public knowledge | Prospect |
|---|---|---|---|
| Logic `.logicx` | macOS package (a folder). MIDI is in an undocumented chunked binary, `Alternatives/NNN/ProjectData`. | **The most.** Three MIT-licensed projects document note, region, tempo, meter and marker layouts. | Medium. The best-understood native format. |
| Cubase `.cpr` | Undocumented binary. | **Little.** One young MIT project maps Cubase 12 files for audio only. No public work on MIDI. | Hard. MIDI would be new reverse-engineering. |
| Reason `.reason` | Undocumented binary. **Encrypted from Reason 6 to 12.5**, unencrypted from 12.6. | **None found.** | Hard. Starts from zero, but 12.6+ files are at least readable. |
| DAWproject `.dawproject` | Zip of XML, open spec (MIT), XSD schemas. | **Complete.** | Easy. Useful for received files, and to prove the shared reader design. |
| Reaper `.rpp` | Plain text. | Python parsers exist. | Easy. Reaper hasn't been tested with this app. |
| Bitwig native project | Not investigated yet. | Not assessed. | Target DAW; native-reader feasibility open. |
| Ableton native project | Not investigated yet. | Not assessed. | Target DAW; native-reader feasibility open. |
| FL Studio native project | Not investigated yet. | Not assessed. | Target DAW if feasible; native-reader feasibility open. |

Everything below is from web sources and unverified until your fixtures confirm it. I mark the shakier claims.

## Logic Pro (`.logicx`)

**What the file is**

- A macOS package: a folder Finder shows as one file.
- The arrangement data is in `Alternatives/000/ProjectData` (and `001`, `002`… for each project alternative). Several sources agree it's an undocumented little-endian binary, chunked with FourCC tags. They're written reversed, for example `qSvE` (event sequence), `qeSM` (MIDI sequence), `karT` (track).
- One guide claims ProjectData is a binary plist or gzipped XML. Every other source contradicts that, so I'd disregard it.
- Tempo and time signature can be read from `MetaData.plist`, according to logic2ableton. LogicProFormatWriter documents tempo, meter and markers inside ProjectData too.

**Prior work** (all MIT unless noted)

- **[logic2ableton: reverse-engineering notes](https://github.com/Evilander/logic2ableton/blob/master/docs/reverse-engineering-logic-pro-midi.md).** It documents the note record:
  - Each note is a fixed record found by a 15-byte signature, `00 00 01 00 00 00 00 00 00 00 89 00 00 00 00`.
  - Start position is a uint32 at signature−9, velocity at −2, pitch at −1, duration a uint32 at +15.
  - 960 ticks per quarter note.
  - Notes belong to the nearest preceding `qSvE` sequence.
  - **Weaknesses:**
    - Finding notes by scanning for a signature can produce false matches. Range checks reduce them.
    - It doesn't recover absolute bar positions, only relative ones.
    - It doesn't decode MIDI channel.
    - It was tested on three of Apple's bundled Live Loops demos, and doesn't say which Logic version.
- **[LogicProFormatWriter](https://github.com/jonkubis/LogicProFormatWriter)** (Python, standard library only). A writer, not mainly a reader, but its `PROJECTDATA_FORMAT.md` is a byte-level spec covering:
  - record framing;
  - tempo, meter and marker encodings;
  - MIDI note and region layouts.

  It targets one Logic version, which it doesn't name. **This is the most valuable thing to read first.** Proper record framing would replace signature scanning.
- **[logicx-analyzer](https://github.com/geoffmyers/logicx-analyzer)** (Python). It extracts track names, plug-in data and chunk structure. Tested with projects saved by Logic 10 and 11 on macOS Sonoma.
- **[lpx-explorer](https://github.com/rhydlewis/lpx-explorer)** (Tauri/TypeScript, a read-only inspector) and its Rust crate `lpx-parser`. Its author describes the crate as the long-term home for format knowledge.
- **[daw2logic](https://github.com/audiohacking/daw2logic)** converts DAWproject to Logic. That's the reverse direction, but it may show more of the layout.
- A [Logic Pro Help forum thread](https://www.logicprohelp.com/forums/topic/132829-internal-logic-pro-x-file-format-docs/page/2/) discusses the format. One poster used Ghidra on Logic itself. **We shouldn't do that.** We only study files we've saved ourselves (see [legal](#legal-and-licensing)).

**DAWproject:** Logic has **no native DAWproject support**. Several mid-2026 sources say so, though most of them sell converters. Apple forums have open feature requests. Your fixture will confirm: check whether File ▸ Export offers it.

**Observations**

- **The current alternative.** A project can hold several alternatives, and only one is current. The reader must find which, from the package's plists or ProjectData. That fits the roadmap's "current arrangement only".
- **Take folders and comping** are likely the hardest part of "exclude inactive material".
- **Drag-in today:** dropping a folder imports the `.mid` files inside it (`interchange/drag_import.py`). A `.logicx` package arrives as a folder, so today it would import nothing, or stray MIDI files. Package detection must come before that.
- **Platform:** Logic files only exist on macOS, but the reader is plain file parsing, so it would run on Windows too.

## Cubase (`.cpr`)

**What the file is**

- An undocumented binary. Steinberg publishes nothing.
- The format changes across versions. The only modern work targets Cubase 12.

**Prior work**

- **[cpr2rpp](https://github.com/daniel-lynch/cpr2rpp)** (MIT, probably Python, one commit, no stars). It converts Cubase 12.0.50 projects to Reaper and documents the format in `docs/FORMAT.md`.
  - It reads audio events, mixer settings and the pool.
  - **It doesn't read MIDI parts, tempo changes or markers.**
  - Its author **found no flag for part mute**. That's a warning for our clip-mute goal, though they were looking at audio events.
  - **Read `FORMAT.md` first.** Its container and track-structure findings should save the first days of work.
- **[cubase-project-plugins](https://pkg.go.dev/github.com/fgimian/cubase-project-plugins/parser)** (Go). It lists the plug-ins and Cubase version in a project, so it understands enough of the container to walk it.
- **[A gist that exports markers](https://gist.github.com/andigamesandmusic/94be52eff000013d7cdf5daef54bc4aa)** (JavaScript) from `.cpr`/`.npr` to JSON with sample precision. It's a direct lead on the marker track.
- **[Cubase-Project-File-Reverse-Engineering](https://github.com/omeriko9/Cubase-Project-File-Reverse-Engineering).** An SX2/SX3-era (2003) viewer. Mostly of historical interest.

**Cubase's DAWproject export, for reference only**

- It needs Cubase 14.0.20+ or 15. That's from a search snippet; Steinberg's [help page](https://helpcenter.steinberg.de/hc/articles/25142209226642) blocked my fetch.
- **It drops MIDI CCs.** Steinberg staff [confirmed in the forum](https://forums.steinberg.net/t/issue-dawproject-export-missing-midi-cc64-sustain-events-cubase-15-pro/1023436) that "MIDI CCs are not currently supported yet", along with note expression, crossfades and the channel strip. A November 2026 post says Cubase 16 still drops them.
- A search snippet said Steinberg's page also lists the tempo track as not carried over. **Unconfirmed.**
- So for checking a `.cpr` reader, **the MIDI export is the better reference.** The DAWproject export adds clip positions, trims and mute that MIDI loses.

**Observations**

- **No head start on MIDI.** This is the format where differential fixtures (below) matter most.
- **Inactive material:** lanes, takes, disabled tracks and hidden tracks each need a rule.
- **Material Cubase generates rather than stores:** the chord track, MIDI inserts and MIDI modifiers (transpose, velocity), and possibly MIDI track parameters applied at playback. Whether the saved notes include these is a question for the fixtures.
- **Platform:** the same `.cpr` format on macOS and Windows, presumably. Unverified.

## Reason (`.reason`)

**What the file is**

- An undocumented binary holding the sequencer tracks, the rack and its devices, and optionally embedded samples (self-contained songs).
- **Encryption.** You remembered correctly, and it checks out:
  - From Reason 6 to 12.5, song files were encrypted, and Reason's copy protection decrypted them.
  - From **12.6 onward**, songs are still `.reason` files, but not encrypted. A Reason Studios post quoted in [a KVR thread](https://www.kvraudio.com/forum/viewtopic.php?t=597632&start=15) explains the change, also covered [later in the thread](https://www.kvraudio.com/forum/viewtopic.php?t=597632&start=45).
  - I found no official release note, so that thread is the source.
- Older formats: `.rns` (before `.reason`), `.rps` and `.rsndemo` ([Reason 13 help](https://help.reasonstudios.com/hc/en-us/articles/4405950834834-What-song-files-can-I-open-in-Reason-13), [Just Solve](http://justsolve.archiveteam.org/wiki/Propellerhead_Reason_Project_File)).

**Prior work:** **none found.**

- A [Gearspace thread](https://gearspace.com/board/music-computers/1459810-extract-midi-reason-lite-song-files-without-reason-possible.html) concluded only Reason can read the files. That was before 12.6, or encryption-era thinking.
- Reason has no DAWproject support.
- [DawVert](https://github.com/SatyrDiamond/DawVert) doesn't read Reason.

**Observations**

- **Pattern devices.** Redrum, Matrix and other pattern-based devices hold their own patterns in the rack, not as notes on the sequencer. [ReasonTalk](https://forum.reasontalk.com/viewtopic.php?t=7524214) confirms pattern lanes must be converted to notes before other DAWs can use them. Without that conversion, those notes aren't in the sequencer data at all. We'd report them as skipped, not decode device patterns. That's an arranger's job, not a palette's.
- **Players** (Reason's MIDI-effect devices) generate notes at playback, so they're out of scope in the same way.
- **Clean failure for encrypted files.** The reader should detect an encrypted, pre-12.6 song and say "saved by an older Reason; re-save it in Reason 12.6 or later". It must not half-import.
- **The known Reason quirk** with Controller #254 on import ([INTEROP_FINDINGS](../INTEROP_FINDINGS.md)) is about Reason reading our MIDI, not us reading Reason. It doesn't apply here.

## DAWproject (`.dawproject`)

**What the file is:** a zip holding `project.xml` and `metadata.xml`, plus embedded audio and plug-in states. The spec is at [bitwig/dawproject](https://github.com/bitwig/dawproject), MIT-licensed, version 1.0, described as stable. It has XSD schemas, and a [full reference](https://github.com/bitwig/dawproject/raw/refs/heads/main/Reference.html) I read for this.

**The data we need is all there:**

- **Arrangement:**
  - `Arrangement` › `Lanes` (one per track, referencing it) › `Clips` › `Clip` › `Notes` › `Note`.
  - Notes carry `time`, `duration`, `channel`, `key`, `vel` and `rel`.
- **Clip fields:**
  - `time` and `duration` on the parent timeline; `playStart` and `playStop` (the trim); `loopStart` and `loopEnd`.
  - `reference`, for linked (alias) clips.
  - `name` and `color`.
  - **`enable` — "whether this clip should be played back"**. That's clip mute, exactly.
- **Tracks:** `Channel` has a `solo` attribute and a `Mute` element.
- **Tempo and meter:** `Transport` has the start tempo and time signature. `TempoAutomation` and `TimeSignatureAutomation` in the arrangement hold the changes.
- **Markers:** `Markers` › `Marker` (cue markers) on the arrangement.
- **CCs and pressure:** `Points` with an `AutomationTarget` that can be a MIDI expression, monophonic (CCs) or per-note.
- **Times** are in beats or seconds, set per timeline (`timeUnit` and `contentTimeUnit`). Seconds have to be converted through the tempo map.
- **Clip launcher:** `Scenes` and `ClipSlot` are stored apart from the arrangement, so they're easy to exclude.
- **No lyrics element.** Text events inside clips may not survive either; to check.

**Who writes it:** Bitwig 5.0.9+, Studio One 6.5+ (now Fender Studio Pro), Cubase 14+ (with the CC loss above), Cubasis 3.7.1, VST Live 2.2 and n-Track 10.2.2 ([spec README](https://github.com/bitwig/dawproject), [Bitwig FAQ](https://www.bitwig.com/support/technical_support/system-requirements-62/)). Reaper reads it through third-party tools.

**Observations**

- **The reader:** Python's `zipfile` plus `xml.etree` is enough, with no new dependency. A Python library, [DAWproject-Py](https://www.roexaudio.com/blog/introducing-dawproject-py-empowering-daw-interoperability), exists, but we probably don't need it.
- **Unrolling loops:** a looped clip has to become repeated clips or one longer event list, since our model has no loop.
- **Alias clips** (`reference`) map naturally onto clips that share events, as split clips already do.
- **Embedded audio** can make the file large. We must read `project.xml` from the zip without loading the audio. See the size cap below.

## Reaper (`.rpp`)

- **Plain text.** The Python parser [`rpp`](https://pypi.org/project/rpp/) (Perlence) exists, and so does [`rppxml`](https://pypi.org/project/rppxml/) (C++ core, Python 3.10+). I didn't check their licences.
- **MIDI storage:** from general knowledge, MIDI items are stored inline as `E` lines (delta ticks, status, data bytes) under a `HASDATA` header, or as references to `.mid` files. Items have `MUTE` and tracks have `MUTESOLO`. **Unverified;** one fixture settles it.
- Included in the agreed target DAWs; Reaper hasn't been tested with this app (DESIGN_NOTES risk 3).

## Converters and other references

- **[DawVert](https://github.com/SatyrDiamond/DawVert)** (Python) is a general project converter. Its [input list](https://raw.githubusercontent.com/SatyrDiamond/DawVert/main/docs/input_plugins.md) includes DAWproject, Reaper, Ableton 11, FL Studio 20+ and many trackers, but **not Cubase, Reason or Logic**. I didn't check its licence. Look before borrowing anything; reading it to understand a format is fine.
- **WG DAW Converter** and **Doseedo** are commercial and claim to read `.logicx`. Closed, so no help beyond showing it can be done.
- [Doseedo's guide to DAWproject and Logic/Ableton](https://doseedo.com/guides/dawproject-logic-ableton) is the main source for Logic's lack of DAWproject. It sells conversions, so it has an interest in that framing.

## The current code: what a second format touches

I read the import path to see where formats are assumed. These are observations, not decisions.

- **Two places decide "is this MIDI":**
  - Drag-in's `_read_midi_file` sniffs for `MThd` or `RIFF…RMID` and reports anything else as "not a MIDI file" (`interchange/drag_import.py`).
  - Import ▸ Open filters on `*.mid *.midi *.smf *.kar` (`ui/main_window.py`).
  - The registry's detection replaces both.
- **One parse call:** `controller.parse_payloads` calls `import_smf_bytes` directly. That's the natural place for registry selection. Everything after it (`place_imports`, placement, the tempo source, undo) takes `(Source, [Track])` and is format-blind already.
- **Payloads are bytes.** `Payload` carries the file's bytes, capped at 64 MB (`MAX_FILE_BYTES`). Two formats don't fit that:
  - Packages (`.logicx` is a folder).
  - Projects whose size is mostly audio (`.dawproject` with embedded audio, self-contained `.reason`).

  Readers will want a path, and to read only the parts they need.
- **Folder drops** import the MIDI files inside the folder. A `.logicx` package must be recognised first.
- **`Source` is MIDI-shaped.**
  - `smf_format` (validated 0–2 by the session loader), `ppq`, and `raw` (the original bytes).
  - The source info panel prints "SMF format N · PPQ · bytes".
  - Ticks per quarter differ by format: Logic 960, the others to find out.
- **Sessions store `raw`, but no musical operation consumes it.** Checked 2026-11-14: `import_smf.py` retains the original bytes; `session.py` saves/restores them as base64 and validates their type. `Source.describe()` and Source Info use only their length for the file-size display. Editing, undo, restoring full clip extent, session reconstruction and export all use the parsed events and model metadata. There is no current reparse, original-file recovery or byte-for-byte source download feature.
  - Retaining originals could support a future reparse with an improved reader, recovery of data the model omitted, or saving an exact source copy. Those are possible benefits, not implemented behaviour.
  - **Agreed storage policy (2026-11-14), to implement with the shared importer:** persist the complete imported model, provenance fields, and any other metadata derived from the input that is not represented directly in the musical model. Keep the `raw` bytes field, but leave it empty (`b''`) for new imports, including MIDI. Populate it only if a concrete future feature needs the original bytes; retaining the field does not require retaining source files.
  - Store original source byte size independently of `raw`; source descriptions and Source Info must not report the empty field's length as the input's size. Keep derived metadata on the source record, with explicit fields and session persistence as needed by readers. This policy does not mean retaining arbitrary original content, embedded media or plug-in states. Research fixtures remain separate from normal user sessions.
  - Changing persisted `Source` fields requires an explicit schema/compatibility decision. The current loader preserves and skips unsupported schemas; it does not implicitly migrate them.
- **Drag preview parses on drag-enter**, to show matching track names while the drag is still over the window. A slow project reader would make the drag stutter. Readers need to be fast, or the preview needs a cheaper path.
- **The event model is already right.** Events are mido messages at Fraction beat times, so readers produce the same `Event` list the MIDI importer does. Markers and lyrics are meta events (`TEXT_META` in `core/events.py`), so they flow through the existing marker row and export.
- **Clip mute doesn't exist.** `Track` has `muted` and `soloed`; `Clip` has no mute. Its own plan is needed (roadmap: UI, export, ranges, undo, sessions).
- **No loops:** the model has no loop or repeat, so readers unroll them.

## Shared reader design (draft)

This interface is a sketch to test against the first two readers. The source storage policy above is agreed; the remaining interface details are provisional.

- **A reader** has two parts:
  - `detect(path, head)`: does this file or package look like mine? Cheap: extension, magic bytes, package layout.
  - `read(path)`: returns an **import result**.
- **The import result** holds:
  - a `Source` (provenance: format, version found, path, app, original byte size, tempo map, song title; plus other derived input metadata not represented in the musical model). Its `raw` bytes field is retained but left empty under the agreed policy;
  - a list of `Track`s with `Clip`s and events;
  - per-clip and per-track mute;
  - **diagnostics**: what was skipped and why, such as an encrypted Reason song, pattern devices, an unsupported version, a missing referenced file, or ignored inactive takes.
- **The registry** lists readers in order. The MIDI importer is the first reader, which proves the interface before any new format arrives. Drag-in and Open both ask the registry; neither has format-specific branches.
- **Clean failure:** an unreadable project raises one error with a clear message, and the workspace is untouched. That's the existing `ImportError_` path.
- **Read-only:** open files read-only, and never write next to them, even caches.

## How to investigate

### Differential fixtures (the biggest time saver)

For an undocumented binary, the fastest method is saving tiny projects that differ by **one thing**, then diffing the bytes. logic2ableton used exactly this. For each native format, a series like this would make reverse-engineering fast:

1. An empty project, saved.
2. The same project plus one MIDI track with **one note** (C3, velocity 100, bar 1 beat 1, one beat long).
3. That note moved to bar 2. Then its velocity changed to 64. Then its pitch changed to D3. Then its length changed to two beats.
4. A second note added.
5. The clip moved to bar 5.
6. The clip trimmed at the start, then at the end.
7. The clip muted. Then the track muted, with the clip unmuted.
8. A mod-wheel CC and a pitch bend added.
9. A tempo change at bar 3, then a time-signature change at bar 5.
10. A marker at bar 2.
11. Lyrics, where the DAW has them.
12. A second clip, then that clip looped or repeated.
13. An inactive take or lane (Cubase), or a second alternative (Logic). Reason's equivalent if it has one.

Each save as its own file with a numbered name. For Reason, add a Redrum pattern track and a Player device. Each one only needs to be detected and reported.

### Realistic fixtures

Alongside the series, one or two **real-sized projects** per DAW, each with its **MIDI export** (and DAWproject where possible), for the comparison: notes, timing, mute, markers, tempo.

### Comparison

- Write a script that reads a native project and the matching MIDI export, and compares note by note: pitch, velocity, start, length, channel. Then tempo, meter and markers.
- It reports differences, never "looks right". This becomes the per-format evidence in the feasibility matrix the roadmap asks for.

## Deliverables (from the roadmap)

- A feasibility matrix per format: what's recoverable, gaps, dependencies, effort, and evidence from fixtures.
- A separate implementation recommendation per format.
- The shared reader interface and registry, validated by the first two readers.
- A separate plan for clip mute.

## First feature and suggested follow-on order

1. **The shared reader interface, with MIDI as the first reader.** No behaviour change; it proves the seams.
2. **DAWproject (agreed first new reader).** Its main purpose in this milestone is validating the pluggable import model: the shared result, clip `enable`, loops and seconds-to-beats conversion. It's also useful for received files. The native-reader order below remains a suggestion pending fixtures and investigation of Bitwig, Ableton and FL Studio.
3. **Logic.** The most prior work. Start from LogicProFormatWriter's spec and your differential series.
4. **Cubase.** Start from cpr2rpp's `FORMAT.md` and the marker gist, plus the differential series. Expect the most work on MIDI.
5. **Reason.** Timeboxed: decide whether it's feasible from the differential series before committing to a reader.
6. **Clip mute plan**, when the first reader that can see clip mute is ready.

Reaper, Bitwig, Ableton and FL Studio are all in scope, with FL Studio support subject to feasibility. Their place in the native-reader order remains open; Bitwig, Ableton and FL Studio need initial investigation.

## Legal and licensing

- **What we study:** only project files you saved yourself, never the DAW applications. No decompiling, no Ghidra.
- **Format vs software:** one forum post argues Apple's licence restricts reverse-engineering the software, not documenting its data files. **I can't judge that; you may want to.**
- **Code reuse:** the prior work above is MIT where stated, which allows reuse with attribution. Check each licence before copying code (DawVert, `rpp`, `rppxml` unchecked). Reading them to learn the format raises no licence question.
- **Fixtures in a public repo:** see the questions.

## Questions for you

1. **DAWproject's place — resolved 2026-11-14.** First new reader, primarily to validate the pluggable import model alongside MIDI.
2. **DAW versions.** Which versions of Cubase, Reason, Logic, Reaper, Bitwig, Ableton and FL Studio do you have? Cubase's format changes between versions. Reason must be 12.6+. Logic may vary between 10 and 11.
3. **Differential series.** Can you save a series like the one above for each DAW? It's tedious but small, and it's the biggest time saver for Cubase and Reason.
4. **Fixtures in the repo.** The repo is public. Commit the project files under a fixtures folder, or keep them local and untracked (like the Range samples)? If local, tests skip when they're missing.
5. **Version support.** How far back should a reader support? Probably only what you have, with a clean "unsupported version" for others.
6. **Generated material.** Agree that pattern devices, players, arpeggiators, chord tracks and MIDI inserts are **reported as skipped, not rendered**?
7. **Sessions — resolved 2026-11-14.** Persist provenance and derived input metadata alongside the complete imported model. Retain `raw` as a bytes field but leave it empty for new imports, including MIDI, unless a future feature gives it a concrete purpose. Store original byte size separately. Implement the field/UI/session changes together with an explicit compatibility decision; current application behaviour has not changed yet.
8. **Legal comfort.** Are you comfortable with format reverse-engineering from your own saved files, for Logic in particular?
