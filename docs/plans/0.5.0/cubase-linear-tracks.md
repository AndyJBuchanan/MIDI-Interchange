# Plan: Cubase linear time-base tracks

Status: **built** (2026-11-23), on `feature/cubase-linear-tracks`. Manual checklist 8u passed on the owner's studio Mac with Cubase 16 projects (d8 baseline, c26). Built as planned, with one addition agreed during the build: parts inside an inactive track version are left out, so the import matches Cubase's export (the app imports only what is active). Still unknown: a linear part spanning a tempo change in the project's own tempo, positions inside a ramp (tested only against the formula), an extended or looped linear part, a linear track in a folder or with a muted part, and Cubase 14.

## The problem

A Cubase track set to the linear (seconds) time base is skipped on import, with the warning `Track "X" uses the linear (seconds) time base; it is not imported yet`. The track's parts are never read ([import_cubase.py](../../../midi_interchange/core/import_cubase.py), the time-base check in the track loop). A project made only of linear tracks fails with "no supported MIDI parts or markers". Cubase's own MIDI export does include them.

## What is known

Details and evidence are in [CUBASE_FILE_FORMAT.md, sections 4.2 and 4.7](../../investigation/formats/CUBASE_FILE_FORMAT.md).

- **Layout.** A linear part differs from a musical one only in its node header: `u32 1 · f64 1.0` replaces the tempo and signature references. The part event's start, length and offset, and the events' positions and note lengths, are in **seconds** (c26). **VERIFIED**, but only on c26, so the reader never exercised it on a second file until d8 baseline.
- **What Cubase's export does.** It writes a linear track as an ordinary track: each stored time in seconds is converted to ticks through the project's tempo map **as the project stands when it is saved**. Nothing marks the track as linear.
  - c26 (a tempo ramp from 120 to 90 BPM before the part): the Lead track's four exported notes, at ticks 8160, 9600, 15360 and 16800, are exactly the stored seconds converted through the tempo map, ramp included.
  - d8 baseline (`samples/project-cubase-phases/DTracks/`, with its export): two identical tracks written at 160 BPM, one then set to linear, then the project tempo changed to 140. The musical track's notes stay on their ticks (0, 640, 1280...). The linear track's notes, stored as seconds at 160, move to 0, 560, 1120... (every position times 140/160), and its second part starts at tick 10080 (9.0 s at 140 BPM). The export matches, note for note.
- **The tempo to use** is therefore the imported project tempo map, the one the reader already builds (d8 baseline: a single 140 BPM point; the 120 stored after it is only the trailing fixed tempo and is not played).

## Behaviour (as the owner described)

- A linear track is **imported as an ordinary track**: seconds converted to ticks through the imported tempo map, at the project's tempo as saved. There is no special handling of linear tracks in the app after import.
- It is imported **against the source tempo and not rescaled by later tempo changes**. If it is exported with a different tempo map, it is exported with that map and whatever tick positions it has. (This is the roadmap's wording, and what the owner confirmed.)
- Everything else about the track is as for a musical track: mute, solo, transpose, disabled (disabled still leaves it out first), clip names, trims and loops, shared parts.
- Mirror mode converts again on every re-import, with the tempo map in that save.

## Design

### Reading a linear part

- `cpr_format.decode_part_events` reads the header as "u32, W-byte, W-byte". A linear header is `u32 1, f64 1.0` and 8 bytes shorter (found at build), so the decode needs a branch on the time base, then decodes the events as for a musical part with positions and lengths in seconds. The format notes say the bytes are consumed exactly (c26); d8 baseline is the second check.
- `part_event_info` and `part_event_window` already read start, length and offset as f64. For a linear part they are seconds.
- `track_time_base_linear` is already the test. A part carries its own time base, so the part's header, not only the track's, decides how its events are read. (To check at build: whether a part can differ from its track.)

### Converting seconds to ticks

- One function in `import_cubase.py`, `seconds → ticks`, over the same tempo points the reader builds the tempo map from (`cf.tempo_points`: seconds, ticks and ramp flag per point). Between points it is constant tempo, and across a ramp the stored seconds match the closed form (format doc 4.8), so the conversion is exact.
- Positions are rounded to whole ticks, as the export's are. A note's length is the converted end minus the converted start, so a note that spans a tempo change keeps the right duration.
- To check at build: whether converting through the exact points or through the reader's stepped tempo map (a step per beat across ramps, as Cubase's export does) matches the export within a tick on c26. The exact points are expected to; the stepped map may drift by a tick or so inside a ramp.
- A linear part's start, length and offset convert the same way. A part's "content zero" (start minus offset) is converted as a position, not an offset length, so a part that begins mid-ramp is placed correctly.

### The reader

- Remove the skip and its warning. Linear tracks go through the same loop as the others, with the part events decoded in seconds and converted.
- **A Source Info note** (decided): each imported linear track adds `Track "X" was on Cubase's linear time base; its positions are converted at the project's tempo`. It goes in the source's Warnings list, which is what Source Info and the import summary show (as the hidden-track note does, which has no per-track field either). It explains why such a track moves when the Cubase project's tempo changes. The note is the only special treatment; the track itself is ordinary.

### Code

- `cpr_format.py`: the time-base branch in `decode_part_events`; a seconds-to-ticks helper next to `tempo_points`, if it belongs with the tempo code.
- `import_cubase.py`: remove the `continue`; convert the part window and the events for a linear part.
- Format doc: section 4.7 (VERIFIED on d8 baseline, the c26 reader finding, section 8's disagreement closed), section 6.2 (Linear-time-base tracks, "Skipped with a warning" becomes imported), the fixture table.

### Tests

- **d8 baseline against its export:** the linear track and the musical track both match `d8 baseline.midi` note for note (names, tick positions, lengths). This is the main test.
- **c26 against its export:** the Lead track's four notes at ticks 8160, 9600, 15360 and 16800, through the ramp. Replaces `test_tier3_linear_time_base_track_reported_not_imported` (it currently asserts the track is skipped).
- The Source Info note appears once per linear track, and not on musical tracks (d8 baseline).
- A linear track whose project tempo is changed: its ticks move and the musical track's do not (d8 baseline against a project with the same notes at 160, if one exists; otherwise the d8 baseline numbers above).
- A disabled linear track is still left out (the existing d8 case).
- Regression: every other Cubase fixture imports exactly as it does today. Add a regression test for the changed import behaviour, as the project rule says.
- Mirror: a re-import after the tempo changes moves the linear track's clips and not the musical track's.

### Docs

- README: remove the linear-time-base line from the Cubase limitations (or reword it).
- A TEST_CHECKLIST section for the feature's branch (drag d8 baseline in and see both tracks line up as the export does; c26's Lead appears).
- The roadmap removal and the plan's built status, when the feature is accepted.

## Decisions (2026-11-23)

1. Linear tracks import as ordinary tracks, converted at the project's tempo as saved, as Cubase's export does. No rescaling by later tempo changes, no special handling after import.
2. **A Source Info note** per imported linear track, worded as in "The reader" above.
3. Edge cases (a linear part that is shared, extended before its content, or looped): test what the fixtures offer and report the rest as unknown, not guessed.

## Questions for the owner

None open.

## Fixtures

- `samples/project-cubase-phases/DTracks/d8 baseline.cpr` and `d8 baseline.midi` (both on the owner's checkout, **untracked**; they go in on the feature branch with the code).
- c26 and its export, already in the repository (`Tier 3/Cubase16`).
- What is missing and would help: a linear track that spans a tempo change **in the project's own tempo** while the other track stays musical (c26 has a ramp but one linear track), and a **linear track in a folder or with a muted part**. Neither blocks the first build.

## Branch

Plan and roadmap entry on `release/0.5.0` (this branch, not yet committed). The feature is `feature/cubase-linear-tracks`, made from the release branch after the plan is agreed.
