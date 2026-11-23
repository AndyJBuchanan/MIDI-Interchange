# Plan: Cubase disabled tracks

Status: **draft, decisions made** (2026-11-23); waiting on fixtures d0 to d5 (to go under `samples/`); mirror mode first. Not on the roadmap yet and not agreed. No code until the owner agrees this and says to build.

Raised during the mirror-mode checklist: a track disabled in Cubase (Disable Track, which is not mute) still comes into the app. It probably should not, because Cubase plays nothing from it.

## What is known

- The reader knows nothing about disabled tracks. It reads the track's flags word and takes two bits: `TRACK_SOLO = 0x1`, `TRACK_MUTE = 0x4` ([cpr_format.py:561](../../midi_interchange/core/cpr_format.py#L561)). Everything else is ignored.
- [CUBASE_FILE_FORMAT.md](../formats/CUBASE_FILE_FORMAT.md) lists "disabled and hidden tracks" as **UNKNOWN**. The fixtures that were meant to show it (c27 lanes and takes, c28 Disable Track, c29 hidden track) were never received. It also says that, in every fixture so far, no flag bit other than mute and solo is set.
- Whether Cubase's own MIDI export includes a disabled track is **not known**. The owner's guess was that it may.
- Hidden tracks are a different thing from disabled ones: hidden is a display choice, and Cubase still plays the track. They belong in the same fixture set, but only disabled is in scope here. Hidden tracks keep importing.

## The unknowns to settle first (needs fixtures)

1. **Where Cubase stores "disabled"**: a bit in the flags word, a separate record, or something else. A decode guessed from one file is the sort of rule we have been caught out by before, so it needs several saves.
2. **What Cubase's MIDI export does with a disabled track**: leaves it out, or writes it. This is the reference the reader is checked against, as for the other readers.
3. **What happens to disabled folders**: whether disabling a folder disables the tracks inside, as muting a folder sets the mute bit on each inside track (format doc 4.4).

## Fixtures to request from the owner (they go in the project, under `samples/`)

Made from one small project, each saved as `.cpr` and exported with File ▸ Export ▸ MIDI Loop or MIDI file:

- **d0**: three MIDI or instrument tracks, each with a few notes. No disabling. The baseline.
- **d1**: the same project with the middle track disabled (right-click the track, Disable Track).
- **d2**: d1 with the track disabled and also muted. Settles whether the two states are independent.
- **d3**: a folder with two tracks inside, the folder disabled.
- **d4**: d1 with the track hidden (not disabled), to confirm hidden is stored apart from disabled.
- **d5**: d1 saved twice, with the track re-enabled in the second. A disabled state that survives an enable would show up here, and it is also the case mirror mode meets.

The same method as the other fixtures: diff d0 against d1 with the existing Cubase inspector tool, then check the decoded bit across the other files.

## Design

### Behaviour

- A disabled track is **left out of the import**, the way the reader already leaves out linear time-base tracks, and a note says so ("Track "X" is disabled in Cubase; not imported"). The note appears in the import summary, and in the status bar while mirroring.
- Skipping rather than muting is the point: a muted track still shows, can be unmuted and exports. A disabled track in Cubase cannot sound at all.
- Re-enabling the track in Cubase and saving brings it in on the next mirror re-import, as a new track. The mirror path already handles tracks that appear and disappear.

### The internal setting

- A reader option, `include_disabled` (default `False`), next to the existing `preserve_track_state`. When true, disabled tracks import **muted**, so they stay silent but are there to be inspected.
- It is a plain argument at first, with no UI. Nothing else in the app has to change when a settings dialog arrives: the dialog would store the flag and pass it through. It is listed under "Future settings page" in the roadmap once agreed.
- Mirror mode passes the same option on every re-import, so its behaviour follows the setting.

### Code

- `cpr_format.py`: a function to read the disabled state next to `track_state_flags`. Its shape depends on unknown 1. If it is a bit in the flags word, the constant joins `TRACK_MUTE`.
- `import_cubase.py`: a check next to the time-base check in the track loop. It either skips the track with a note, or, with the option, imports it muted. Folder handling follows unknown 3.
- Reader registry: the option reaches `import_cubase` through whatever carries `preserve_track_state`, to be checked at build time.

### Tests

- Fixture tests: for each of d1 to d5, the expected tracks in the import, with the note text. One test for the option on.
- A regression test that d0 imports exactly as it does today, and that the existing Cubase fixtures give identical results.
- Cubase's MIDI export of d1 is the reference: the import of d1 and the export must hold the same tracks (or the difference is documented, if the export keeps disabled tracks).
- A mirror test: a re-import where a track becomes disabled removes it, and one where it's re-enabled adds it back, without disturbing the other tracks' ids and states.

### Docs

- Cubase format doc: replace UNKNOWN with the finding, and close Q7's c28 entry.
- README: one line under the Cubase limitations.
- A TEST_CHECKLIST section for the feature's branch.

## Decisions (2026-11-23)

1. **Plays or exports**: follow what Cubase **plays**. Disabled tracks are left out even if Cubase's MIDI export writes them; `include_disabled` brings them back.
2. **A disabled track with clips**: skipped, with a note. It is not listed as an empty track.
3. **Hidden tracks**: keep importing them, as Cubase still plays them. The fact that a track is hidden in Cubase is **noted in its Source Info**. This needs the hidden state to be found in the file (fixture d4), and a place in Source Info for it to show, to be checked at build time.
4. **Fixtures**: the owner has no time to make d0 to d5 yet, so the work waits for them. They go in the project, under `samples/`, like the other fixtures. Mirror mode is finished first.

## Branch

Not yet decided. This is a new feature, so its plan belongs on the release branch (`release/0.5.0`) and the roadmap entry with it. I'm on `feature/mirror-mode` and have not switched. The file is untracked in the working tree and is not committed.
