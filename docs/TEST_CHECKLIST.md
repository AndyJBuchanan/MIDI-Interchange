# Manual Test Checklist

Hand tests for the clip-assembly feature (`feature/clip-assembly`), plus a short regression pass. Reuse it for later features: add a section, keep the regression pass.

Wherever a step changes something, also check that one ⌘Z undoes the whole step.

Record interop results (does a drag work with an app at all) in the README checklist, and the detail in [INTEROP_FINDINGS.md](INTEROP_FINDINGS.md). Don't claim compatibility until it has actually been tested.

## 1. Drop placement (single file, one track)

- [x] While you drag over the window, the insertion cursor and label follow the mouse and snap to beats. Holding Shift turns snapping off.
- [x] Drop on a lane whose track has the **same name** (try different capitals and extra spaces): the clip lands on that track at the cursor time.
- [x] Drop on a lane with a **different name**: you get a new track at the cursor time, and the label says *names differ*.
- [x] Drop on a track you've **renamed**: it still matches the original name.
- [x] Drop on a **track header**: it lands at bar 1 under the same name rules.
- [x] Drop on the **blank area below the tracks**: new track at the cursor time, shown with a dashed box.
- [x] Drop on the **export panel or elsewhere**: new track at bar 1.
- [x] Drop onto an **empty workspace**: it works, and the tempo comes from the dropped file.

## 2. Multi-track file

- [x] Drop a Staccato round-trip file on one of its matching tracks. Every same-named track gets its clip, and any leftover tracks become new tracks. The label lists the track names.
- [x] Drop the same file on a **track that doesn't match**: everything becomes new tracks.
- [x] Drop it on a **blank area**: everything becomes new tracks.
- [x] At the **same position with the same lengths**, the existing clips are replaced (no red tint). The message says "replacing N".
- [x] At a **shifted position**, or with a **different length**, both clips stay and the overlap is tinted red.
- [x] One ⌘Z restores the replaced clips.

## 3. Several files at once (Finder multi-select)

- [x] The dialog appears only for several **files**, not for one file with several tracks.
- [x] **End to End** (changed 2026-11-10): the files are laid in sequence from the cursor on **one** new track named after the first file's track, whatever the names. The dialog says the track's name. Multi-track files line up by position (first tracks together, second tracks together, …).
- [x] After End to End with the `samples/assembly/bass_part_*` files, every clip's notes draw **inside** the clip, high and low parts alike (fixed 2026-11-10: wide pitch ranges used to overflow the lane). Also check a drum track and a small lane height.
- [x] **All at Cursor**: each file starts at the cursor on its own tracks.
- [x] **Cancel** imports nothing. Check the source app isn't left hanging.
- [x] Dropped on a matching lane: the name-matching rules from sections 1 and 2 still apply.

## 4. DAW workflow (the real use case)

- [x] Drag parts out of Cubase **one at a time** and drop each on its matching track at the right bar. Do this for several tracks.

Reason and RapidComposer can't drag MIDI out (they only export files), so they have no drag test here.

## 5. Moving and copying clips

- [x] **Option-drag** moves a clip in time, and onto another track.
- [x] **Option-drag below the last track** creates a new track. Also drag through another lane first; the new track should keep the **original** track's name. A clip that is alone on the last track stays put (a new track would look identical); Option-⌘ (copy) still makes one.
- [x] **Option-Shift-drag** changes track but keeps the clip's time.
- [x] **Option-⌘-drag** copies; the original stays put.
- [x] A track left with no clips is removed, and ⌘Z undoes the whole move (the track comes back with its clip).
- [x] Dragging near the edge of the view scrolls it.
- [x] Try all of the above with a **trackpad** as well as a mouse.
- [x] A plain drag (no modifiers) still creates and edits ranges as before.

## 6. Clip right-click menu

- [x] **Duplicate Clip** places the copy straight after the original.
- [x] **Butt Against Previous Clip** closes the gap. It does nothing on the first clip.
- [x] **Move Clip to Track ▸** moves it to an existing track, or to a **New Track**.
- [x] **Delete Clip** removes it. Deleting the last clip removes the track.
- [x] The **Track ▸** submenu offers the usual track operations.
- [x] **Solo for Export**, then right-click the soloed track ▸ **Unsolo**: the previous track selection comes back. Soloing another track in between still restores the original selection.

## 7. Track operations

- [x] **Merge Into ▸** another track puts all the clips on the target track and removes the source track.
- [x] The track header shows "N clips · M sources" for a mixed track.
- [x] **Source Info** is a proper dialog: track summary, a table of clips (position, channels, notes, source), and the sources with their details. Clicking a clip selects its source; Show in Folder opens the file's folder.
- [x] Rename, reorder, remove, solo and the export checkbox still work on assembled tracks.

## 8. Export of assembled tracks

The default export mode is now **Ranges · rebase & concatenate** (2026-11-10). Check the export mode before each test.

- [x] Use **Save MIDI…** and **Drag MIDI out** into Cubase and Staccato. Clips from several sources arrive on one track, in the right places.
- [x] Overlapping clips export with both clips' notes merged, and there are no stuck notes.
- [x] Combine sources with **different PPQ** (e.g. Cubase + Reason): the timing is still correct.
- [x] A clip moved to a track with **another MIDI channel** keeps its own channel. This is expected for now (DESIGN_NOTES Risk 9); just note how the DAW handles it. *Reason 14 splits such a track into one track per channel (2026-11-10).*
- [x] Range export across clip joins: notes at the edges are cut cleanly, and a rebased range lands at the drop position.

## 9. New document

- [x] **⌘N**, the toolbar button and File ▸ New all clear the workspace.
- [x] ⌘Z restores everything, including tracks, ranges and tempo.
- [x] Export settings survive ⌘N.
- [x] ⌘N on an empty workspace does nothing and adds no undo step.

## 10. Quick regression

- [x] File ▸ Open, command-line paths and folder drops still import as new tracks at bar 1.
- [x] Ranges: create, resize, move, Tab to cycle, delete, and type positions as bar.beat.tick.
- [x] Zoom, lane height and the tempo map dialog.
- [x] A long undo/redo chain mixing drops, moves and the clip menu.

## 11. Windows (release time only)

Windows is a secondary platform: it isn't tested during normal development, only before a release (RELEASING.md, step 3). Leave this section unticked until then.

- [ ] Use **Alt** in place of Option and **Ctrl** in place of ⌘ for the clip drags. Check the drop cursor and the multi-file dialog.
