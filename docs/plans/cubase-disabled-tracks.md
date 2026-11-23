# Plan: Cubase disabled tracks

Status: **agreed** (2026-11-23), not built. On the roadmap under Agreed, not started. Building is for a separate session from this plan; no code has been written.

Raised during the mirror-mode checklist: a track disabled in Cubase (Disable Track, which is not mute) still comes into the app. It should not, because Cubase plays nothing from it and leaves it out of its own MIDI export.

## What is known

The full findings, with offsets and the evidence behind each, are in [CUBASE_FILE_FORMAT.md, section 4.3](../formats/CUBASE_FILE_FORMAT.md). In short:

- **Disabled** is the property `noit` (on disk `6e 6f 69 74 00 01` + i64; `cf._props` key `'tion'`) in the track event's property list, with the value **1**. It is the same for instrument, drum, MIDI and audio tracks, and was checked against an enabled twin of the same project for all four.
- **The test is "equals 1", not "present".** A track that was disabled and re-enabled keeps `noit` with value 0, and a track never toggled has none.
- Instrument and drum tracks also carry `dfot`. It only corroborates `noit` there. MIDI and audio tracks never have it, so it is not the test.
- It is independent of mute (d2) and of hidden (d4).
- **Hidden** is a separate property, `dihT` (i64 1). Cubase still plays hidden tracks and its export keeps them.
- Folders cannot be disabled in Cubase. A disabled track in a folder carries the marker on the track only (d10, d11).
- **Cubase's MIDI export leaves out disabled tracks** and keeps hidden ones. BBCSO_Woodwinds101 is the independent check: of the 34 tracks the reader imports, the 18 with `noit` = 1 are exactly the 18 missing from the export.
- Every MIDI and audio track in the samples with `noit` = 1 is confirmed disabled by the owner. No MIDI or audio track known to be enabled has it.

### Still unknown

- Cubase 14: no sample with a disabled track (the owner's Cubase 14 machine is only intermittently available). `noit` is seen in 13, 15 and 16.
- What Cubase's export does with a track that is **muted but not disabled**. No fixture. This does not change the plan, which follows what Cubase plays and leaves muted tracks as they are today.
- What `noit` is called in Cubase and why the property is written. Only its behaviour is known.
- Disabled audio tracks cannot be checked against a MIDI export. They are never in one, and the reader does not import audio.

## Fixtures (all supplied, in `samples/project-cubase-phases/DTracks/`)

| File | What it is |
| --- | --- |
| d0 | Three instrument tracks (Pianoteq 9 A, B, C) with notes. Baseline |
| d1 | d0 with B disabled |
| d2 | d1 with B also muted |
| d4 | d0 with B hidden |
| d5 | d1 with B re-enabled (nothing hidden) |
| d6, `d6 baseline` | One MIDI track, "MIDI 01": disabled, and enabled |
| d7, `d7 baseline` | One drum track, "Beat Starter 01": disabled, and enabled |
| d8 | One instrument track on the linear time base, disabled |
| d9, `d9 baseline` | One audio track, "70sBandLoop": disabled, and enabled |
| d10, `d10 baseline` | A folder holding an audio track and an instrument track, both disabled; both enabled |
| d11 | A folder holding one disabled instrument track |
| `.midi` | Cubase's own MIDI export, for d0, d1, d2, d4, d5 only |

d3 (a disabled folder) does not exist, because Cubase cannot do it. `d9(15)` is an unrelated test and is ignored. d8 has no enabled twin: its marker is read from d8 itself, as for the others.

## Design

### Behaviour

- A disabled track (`noit` = 1) is **left out of the import**, the way the reader already leaves out linear time-base tracks, and a note says so ("Track "X" is disabled in Cubase; not imported"). The note appears in the import summary, and in the status bar while mirroring.
- It applies to every track class the reader looks at, so a disabled MIDI track (d6) goes the same way as an instrument track.
- Skipping rather than muting is the point: a muted track still shows, can be unmuted and exports. A disabled track in Cubase cannot sound at all.
- A disabled track is left out whether or not it has clips. It is not listed as an empty track.
- Re-enabling the track in Cubase and saving brings it in on the next mirror re-import, as a new track. The mirror path already handles tracks that appear and disappear.
- **A project whose only importable tracks are disabled** (d6, d7, d8, d9 give the shape) ends in the existing "no supported MIDI parts or markers" error today, and the warnings that were collected are lost with it, such as the linear time-base and Pattern Editor notes. Decided: the import fails with a clearer message that says the project's tracks are disabled in Cubase (naming how many), and the notes collected on the way are not lost. The wording is for the build to propose and the owner to approve.
- Hidden tracks keep importing. That a track is hidden in Cubase is **noted in its Source Info**. `dihT` = 1 gives this. A place in Source Info for it is to be checked at build time.

### The internal setting

- A reader option, `include_disabled` (default `False`), next to the existing `preserve_track_state`. When true, disabled tracks import **muted**, so they stay silent but are there to be inspected.
- It is a plain argument at first, with no UI. It is listed under "Future settings page" in the roadmap once agreed.
- Mirror mode passes the same option on every re-import, so its behaviour follows the setting.

### Code

- `cpr_format.py`: a function next to `track_state_flags` that reads the track event's property list and returns whether `noit` is 1. It should read the list with `_props` (the list ends exactly where the mixer object starts, on every track event in the samples across Cubase 13 to 16). Fallback if the list fails to parse: search for `noit 00 01` in the bytes between the event's direct children, never inside a child. Hidden is read the same way (`dihT`).
- `import_cubase.py`: a check next to the time-base check in the track loop. It either skips the track with a note, or, with the option, imports it muted.
- Reader registry: the option reaches `import_cubase` through whatever carries `preserve_track_state`, to be checked at build time.

### Tests

- A fixture test for each of d1, d2, d6, d7, d8, d9, d10, d11: the tracks that come in, and the note text.
- A regression test that d0, each `baseline` file and d5 import exactly as they do today (nothing disabled), and that the existing Cubase fixtures give identical results.
- A test of the marker itself on the enabled twins: `noit` is 0 (or absent) and the track is not treated as disabled. This is the "equals 1, not present" rule.
- Cubase's MIDI export of d1 and d2 is the reference: the import and the export hold the same tracks. BBCSO_Woodwinds101 is the larger check: the import and the export hold the same tracks and notes.
- One test for `include_disabled`: the disabled tracks come in muted.
- The all-disabled case (d6 to d9): the clearer message, and the other notes kept.
- A mirror test: a re-import where a track becomes disabled removes it, and one where it is re-enabled adds it back, without disturbing the other tracks' ids and states.
- `orchestral-import-test-01.cpr`: the reader imports 169 tracks today and 144 of them are disabled, so this feature leaves 25. The owner expects this: the file was made from an orchestral template, most of whose tracks are disabled. Any test or checklist item that counted that file's tracks needs updating.

### Docs

- Cubase format doc: done in this branch (section 4.3, Q7, the fixture table).
- README: one line under the Cubase limitations.
- A TEST_CHECKLIST section for the feature's branch.
- The roadmap entry (still to add) and the plan's "built" status, when it ships.

## Decisions (2026-11-23)

1. **Plays or exports**: follow what Cubase **plays**. Disabled tracks are left out. `include_disabled` brings them back.
2. **A disabled track with clips**: skipped, with a note.
3. **Hidden tracks**: keep importing them, as Cubase still plays them. The fact that a track is hidden is noted in its Source Info.
4. **Fixtures**: supplied, as above.
5. **All tracks disabled**: fail with a clearer message, not an empty palette.
6. **orchestral-import-test-01** dropping from 169 imported tracks to 25 is expected.

## Questions for the owner

None open.

## Branch

This plan, and the format doc changes, are on `feature/cubase-disabled-tracks`, which was already made from `release/0.5.0`.
