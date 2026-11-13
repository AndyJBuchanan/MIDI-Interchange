# Session persistence — manual verification

Branch: `feature/session-persistence`. Run from source with `.venv/bin/python main.py`; no build/release is required. Persistence is on by default. All boxes below are for manual results, not automated test results.

- [ ] Assemble several sources: move/copy clips, trim edges, rename/recolour tracks, set a channel override and a tempo source. Add named/unnamed ranges, including a locked range with an independent selection. Set mute/solo with a remembered mute under solo. Quit and reopen: everything returns correctly.
- [ ] Change export mode, trim-silence setting, snap, selected range, zoom, lane height and scroll. Quit/reopen: settings and view return (scroll clamps if the window is smaller), with Undo/Redo initially unavailable.
- [ ] Use the real Cubase lyric clip and a temporary DAW drag. After quitting, move/remove the original input files or temp file; reopen and verify the restored clips, lyrics and exports in the DAW.
- [ ] Compare Whole, Preserve, Rebase and Separate exports before/after reopening, including overridden channels and locked-range exclusions.
- [ ] Edit, then leave the app idle for at least two minutes. Make another edit and force-quit promptly. Reopen: a recovery notice appears and the saved checkpoint returns; the latest unsaved edit can be absent.
- [ ] Keep editing/scrolling beyond two minutes, then leave the app idle for 15 seconds. Confirm normal work stays responsive and a checkpoint follows the idle interval. Repeat with a large workspace.
- [ ] Hold an internal clip/range/trim drag or an external drag stationary beyond the checkpoint time. Confirm the gesture stays responsive; leave the drag and then idle. Repeat with an open dialog.
- [ ] Quit immediately after editing, including while a checkpoint may be writing. Reopen: the latest state is present. A track/range name still being edited when Quit is chosen should be saved.
- [ ] Choose New, then quit/reopen: the workspace stays empty. Undo New before quitting: the restored contents are saved instead.
- [ ] With the app running, open more MIDI files from Finder/Explorer or run `.venv/bin/python main.py "path/to/file.mid"`. Files join the existing workspace; no second window opens. Try multiple paths, spaces and non-ASCII names.
- [ ] Launch a second time with no files: the existing window comes forward. Repeat a file open while the original app is starting/restoring.
- [ ] After force-quitting, relaunch normally: ownership recovers without deleting a lock file manually.

Notes/failures:

