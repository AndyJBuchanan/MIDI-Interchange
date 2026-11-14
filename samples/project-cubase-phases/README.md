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

## Tier 2 (2026-11-14)

Cubase 16.0.5 only (tier 1 showed the musical encoding matches 15).
`c10`–`c18.cpr`, with MIDI exports for the ✱ steps (`c10`, `c12`, `c13`,
`c14`, `c16`, `c17`, `c18`). The c12 end trim is one sixteenth, so the part is
1.2.3 long (bars.beats.sixteenths) from 5.2. c15 is an independent copy at bar
9; c16 a shared copy there. c17 adds a MIDI track (not an instrument track) on
channel 2; c18 puts both tracks in a folder.
