# Plan: clip edge trims

Status: **agreed, not built** (planned 2026-11-11). Branch: `feature/clip-edge-trims`.

Option-drag a clip's left or right edge to trim it. An edge can't go past the clip's original start or end. Exports write what the timeline shows.

## Behaviour

- **Gesture:** Option-drag (Alt on Windows) near a clip's left or right edge trims that side. With Option held over an edge, the cursor is ↔ (`SizeHorCursor`). Without Option, nothing changes: a plain drag still makes or resizes ranges.
- **Range edge and clip edge at the same spot:** a plain drag moves the range edge, and Option-drag trims the clip.
- **A clip too narrow for both edges:** when both edges fall inside the grab zone, the clip can only be moved (Option-drag moves it as today). To trim it, the user zooms in, or uses Restore Full Clip.
- **Limits:**
  - An edge can't go past where the clip's MIDI originally started or ended.
  - The two edges can't cross: a clip keeps a minimum length of one snap step, or one tick when snap is bypassed.
- **Snap:** an edge snaps to the grid as clip moves do, and Shift bypasses the snap, as in range drags.
  - An edge stops at the clip's original start or end, even when that is off the grid.
  - To get back on the grid, the user moves the clip.
  - Shift means something different on a clip move (keep the time), which is noted for the later keys and modifiers review.
- **Undo:** one checkpoint at the start of the drag, so one Undo reverses the whole trim, as with range resize.
- **Restore Full Clip:** a right-click menu item, shown only on a trimmed clip. It puts both edges back to the clip's full extent in one undoable step. Restoring never happens by itself.
- **Copies:** duplicating, Option-⌘-drag copying, moving to another track, merging tracks and butting against the previous clip all keep the trim. Butting and placement use the trimmed start.

## Export: what's on the timeline is what's exported

This applies to whole exports, range exports (preserve, rebase & concatenate, separate) and drag-out. Each clip's trims are applied with the range edge rules, from the one place where they're written:

- **A note that started before the left edge** sounds from the edge. The option to drop it instead (`partial_notes`, which already exists for ranges) covers trim edges too, so there's one rule. It's not exposed in the UI yet (see [Future settings page](../DESIGN_NOTES.md#future-settings-page)).
- **A note running past the right edge** is released at the edge, so no notes hang.
- **Settings at the left edge:** the program, controller, pitch bend, channel pressure and key signature in force there are written at the edge, as at a range start.
- **Lyrics, text and markers** are kept only inside the trims.
- **Whole export:** untrimmed clips are still written exactly as imported. A trimmed clip is written through the edge rules.
- **Trim leading/trailing silence** measures only what's inside the trims.

## Other places that use a clip's extent

- **Track channel badges and the source info panel:** count only the MIDI inside the trims.
- **Replace on drop:** a dropped clip replaces one with the same start and end. The comparison uses the trimmed (visible) edges by default, with an option to compare the full extents instead (a placement option, not exposed yet).
- **Drawing:** notes are already drawn only inside the clip's rectangle, so trimmed-away notes disappear. A note crossing an edge is drawn cut at the edge.

## How to build it

1. **Model (`core/document.py`):**
   - `Clip` keeps `events` and `length` unchanged as its full extent, and gains `trim_start` (default 0) and `trim_end` (default `length`), in clip time.
   - `start` and `end` return the visible edges, and `is_trimmed` says whether either trim is set.
   - A method sets the visible start: `offset = start - trim_start`.
   - Everything that positions a clip goes through it: `move_clip_to_track`, `duplicate_clip`, `snap_clip_to_previous`, `sort_clips`, `placement.source_length` and `place_imports`.
   - Workspace methods `trim_clip(clip_id, edge, time)`, which clamps to the limits, and `restore_clip(clip_id)`.
2. **Edge rules in one place (`core/export_smf.py`):**
   - `_extract` already cuts notes and carries settings at a segment's edges. Each clip's window becomes the overlap of the segment with the clip's trimmed span, and settings are carried to the start of that overlap.
   - `_whole` sends trimmed clips through the same code over an open-ended segment, and untrimmed clips stay exact.
   - `content_bounds` respects the trims.
   - Don't write a second copy of the cutting rules anywhere, including for badges and source info (reuse the same windowing to find what's inside).
3. **Timeline (`ui/timeline.py`):**
   - A `clip_edge` hit with Option held. It only counts when the clip's on-screen width is more than twice the grab zone.
   - The cursor, a `trim` drag kind that checkpoints at the start, and an update to the gesture list in the module docstring.
4. **Controller and clip menu:** `trim_clip_live`, plus `restore_clip` with a checkpoint, and **Restore Full Clip** in the clip context menu (main_window).
5. **Tests (headless, existing style):**
   - The limits, the minimum length and that edges can't cross.
   - A note across the left edge (with `partial_notes` on and off), a note across the right edge, and settings carried at the left edge.
   - Each export mode, plus Trim silence, with trimmed clips.
   - Moving, duplicating, butting, merging and undoing trimmed clips, and Restore.
   - Replace-on-drop with visible edges and with the option for full extents.
   - The Option-drag in the timeline, and a narrow clip allowing move only.
6. **Docs:**
   - README: the gesture, and remove "can't be trimmed yet".
   - DESIGN_NOTES: move the item out of to-do, and update the export policy text.
   - TEST_CHECKLIST: a studio section on trimming, then dragging out to a DAW and checking the notes that cross an edge.

## Out of scope

- Splitting a clip.
- Trimming several clips at once.
- Trim handles on ranges.
- Exposing the two new options in the UI (see the future settings page).
