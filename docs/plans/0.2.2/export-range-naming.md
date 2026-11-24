# Fix: export range filenames

Status: **built and verified locally by the user** (2026-11-12). Branch: `fix/export-range-naming` from `main`.

Range filenames must use the same labels as the UI: a named range uses its name, and an unnamed range uses `Range N`.

- Single-range drag and Save MIDI: `Verse.mid` or `Range 1.mid`.
- Combined range export: join the range labels, e.g. `Verse + Range 2.mid`.
- Separate drag: each file uses its range label, with existing duplicate-name numbering.
- Separate multi-file Save MIDI: suggest `Export.mid` in the save dialog, producing `Export - Verse.mid` and `Export - Range 2.mid`. The user can still choose a different base filename.
- Range naming follows the defined range order, regardless of track inclusion. Do not change track exclusions, range content, timing, concatenation or MIDI track names.
- Whole exports retain the existing track/default filename rules.

Implementation: use `range_label` in the shared export-name function for drag and Save MIDI. When saving multiple results, suggest the simple `Export` basename. The existing file writer still appends the individual range labels and handles duplicate filenames. The earlier single-range-only drag naming change has been removed.

Validation: **222 tests passed**. Regression tests exercise actual drag filenames and the Save MIDI dialog/files for named and unnamed ranges, all range modes, and single-track and multi-track ranges. Existing duplicate-name tests remain.

Studio checks (fix verified locally by the user, 2026-11-12):

- [ ] Drag and save one unnamed range: `Range 1.mid`; name it Verse and repeat: `Verse.mid`.
- [ ] Two unnamed ranges, combined export/drag: `Range 1 + Range 2.mid`; repeat with mixed named and unnamed ranges.
- [ ] Separate drag: each file has its own range label only.
- [ ] Separate Save MIDI: dialog suggests `Export.mid`; resulting files are `Export - Verse.mid` or `Export - Range N.mid`, with each range label appearing once. Try a custom base name and duplicate range names.
- [ ] Whole-file naming and per-range track overrides still work.

No commit, push or PR until requested. Leave the mute/solo plan and unrelated sample files untouched.
