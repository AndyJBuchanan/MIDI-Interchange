# Plan: drag-in auto-scroll and timeline length

Status: **built, studio-tested and merged to main via PR #7** (2026-11-12). All current feature checks passed, including leave/re-enter restoration and the ruler drop marker. Esc investigation is deferred to future work by agreement. Automated suite: 210 tests passed. Cancelling the multi-file "Place dropped files" dialog restores the pre-drag view.

This came from the clip-trims studio test (2026-11-12): MIDI dragged in from another app can't reach later in the song, because the timeline doesn't scroll at the edge.

**Behaviour:**
- **Dragging MIDI in from another app:** holding the pointer near the left or right edge of the timeline scrolls it, as a clip drag does. The timeline grows ahead of the pointer, so a drop can go anywhere later in the song.
- **On drop:** the timeline's length goes back to the normal rule, which is content end plus padding. It doesn't stay at the furthest point the drag reached, so it is no longer than needed for the dropped clip's end.
- **When the drag leaves the window:** the timeline goes back to its length before the drag, and to its scroll position. Native Esc cancellation was originally included, but its investigation is now deferred to future work; it is not a completion requirement for this branch.
- **Moving clips** already grows the timeline: the length follows the content's end while the clip moves. The shared code below keeps that, and also covers range drags and trims.

**One mechanism for every drag (`ui/timeline.py`):**
- **Timeline length:** comes from one function. It takes the larger of the content-and-ranges end and a temporary "drag reach", the furthest point any drag in progress has asked to see, then adds the existing padding (32 beats, at least 128). It replaces the body of `total_beats`.
- **One auto-scroll path:**
  - `_check_autoscroll`/`_autoscroll_tick` currently require an internal `_drag` and call `_drag_to`.
  - They become one path that every drag uses. While the pointer is near an edge, it scrolls, extends the drag reach and tells the active drag the pointer has moved.
  - For an internal drag, that means `_drag_to`. For a drag from another app, it means the drop-indicator update in `MainWindow`.
- **Ending a drag:**
  - On drop or release, clear the drag reach and recompute the length.
  - On cancel, restore the length and scroll value saved when the drag started.
- **`MainWindow` drag-in handlers:**
  - `dragEnterEvent`, `dragMoveEvent`, `dragLeaveEvent` and `dropEvent` start, feed and end this path. They stop the timer on leave and on drop.
  - Use the same 20 px edge zone and speed as clip drags.
- **Risk to check in the studio first:** during a drag from another app on macOS, Qt sends move events only when the mouse moves. The scroll timer has to read the pointer itself (`QCursor.pos()`). If that doesn't update during a drag from another app, scrolling still works, but the drop indicator follows only when the mouse moves.

**Tests (headless):**
- The length function with and without a drag reach.
- Restoring the length on cancel.
- An external drag simulated with `QDragMoveEvent` near the right edge scrolls, then a cancel restores the length and scroll position.
- A drop shrinks the length back to the new content.
- Clip moves still extend the length.

**Checklist:** drag in from Cubase or a MIDI file from Finder and hold at the right edge, then drop late in the song; repeat and leave the window to restore the view; move a clip past the end. Retest the ruler drop marker with a destination lane outside the vertical view.

Implementation: external previews and internal gestures share the timeline's edge-scroll timer and temporary reach. The timer reads `QCursor.pos()` on each tick. A drag-leave notification clears the reach and restores the initial scroll. Drop placement is captured before clearing the reach; after import the view keeps its drop position within the new content length. Headless coverage is in `tests/test_drag_autoscroll.py`. The initial assumption that Esc would cancel the source drag and produce a drag-leave notification was not borne out in the Finder studio test; the automated leave test does not verify native Esc cancellation.

Studio follow-up: a drop whose destination lane is outside the vertical view had no visible position indicator. A fixed ruler line and triangle now show the drop time regardless of the destination lane's visibility. Paint tests cover destinations both above and below the view; manual retest passed (2026-11-12).

Esc follow-up: Finder → Finder cancels; Finder → MIDI Interchange does not. Cubase → Finder and Cubase → MIDI Interchange both fail to cancel. Details are recorded in [INTEROP_FINDINGS.md](../INTEROP_FINDINGS.md#esc-during-incoming-drags-studio-report-2026-11-12). The Cubase behaviour is not specific to this destination; the Finder difference is still unexplained. By user agreement (2026-11-12), investigation is deferred to [future work in DESIGN_NOTES.md](../DESIGN_NOTES.md#to-do-agreed-not-started), with no further investigation on this branch.

## Rules for the build session

- Build only this plan, and only when the user says so.
- If the code doesn't fit the plan, stop and ask rather than designing around it.
- Work on the feature branch named above. Don't switch branches, and don't push.
