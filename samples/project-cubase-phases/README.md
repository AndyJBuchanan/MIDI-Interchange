# Cubase progressive fixtures

Small Cubase projects that each differ from the previous file by one change,
for reverse-engineering the native `.cpr` format. The catalogue and the meaning
of each step are in [the Cubase plan](../../docs/plans/cubase-import.md#fixture-requests).
Preserve the original files and filenames.

Each tier has a `Cubase15` (15.0.30) and a `Cubase16` (16.0.5) folder, saved
from the same steps. The project starts at 120 BPM, 4/4, with one Padshop
instrument track.

## Tier 1 (2026-11-14)

- `c01`–`c09.cpr`: the tier 1 steps.
- `c02-1.cpr`: `c02` with a one-bar display offset (the project starts with a
  blank bar before bar 1). Every other file has offset 0.
- `c02.midi`, `c07.midi`: Cubase MIDI exports of the whole project, with Export
  Inserts off. The 15 and 16 exports are byte-identical.

All files are `RIF2` (64-bit chunk sizes). `c09` is `c08` saved again without
changes; the 53–66 bytes that differ are per-save noise to filter out of
other diffs.
