# Plan: clip splitting

Status: **implemented; manual verification passed** (2026-11-14). The intermittent cursor-switching issue predates this feature and is recorded in ROADMAP for later investigation.

Branch: `feature/clip-splitting`, created from the updated `release/0.3.0`. The eventual PR targets `release/0.3.0`, following [the branching rules](../RELEASING.md#branches).

Split one clip into two adjacent clips on the same track, using shared MIDI events and the existing edge trims. Both pieces stay in place. One Undo restores the original clip.

## Interaction

Modifiers below mean Option/Command on macOS and Alt/Ctrl on Windows.

- **Cmd/Ctrl-click over a clip splits it.** Show a scissors cursor while the modifier is held over the clip, plus a vertical preview line at the actual split position. No context-menu action or separate tool mode.
- Apply the current snap grid to the preview and the split. Shift bypasses snap, as with edge trims.
- If the position cannot leave both pieces at least the existing minimum trim length (one snap step, or one source tick with snap off or bypassed), show no valid split preview and do nothing on click. Do not move an invalid split to a different position.
- Split only the hit-tested clip, including when clips overlap. One click performs one split; dragging with Cmd/Ctrl does not repeatedly split or start a range gesture.
- **Opt/Alt** shows a move-arrow cursor over a clip and drags to move it. At a trimmable edge, retain the existing resize cursor and edge-trim gesture.
- **Opt/Alt + Cmd/Ctrl** shows a move cursor with a plus sign and drags to copy. This takes precedence over splitting and edge trimming, including at clip edges. Fix the currently missing copy cursor as part of this feature.
- Update cursors and the split preview as modifiers change with the pointer stationary, as well as on pointer movement. Clear the preview when leaving the clip, releasing the split modifier, or starting another gesture.
- Keep both clip names unchanged; do not invent suffixes or change export filenames.

## Boundaries

This is a non-destructive split using the existing trim model:

- Keep the original clip as the left piece, retaining its ID. Give the right piece a fresh ID.
- Both retain the original event list, full length, source, name and offset. Only their visible trim windows differ.
- For a split at workspace time `t`, the left piece ends and the right piece starts at clip time `t - offset`. Retain the original outer trims, including on an already trimmed clip.
- Either piece can subsequently be moved, copied, trimmed or restored independently. **Restore Full Clip** on either piece restores the full original extent, so it can overlap its neighbour. Splitting does not establish permanent new source boundaries.
- Use the existing export edge rules. A crossing note ends at the left piece's end and restarts at the right piece's start when `partial_notes` is on; when off, the right-hand continuation is omitted. This can sound different from an unsplit sustained note.
- Existing controller/program carry, text/lyrics/marker inclusion, channel override, mute/solo, range exclusions and all export modes continue through the existing export path. Do not introduce separate MIDI cutting rules.

## Implementation

1. Add a workspace split operation and a shared validity check. Validate the complete request before changing anything; an invalid request changes neither the workspace nor undo history.
2. Reuse `duplicate_clip` at the original visible start and `trim_clip` for the two inner edges. Preserve the full offset, including a negative offset on a left-trimmed clip. Reuse the controller's snap and minimum-trim policy. Keep validation and execution consistent without copying their boundary rules into the timeline.
3. Add one controller action with one undo checkpoint and one final track-change notification. Avoid calling public controller actions that independently checkpoint or emit intermediate state. Undo/redo restores IDs, ordering and trims exactly.
4. Resolve modifiers in one place for cursor feedback and gesture dispatch, with copy before move/trim before split. Reuse timeline hit-testing, coordinate conversion and snap handling. Use the same split-position validation for the preview and the click. Add scissors and move-with-plus cursors using existing Qt cursors where suitable, or small cursor artwork with an explicit hotspot where necessary; keep the preview in the existing theme.
5. Use existing track sorting, channel refresh and change notifications. No new track or range is created; locked-range exclusions remain track-based. Session persistence should already cover the two normal clips and their shared events. No new persisted fields or schema change is expected.

## Automated verification

- Untrimmed, already trimmed and repeatedly split clips; nonzero and negative full offsets; exact fractional positions; stable original ID and a fresh right ID; shared event-list identity and unchanged source events.
- At/outside edges, insufficient remaining length, missing clip, snap on/off and Shift bypass; rejected requests leave no partial duplicate and no undo step.
- One Undo/Redo restores the exact clip state; moving, copying, restoring and deleting either half remains independent.
- Export note pairs at the seam, including a crossing note, a note starting or ending exactly there, and `partial_notes` on/off. Verify same-tick note-off/note-on ordering, carried settings and text/lyrics at the boundary through existing edge rules.
- Exercise Whole, Preserve, Rebase and Separate exports, including channel overrides and locked-range exclusions. Test MIDI event results programmatically; do not ask for manual file comparisons.
- Session round trip preserves both pieces and shared data; reopening starts with fresh undo history as usual.
- UI checks cover Cmd/Ctrl-click, snap/Shift, correct hit-tested clip, invalid cuts, one split per click, modifier precedence at edges, stationary-pointer cursor updates and preview cleanup. Verify Opt/Alt still moves/trims, Opt/Alt + Cmd/Ctrl still copies, and plain range gestures remain unchanged.

## Manual verification after implementation

- Hold Cmd/Ctrl over a clip: check the scissors and snapped preview, then click to split. Repeat with Shift off-grid. Check the two pieces stay adjacent and Undo/Redo works as one operation.
- Check move, trim and copy cursors and gestures, including modifier changes without moving the pointer and copying from an edge, on macOS and Windows.
- Move one half and restore its full extent, confirming the agreed non-destructive behaviour.
- Drag the result into a DAW and listen to a note spanning the split, confirming the agreed release/restart behaviour.

## Documentation and scope

On implementation, document the action and boundary behaviour in README and DESIGN_NOTES, add the short manual checks to TEST_CHECKLIST, and remove the completed roadmap entry. No separate tool mode, multi-clip splitting, joining/gluing, destructive event edits, new colours, version bump or build is included.

## Implementation notes

- The controller shares snapped-position validation between preview and execution; the workspace reuses duplication and trims. No new session fields or schema change.
- Modifier feedback uses an application event filter so a stationary pointer updates even when another control has focus. Qt maps Command to Control on macOS. Modifier-key transitions are normalized explicitly because their reported modifier state can include the released key.
- Scissors and move-with-plus cursors are small outlined vector drawings with explicit hotspots. The preview uses the existing accent colour.
- Export regression tests exposed synthetic cut releases sorting after same-time retriggers. Their ordering in the shared extraction path now puts the cut release first; source MIDI and untrimmed whole-export event ordering remain unchanged.
- Automated coverage is in `tests/test_clip_splitting.py`, alongside the existing trim, export, session and timeline suites.

Validation: full suite **368 passed, 3 Windows-only skips**; after the final pointer/zoom and independence checks, focused split/trim/timeline/autoscroll suites **90 passed**. Manual checks are in TEST_CHECKLIST section 8l.

## Follow-up: Shift on clip move/copy

Windows clip-splitting verification passed. By user request, Shift during move/copy bypasses snap while targeting the gesture's original track, and preserves the original visible start while targeting another track or creating a new one. The reference remains the original track/time throughout the gesture; returning to it resumes unsnapped movement, and releasing Shift restores ordinary snapped movement. Both move and copy use the same logic and retain one undo step.

Follow-up validation: **97 passed** across split, trim and UI assembly tests, including move/copy to existing/new tracks, remaining on the destination, returning to the source, releasing Shift and undo. The user also manually verified the new Shift behaviour as working.
