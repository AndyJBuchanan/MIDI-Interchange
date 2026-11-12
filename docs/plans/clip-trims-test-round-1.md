# Plan: clip trims, test round 1 follow-up

Status: **built** (2026-11-12). Branch: `feature/clip-edge-trims`, on top of `61a90ac` (the tested build).

This plan only finishes clip trims. Drag-in auto-scroll and mute/solo are in a separate plan, for after trims is merged.

Source: the studio test of checklist section 8d. Every item passed. The notes raised one bug, two behaviours for the docs to explain, and two ideas that aren't about trims. The section 10 Windows tick is from testing the last release, and it stays ticked.

## Evaluation

| Note | Verdict | Where |
|---|---|---|
| With the right edge at its limit, the pointer carried on to the window edge and the timeline scrolled | **Bug.** Once the edge can't move any further, the drag should have no further effect | 1 |
| An off-grid trimmed edge is kept only with Shift; moving a trimmed clip tends to snap it | **Working as designed** (plan answer 6: move the clip to get back on the grid; Shift keeps the time) | 2, docs |
| Duplicate puts the copy straight after the original, touching it | **Working as designed**, and right for a trimmed clip (it uses the visible end) | 2, docs |
| Dragging MIDI in from another app doesn't scroll the timeline at the right edge | **Missing feature** | Later: [next features](next-drag-in-scroll-and-mute-solo.md) |
| Make the include tickbox a mute control, add solo and a cancel-all | **Feature** | Later: [next features](next-drag-in-scroll-and-mute-solo.md) |

## Build

1. **Stop scrolling when a trim edge is at its limit (`ui/timeline.py`):**
   - During a trim drag, scroll only while the edge can still move in that direction.
   - **Right edge:** stops at the clip's original end going right, and at the minimum length going left.
   - **Left edge:** stops at the clip's original start (or time 0) going left, and at the minimum length going right.
   - Scrolling still works while the limit is off screen, so a zoomed-in user can drag an edge back out to an original end they can't see.
   - The rule for "can this edge still move this way" sits beside the clamp in `Workspace.trim_clip`, which owns the limits. The timeline asks it rather than working the limits out again.
   - Other drags are unchanged.
2. **README:** add three points to the trim row:
   - An edge placed off the grid with Shift stays there until the clip is moved.
   - A plain move snaps the clip's visible start to the grid; Shift keeps its time.
   - Duplicate places the copy straight after the visible end.
3. **DESIGN_NOTES to-do:** add drag-in auto-scroll, and mute and solo, as "seen in studio testing 2026-11-12, not yet built".
4. **TEST_CHECKLIST 8d:**
   - Commit the tester's ticks, which are in the working tree now.
   - Add one unticked line: hold a trim drag past the limit at the window edge and check the view doesn't scroll. Then zoom in so the original end is off screen and check the drag still scrolls to reach it.
5. **Tests (headless):**
   - When the edge is pinned and the pointer is past the window edge, an auto-scroll tick doesn't move the scroll bar.
   - When the limit is off screen, it does move.
   - Use the fixtures already in `tests/test_clip_trims.py`. The last attempt failed with "fixture 'win' not found".
6. Run the whole suite, then commit on `feature/clip-edge-trims`. **Don't push.**

## Rules for the build session

- Build only these steps, and only when the user says so.
- If the code doesn't fit the plan, stop and ask rather than designing around it.
- Don't switch branches, don't commit anywhere but `feature/clip-edge-trims`, and don't push.
