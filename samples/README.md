# Samples

Test fixtures and reference files. Tests that need a file skip when it is
absent, so the suite runs on a fresh clone; the local-only files make it more
thorough on the machine that has them.

| Folder | In git | What it holds |
| --- | --- | --- |
| *(top level)*, `assembly/`, `complex-matching/`, `cubase-check/`, `non-synthetic/` | yes | MIDI files for import, export, assembly and song-matching tests |
| `project-sets/` | yes | Cubase projects with their MIDI and DAWproject exports ([README](project-sets/README.md)) |
| `project-cubase-phases/` | yes, except three large Verify projects | Cubase fixture tiers (c01–c26) and real "Verify" projects ([Cubase plan](../docs/plans/cubase-import.md)). `Verify/` keeps BBCSO, orchestral-import-test and Scaler3Test local (large; ignored by name) |
| `reason-probe/` | yes | The Reason r-series (r01–r27, saved for decoding, with their Reason MIDI exports and screenshots), `mute-tests` and `rampy` ([Reason plan](../docs/plans/reason-import.md)) |
| `reason-check/` | yes | Real Reason songs with Reason's own MIDI export: the import is compared with each export. Also two assembled MIDI files from the Reason interop findings |
| `local/` | **no** | Files tests use when present but too big to commit (`local/reason/Oct08…`, 58 MB) |
| `_archive/` | **no** | Material not kept in the repo, gathered to be archived elsewhere: the Reason 5–14 songs used for the format probe, re-saved and scratch Cubase files, stray exports, `Auto Saves` and `Track Pictures` folders |

Rules:

- A file a test depends on goes in a committed folder, or in `local/` if it is too big (over about 50 MB, GitHub's warning size).
- Scratch exports, auto-saves and re-saves don't stay in fixture folders: move them to `_archive/` or delete them.
- Cubase `Auto Saves/` folders are ignored everywhere.
