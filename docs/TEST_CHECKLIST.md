# Manual Test Checklist

Hand tests for the clip-assembly feature (`feature/clip-assembly`), plus a short regression pass. Reuse it for later features: add a section, keep the regression pass.

Wherever a step changes something, also check that one ⌘Z undoes the whole step.

Record interop results (does a drag work with an app at all) in the README checklist, and the detail in [INTEROP_FINDINGS.md](INTEROP_FINDINGS.md). Don't claim compatibility until it has actually been tested.

## 1. Drop placement (single file, one track)

- [x] While you drag over the window, the insertion cursor and label follow the mouse and snap to beats. Holding Shift turns snapping off.
- [x] Drop on a lane whose track has the **same name** (try different capitals and extra spaces): the clip lands on that track at the cursor time.
- [x] Drop on a lane with a **different name**: you get a new track at the cursor time, and the label says *nothing matches “…”* and why (wording changed 2026-11-10; was *names differ*).
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

## 8a. Per-range track exclusion (`feature/range-track-exclusion`)

- [x] Draw a range: each lane gets a checkbox at the range's inner left edge, ticked to match the track toggles (an off track starts unticked).
- [x] Click a checkbox: it untick/ticks, the lane section inside the range is hatched/clear, and ⌘Z undoes it. Two quick clicks flip it twice and don't open the range editor.
- [x] Change a track toggle after drawing the range: the range's checkboxes don't change.
- [x] Turn a track off but leave it ticked in a range: its notes from that range are still exported.
- [x] Rebase with two ranges, a track excluded from the first: in the DAW its notes appear only in the second range's part, at the right position.
- [x] Separate: each file holds only the tracks ticked in its range; a range with nothing ticked gives no file.
- [x] A track unticked in every range is missing from the file (and from the "N of M tracks" counts).
- [x] Whole export ignores the range checkboxes and uses the track toggles.
- [x] A very narrow range shows no checkboxes; right-click it: the track list, Include All, Exclude All and Reset to Track Toggles all work.
- [x] Drop a new file after drawing a range: its track is ticked in the range. Option-drag a clip from an excluded track to a new track: the new track is unticked.
- [x] The bottom panel shows "N of M tracks" for the selected range.

## 8b. Studio round fixes (2026-11-10)

- [x] Two named ranges, several tracks, Rebase: the Save dialog and the dragged file are named "Verse + Chorus".
- [x] Two ranges with the same name, Separate drag: both files arrive (the second gets " (2)").
- [x] Switch a track off while a range includes it: its clips are in colour inside the range, grey outside.
- [x] Option-click a track toggle: the track and its checkbox in every range change together; ⌘Z undoes both. A plain click still changes only the track.
- [x] Round trip (studio report, not reproduced on the dev Mac): open `samples/assembly/seven_tracks_A-G.mid`, draw three ranges, tick A B / C D / E F, Separate, drag out to Finder, ⌘N, then drop each file in turn onto track A. Expect A B, then C D added, then E F added, each with its own notes. If it goes wrong, keep the files and note the exact drop spot.
- [x] Scroll the track list vertically: headers disappear under the "TRACKS n/m" band instead of drawing over it.

## 8c. Studio round fixes 2 (2026-11-10)

- [x] ⌥ + mouse wheel changes lane height gently: one wheel notch is a small step (half or less of before), and a trackpad stroke no longer jumps.
- [x] Separate drag: files are named by their range alone ("Verse.mid", "Chorus.mid"); two ranges with the same name give "Dank.mid" and "Dank (2).mid". Save MIDI… in Separate mode still appends the range name to the name you type.
- [x] New `samples/assembly/seven_tracks_A-G.mid`: 12 bars in three 4-bar sections. Each track has its own shape (A rising, B falling, C zigzag, D chord, E long note, F long-short-short, G high-low), played once per bar in bars 1–4, twice in 5–8, three times in 9–12. Round trip: three ranges on the sections (bars 1–5, 5–9, 9–13), tick A B / C D / E F, Separate, drag out, ⌘N, drop each file onto track A. Check by eye that A B show one repeat per bar, C D two, E F three.
- [x] Staccato round trip with a new generation: open the Staccato song, export or drag some tracks to Staccato, generate, and drag the result back onto one of its tracks. Tracks named "part - <new song>" land on the matching "part - <old song>" tracks; the status bar says "matched ignoring song titles …". (Built test: tests/test_song_matching.py, from the Industrial EBM Anthem sample renamed the way Staccato did.)
- [x] Two DAW clips named "Lead - Verse" and "Lead - Chorus": dropping the second onto the first's track makes a new track (not a song title).
- [x] Exports now carry the song title. Every MIDI file has a first track that holds only the tempo and time signature; MIDI Interchange now names that track after the song ("Industrial EBM Anthem") when all the exported clips come from one song, as Staccato's own files do. Check that apps don't mind: open the Staccato song, drag it out whole into Cubase, Logic and Reason, and check each gets the same tracks and tempo as before, with no extra empty track called "Industrial EBM Anthem". (Note if an app shows the name somewhere, e.g. as a song or marker title.)
- [x] Staccato round trip again (round 2 failed with the drop on Heavy EBM Drums; not reproduced on the dev Mac with the same files and steps, round 3 adds the reason to the message): open the Staccato song, drag a new Staccato generation onto Heavy EBM Drums. While dragging, the preview says "Onto “Heavy EBM Drums - …” …"; after the drop, the parts land on their tracks and the status bar says "matched ignoring song titles …". **If it makes new tracks instead, copy down the status bar message**: it now ends "new because nothing matches “…” (…)" with the file's and the track's song titles.
- [x] The preview and the result always agree: whatever the cursor says before you let go ("Onto …" or "New track(s) …: nothing matches …") is what happens.

## 8d. Clip edge trims (`feature/clip-edge-trims`)

- [x] ⌥-hover a clip's left or right edge: the cursor turns to ↔. Without ⌥ nothing changes, and a plain drag there makes a range.
- [x] ⌥-drag the right edge in: the clip shortens and its notes are cut at the edge. Drag it back out: it stops at where the clip originally ended. Same for the left edge and the original start.
- [x] The edge snaps to the grid; hold Shift to place it freely. The two edges can't cross.
- [x] One ⌘Z undoes a whole trim drag. Right-click a trimmed clip ▸ **Restore Full Clip** (the item isn't there on an untrimmed clip); ⌘Z brings the trim back.
- [x] Trim a clip so an edge falls inside a long note, then **drag out to a DAW** (try Cubase and Reason): the note starts at the edge (or is missing if that option is turned off in code), a note over the right edge ends at it, and nothing hangs. Check the instrument sound (program, volume) is right at the start.
- [x] Move, ⌥⌘-copy, Duplicate, Butt Against Previous and Merge Into keep the trim. Butting uses the trimmed start.
- [x] Zoom far out so a clip is only a few pixels wide: ⌥-drag moves it instead of trimming.
- [x] Drop a file onto a trimmed clip's exact visible start and end: it replaces it.
- [x] Hold a trim drag past the clip's original end with the pointer at the window edge: the view doesn't scroll. Then zoom in so the original end is off screen: the drag does scroll, so you can reach it.

## 8e. About box (`feature/about-box`)

- [x] Click **About** at the right end of the toolbar: a dialog opens with the icon, "MIDI Interchange", the version, the description, "© 2026 Andy Buchanan" and the GitHub link.
- [x] Click the link: the GitHub page opens in the default browser.
- [x] OK, Return and Esc each close the dialog.
- [x] Resize the window: the About button stays at the right edge.
- [x] Repeat in the packaged app (the icon still shows).
- [ ] Windows, at release: check the same button.

## 8f. Drag-in auto-scroll (`feature/drag-in-autoscroll`)

- [x] Drag a MIDI part from Cubase (or a MIDI file from Finder) over the timeline's rightmost 20 px and hold still: it scrolls, the insertion label follows, and the timeline keeps growing beyond its old end. Repeat at the left edge to scroll back.
- [x] Drop late in the song: the clip lands at the indicated time, stays in view, and the timeline ends at the content end plus normal padding. Scroll far right, then back left before dropping: the timeline doesn't keep the furthest drag reach.
- [x] Repeat the long drag and leave the window: scrolling stops, timeline length and horizontal scroll return to where they were before the drag. Re-enter and check a fresh drag works.

Esc cancellation failed in the studio and is deferred to [future work](DESIGN_NOTES.md#to-do-agreed-not-started) by agreement (2026-11-12), outside this feature's completion checks. Finder → Finder cancels; Finder → MIDI Interchange, Cubase → Finder and Cubase → MIDI Interchange do not. The automated drag-leave test doesn't cover native Esc cancellation.

- [x] Drag a file whose destination lane is above or below the visible tracks: the fixed timeline ruler still shows the drop time with an amber line and triangle. Move the pointer and auto-scroll; the ruler marker follows. Drop or leave the window: the marker disappears. (Studio retest passed, 2026-11-12.)
- [x] Move the pointer over the track headers or export panel during the drag: auto-scroll stops and the usual drop placement applies.
- [ ] Drop several files, Cancel the "Place dropped files" dialog, and check the view returns to where it was before the drag.
- [x] Option-drag an existing clip past the end: the timeline grows. Draw or resize a range past the end too. Release: only the normal content/range padding remains. Check trim scrolling still stops at the clip's original extent.

## 8g. Mute, solo and range track locks (`feature/mute-solo`)

- [ ] Track M/S buttons toggle mute/solo. Several solos work together. Option-click S solos only that track; repeat on the only solo to unsolo it.
- [ ] Mute a track, solo it, then unsolo it: it exports during solo and returns to muted afterwards. Its M indication is greyed while solo overrides it. Compare the display with Cubase.
- [ ] Mute a soloed track: solo clears. Unmute it: solo stays off. Option-click M applies the clicked track's new mute state to all tracks; muting all clears all solos.
- [ ] The boxed M/S buttons above the tracks light when needed and clear all mutes/solos. Clear mutes also clears a mute remembered under solo; unsolo afterwards leaves that track unmuted.
- [ ] Create a range: its greyed checkboxes show the current global M/S result. Clicking them changes nothing. Changing track/global M/S updates all unlocked ranges.
- [ ] Click the padlock in the range header: the range locks and its checkboxes become editable. Global M/S changes leave its track choices alone. Click again: the range immediately follows global M/S and its checkboxes become greyed.
- [ ] Right-click a range: Include All/Exclude All lock it and apply the choice; Unlock resumes following global M/S. Per-track menu choices are disabled while unlocked. Check a narrow range through its context menu.
- [ ] Import a new track: it is included in locked ranges and follows global M/S in unlocked ones. Repeat while solo is active.
- [ ] Lane colours inside ranges match their actual export choices, including a globally muted track included in a locked range. Outside ranges, colours follow global M/S.
- [ ] Save and drag whole and range exports to Cubase and Reason, using Preserve, Rebase and Separate. Check track membership and notes, especially locked ranges that override global M/S.
- [ ] Undo/redo each action: global changes and their unlocked-range updates undo together; locks, manual track choices and remembered mutes restore correctly.

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

- [x] Use **Alt** in place of Option and **Ctrl** in place of ⌘ for the clip drags. Check the drop cursor and the multi-file dialog.
