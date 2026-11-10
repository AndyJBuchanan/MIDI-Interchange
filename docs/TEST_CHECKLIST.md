# Manual Test Checklist

Hand tests for the clip-assembly feature (`feature/clip-assembly`), plus a short regression pass. Reuse it for later features: add a section, keep the regression pass.

Wherever a step changes something, also check that one ⌘Z undoes the whole step.

Record interop results (does a drag work with an app at all) in the README checklist, and the detail in [INTEROP_FINDINGS.md](INTEROP_FINDINGS.md). Don't claim compatibility until it has actually been tested.

## 1. Drop placement (single file, one track)

- [ ] While you drag over the window, the insertion cursor and label follow the mouse and snap to beats. Holding Shift turns snapping off.
- [ ] Drop on a lane whose track has the **same name** (try different capitals and extra spaces): the clip lands on that track at the cursor time.
- [ ] Drop on a lane with a **different name**: you get a new track at the cursor time, and the label says *names differ*.
- [ ] Drop on a track you've **renamed**: it still matches the original name.
- [ ] Drop on a **track header**: it lands at bar 1 under the same name rules.
- [ ] Drop on the **blank area below the tracks**: new track at the cursor time, shown with a dashed box.
- [ ] Drop on the **export panel or elsewhere**: new track at bar 1.
- [ ] Drop onto an **empty workspace**: it works, and the tempo comes from the dropped file.

## 2. Multi-track file

- [ ] Drop a Staccato round-trip file on one of its matching tracks. Every same-named track gets its clip, and any leftover tracks become new tracks. The label lists the track names.
- [ ] Drop the same file on a **track that doesn't match**: everything becomes new tracks.
- [ ] Drop it on a **blank area**: everything becomes new tracks.
- [ ] At the **same position with the same lengths**, the existing clips are replaced (no red tint). The message says "replacing N".
- [ ] At a **shifted position**, or with a **different length**, both clips stay and the overlap is tinted red.
- [ ] One ⌘Z restores the replaced clips.

## 3. Several files at once (Finder multi-select)

- [ ] The dialog appears only for several **files**, not for one file with several tracks.
- [ ] **End to End**: the files are laid in sequence from the cursor, and same-named tracks share one track.
- [ ] **All at Cursor**: each file starts at the cursor on its own tracks.
- [ ] **Cancel** imports nothing. Check the source app isn't left hanging.
- [ ] Dropped on a matching lane: the name-matching rules from sections 1 and 2 still apply.

## 4. DAW workflow (the real use case)

- [ ] Drag parts out of Cubase **one at a time** and drop each on its matching track at the right bar. Do this for several tracks.
- [ ] Do the same with **Reason** and **RapidComposer** parts.

## 5. Moving and copying clips

- [ ] **Option-drag** moves a clip in time, and onto another track.
- [ ] **Option-drag below the last track** creates a new track. Also drag through another lane first; the new track should keep the **original** track's name.
- [ ] **Option-Shift-drag** changes track but keeps the clip's time.
- [ ] **Option-⌘-drag** copies; the original stays put.
- [ ] A track left with no clips is removed, and ⌘Z brings it back.
- [ ] Dragging near the edge of the view scrolls it.
- [ ] Try all of the above with a **trackpad** as well as a mouse.
- [ ] A plain drag (no modifiers) still behaves as before.

## 6. Clip right-click menu

- [ ] **Duplicate Clip** places the copy straight after the original.
- [ ] **Butt Against Previous Clip** closes the gap. It does nothing on the first clip.
- [ ] **Move Clip to Track ▸** moves it to an existing track, or to a **New Track**.
- [ ] **Delete Clip** removes it. Deleting the last clip removes the track.
- [ ] The **Track ▸** submenu offers the usual track operations.

## 7. Track operations

- [ ] **Merge Into ▸** another track puts all the clips on the target track and removes the source track.
- [ ] The track header shows "N clips · M sources" for a mixed track, and **Source Info** lists every source.
- [ ] Rename, reorder, remove, solo and the export checkbox still work on assembled tracks.

## 8. Export of assembled tracks

- [ ] Use **Save MIDI…** and **Drag MIDI out** into Cubase and Staccato. Clips from several sources arrive on one track, in the right places.
- [ ] Overlapping clips export with both clips' notes merged, and there are no stuck notes.
- [ ] Combine sources with **different PPQ** (e.g. Cubase + Reason): the timing is still correct.
- [ ] A clip moved to a track with **another MIDI channel** keeps its own channel. This is expected for now (DESIGN_NOTES Risk 9); just note how the DAW handles it.
- [ ] Range export across clip joins: notes at the edges are cut cleanly, and a rebased range lands at the drop position.

## 9. New document

- [ ] **⌘N**, the toolbar button and File ▸ New all clear the workspace.
- [ ] ⌘Z restores everything, including tracks, ranges and tempo.
- [ ] Export settings survive ⌘N.
- [ ] ⌘N on an empty workspace does nothing and adds no undo step.

## 10. Quick regression

- [ ] File ▸ Open, command-line paths and folder drops still import as new tracks at bar 1.
- [ ] Ranges: create, resize, move, Tab to cycle, delete, and type positions as bar.beat.tick.
- [ ] Zoom, lane height and the tempo map dialog.
- [ ] A long undo/redo chain mixing drops, moves and the clip menu.

## 11. Windows

- [ ] Use **Alt** in place of Option and **Ctrl** in place of ⌘ for the clip drags. Check the drop cursor and the multi-file dialog.
