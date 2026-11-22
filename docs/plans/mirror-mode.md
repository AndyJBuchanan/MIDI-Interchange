# Plan: mirror mode, watching one file

Status: **plan agreed (2026-11-22); build waits for the step 0 save logs.** Branch, when built: `feature/mirror-mode` from `release/0.5.0`.

A separate mode in which the app watches one MIDI or project file and re-imports it every time it's saved. You keep working in Cubase or Reason; whatever you last saved is on the timeline, ready to drag out.

**The build waits for the save evidence** (step 0, below). Only the owner can save from Cubase and Reason, and several numbers and choices depend on how they write.

## Why

Today, to move the latest version of a song you re-open or re-drop the project after every save, and re-make your ranges. Mirror mode keeps the palette in step with the saved project. The ranges, track locks and mute/solo you set up survive each save, so dragging out the current state is one gesture.

## Step 0: how Cubase and Reason save (owner-run, before the build)

**This runs on the owner's Mac** (this MacBook counts as a studio Mac). Nothing is read from it until the owner pastes or copies the output across.

1. Save the script below as `watch_save.py` anywhere outside the repository (it isn't committed). It's stdlib Python, so the Mac's `python3` will do.
2. Run `python3 watch_save.py "/path/to/Song.cpr" | tee cubase-save.txt`.
3. While it runs, do the scenarios below, then press Ctrl-C.
4. Repeat with a Reason song (`reason-save.txt`).

```python
#!/usr/bin/env python3
"""Log how an app saves one file. Run, save in the app, then press Ctrl-C.

Every 50 ms, stat the file and every entry in its folder; print each change
(new / gone / inode, size or mtime changed) with a timestamp. Read-only.
"""
import datetime
import os
import sys
import time


def snapshot(folder):
    out = {}
    try:
        names = os.listdir(folder)
    except OSError as exc:
        return {"<folder unreadable>": (0, 0, str(exc))}
    for name in names:
        try:
            st = os.stat(os.path.join(folder, name), follow_symlinks=False)
        except FileNotFoundError:
            continue
        out[name] = (st.st_ino, st.st_size, st.st_mtime_ns)
    return out


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: python3 watch_save.py /path/to/project-file")
    path = os.path.abspath(sys.argv[1])
    folder, target = os.path.split(path)
    start = time.monotonic()
    prev = snapshot(folder)
    print(f"{datetime.datetime.now():%H:%M:%S} watching {path}")
    print(f"  {len(prev)} entries in the folder; file present: {target in prev}")
    if target in prev:
        ino, size, mtime = prev[target]
        print(f"  file: inode {ino}, {size} bytes, mtime_ns {mtime}")
    try:
        while True:
            time.sleep(0.05)
            cur = snapshot(folder)
            t = time.monotonic() - start
            clock = f"{datetime.datetime.now():%H:%M:%S.%f}"[:-3]
            for name in sorted(set(prev) | set(cur)):
                a, b = prev.get(name), cur.get(name)
                if a == b:
                    continue
                mark = "*" if name == target else " "
                if a is None:
                    print(f"{t:9.3f} {clock} {mark} NEW     {name}  inode {b[0]}, {b[1]} bytes")
                elif b is None:
                    print(f"{t:9.3f} {clock} {mark} GONE    {name}  inode {a[0]}")
                else:
                    what = []
                    if a[0] != b[0]:
                        what.append(f"inode {a[0]} -> {b[0]}")
                    if a[1] != b[1]:
                        what.append(f"size {a[1]} -> {b[1]}")
                    if a[2] != b[2]:
                        what.append(f"mtime +{(b[2] - a[2]) / 1e6:.1f} ms")
                    print(f"{t:9.3f} {clock} {mark} CHANGED {name}  " + ", ".join(what))
            prev = cur
    except KeyboardInterrupt:
        print("stopped")


main()
```

**Scenarios, in each DAW:**
- Save once after a small edit.
- Save a large project (many tracks and parts).
- Save twice quickly.
- Open and close the project without saving.
- Let auto-save run once, if it's on.

**What to record in this plan**, per DAW and version:
- **In place or replaced:** whether the file's inode stays the same (written in place) or changes (temp file, then rename).
- **Timing:** how many size and mtime changes one save makes, and the time from the first change to the last.
- **Gaps:** whether the file is ever GONE, and for how long.
- **Extra files:** any that appear or disappear (temp names, `.bak`, `.csh`, auto-save folders), and whether they stay.
- **Untouched writes:** whether opening, closing or auto-save touches the project file itself.

**Choices that depend on this evidence:**
- the settle time and poll interval;
- how long a missing file is tolerated before the banner says so;
- whether any temp or backup names need ignoring;
- confirmation that polling is the right mechanism (it's recommended either way, below);
- the manual test's wording.

## Behaviour

### Entering and leaving

- **File ▸ Open & Mirror MIDI/Project File…** (and a toolbar button **Mirror…** after Open). It takes one file of any format the app opens directly: MIDI, DAWproject, Cubase (`.cpr`) or Reason (`.reason`), through the existing readers (`interchange/readers.py`). There's no mirror toggle on a normal Open.
- **Mirroring owns the workspace.**
  - Entering clears the workspace and imports the file at bar 1, as new tracks with no name matching (`Placement()` with no target).
  - Entering can't be undone, because unmirroring starts a clean history. So when the workspace isn't empty, a dialog asks first (design question 1).
  - The first import zooms to fit; later re-imports keep the zoom and scroll.
- **Unmirror** (the banner's button, and File ▸ Unmirror):
  - stops the watch;
  - keeps the last imported state as a normal workspace;
  - **clears undo and redo**, so the new history starts clean.

  The workspace isn't re-read on the way out. Editing returns at once.
- Open & Mirror is disabled while mirroring: unmirror first.

### Re-importing on save

- The app polls the file (see *Watching*). When a change has settled, it reads the file on a worker thread, then applies the result on the main thread.
- **A re-import makes no undo step.** It replaces the sources, the tracks and the tempo map (the new source becomes the tempo source). Mirroring stays at bar 1.
- **What carries across** (`core/mirror.py`, pure):
  - **Track matching** uses the rule placement already uses for drops (`placement._assign`). Names are compared case-insensitively against each old track's current and original names. Exact matches pair first, and a name repeated in the file pairs in order with the same-named tracks.
    - The song-title level can't fire within one file's tracks, so it's harmless.
    - The readers themselves don't match anything. Their `preserve_track_state` only keeps the project's *own* saved mute and solo on new tracks (`Workspace.add_import`); it carries nothing from one import to the next.
    - A track renamed in the DAW therefore arrives as a new track (design question 3).
  - **A matched track keeps its old track id**, so range selections and locks (`Range.excluded` holds track ids) keep applying. It also keeps its colour, export channel and controller override. The clips, channels and name come from the new import.
  - **Mute and solo** are carried by the rule in design question 2.
  - **New tracks** get the next colour and join ranges as any new track does (`Workspace._add_track`: included in every range, then unlocked ranges follow mute/solo).
  - **Tracks that have gone** disappear. Their ids are dropped from range selections.
  - **Ranges** are kept unchanged by time (quarter notes from bar 1), including names, locks and selection. A range now past the end stays where it is.
  - **View state** (zoom, scroll, lane height, Show Markers, the controller picker) and **export settings** are untouched.
- **The status bar reports every outcome:**
  - after a successful read: "Mirror: Song.cpr re-imported at 14:02:31: 12 tracks (1 new, 1 gone)";
  - the banner shows "Last updated 14:02:31".
- **Failed or half-written read:**
  - The last good import stays.
  - The status bar says what failed: "Mirror: Song.cpr couldn't be read at 14:03:05 (reason). Keeping the version from 14:02:31; retrying."
  - The app retries (see *Watching*), and the banner shows "Last read failed".
- **Deferred during gestures:** a finished read isn't applied while a range drag, an external drag or a drag-out is in progress (`timeline.gesture_active`, `ctl.file_drag_active`). It's applied when the gesture ends, as session saves are deferred today.

### Read-only while mirroring

**Allowed**, because it's what you need to pick and hand on material:
- ranges: create, move, resize, rename and delete; the track toggles; Lock/Unlock; Include/Exclude All;
- track mute and solo, including Clear All, Alt-click and the Sources dialog's Solo all source tracks;
- the range selection, Tab and Esc;
- zoom, scroll, lane height, Snap, Show Markers and the controller picker and its buttons;
- export settings, **Save MIDI…**, **Save This Track…** and **drag-out**;
- Source Info and the Sources dialog.

Range and mute changes make **no undo steps** while mirroring: undo would restore an old import. Undo and Redo are disabled.

**Unavailable** (greyed or left out of menus, and refused by the controller as a backstop):

| Entry point | Where |
|---|---|
| New, Open…, Open & Mirror… | `main_window._build_actions` |
| File drops on the window, including the drop preview | `MainWindow.dragEnterEvent`, `dropEvent`: refused, with "Mirroring: unmirror to import" in the status bar |
| Second-launch hand-off and macOS Dock/Open With files | `main.receive` → `MainWindow.import_paths`: refused, with the same notice |
| Clip move and copy (Alt / Alt+Ctrl drag), edge trim (Option drag), split (Cmd/Ctrl-click), M to mute a clip | `Timeline._clip_action`, `mousePressEvent`, `keyPressEvent`; their cursors aren't shown either |
| Clip menu: Mute, Duplicate, Butt Against Previous, Restore Full Clip, Move to Track, Delete | `MainWindow.clip_menu` (the menu shows only the track items that stay allowed) |
| Track menu: Rename, Move Up/Down, Merge Into, Use This Track's Tempo Map, Remove Track | `MainWindow._add_track_actions` |
| Timing ▸ Tempo Map and the ruler's Tempo Map menu | `_fill_tempo_menu`, `header_menu` |
| Track header: the name field, the ✕, the ⋮⋮ grip, the colour box (colour and export channel), the controller box | `track_panel.TrackHeader`, `TrackPanel._grip_*` |
| Undo, Redo | disabled |

**The backstop:** `Controller` gets a `mirroring` flag.
- While it's set, `checkpoint()` does nothing (the export panel and timeline call it directly for range edits).
- Every editing method returns without change: `import_payloads`, `new_document`, `move_clip_live`, `trim_clip_live`, `split_clip`, `toggle_clip_mute`, `restore_clip`, `move_clip_to_track`, `delete_clip`, `duplicate_clip`, `snap_clip_to_previous`, `merge_tracks`, `rename_track`, `set_export_channel`, `set_track_color`, `move_track`, `remove_track`, `adopt_tempo`, `set_track_controller`, and `undo` and `redo`.

So a UI path missed above still can't change the mirror.

### The visual cue

The app has one dark theme (`ui/theme.py`, Fusion with a dark palette), so there's no light mode to design for. The cue never relies on colour alone: the banner and the title bar say it in words.

- **Frame:** a 4 px outline in the mirror colour round the whole central area. It's a mouse-transparent overlay widget, built like `DropOverlay`, drawn above the timeline, panels and export panel.
- **Banner:** a strip across the top of the central area, above the tracks and timeline. It's filled with the mirror colour, with dark text that passes 4.5:1 contrast:
  - "**MIRRORING** Song.cpr · read-only · updates when the file is saved · Last updated 14:02:31";
  - an **Unmirror** button at its right;
  - the file's full path in its tooltip.
- **Title bar:** "MIDI Interchange — Mirroring Song.cpr".
- **Tint:** the chrome takes a cool tint, leaving the lanes and notes as they are so the MIDI stays readable. The chrome is the toolbar, menus, export panel, status bar, track panel background and ruler band.
  - The tint comes from `theme.apply(app, mirror=True)` for the palette.
  - `PANEL_BG`, `RULER_BG` and `INFO_BG` get tinted twins that the track panel and timeline paint while mirroring.
- **Colours** (new constants in `theme.py`):
  - `MIRROR = #1fc3e0` (cyan) for the frame, the banner fill and the toolbar button's checked state;
  - `MIRROR_TEXT = #0b1d22` on the banner;
  - tinted backgrounds mixed 12% toward `MIRROR`.

  Cyan is chosen because it's clear of every colour that already means something:
  - the amber `ACCENT` (ranges, and the drop outline round the window);
  - the red `SOLO` (Solo, controller overrides) and the red overlap tint;
  - the tempo row's light blue `TEMPO_COL`.

  The alternatives are in design question 6.

### Session

- Mirroring isn't saved. The session holds the workspace as it is: the last import, with your ranges and mute/solo, saved on the normal cadence (re-imports mark the session dirty like any change).
- **Relaunch** restores it as a **normal** workspace. The watch is never resumed, so there's no new session field and no schema change.
- **A crash while mirroring:** relaunch restores the last checkpoint (the import current at the last periodic save), with the usual "did not close cleanly" notice. It's a normal workspace; Open & Mirror starts watching again.

### Watching

**Recommended: polling with a settle period**, not `QFileSystemWatcher`.

- `QFileSystemWatcher` drops its watch when the file is replaced by a rename, a common way to save safely. It would also need a folder watch and re-arming, and it behaves differently on macOS and Windows.
- One `os.stat` four times a second costs nothing. It treats in-place writes and replacements the same way, and it's easy to test with a fake clock.

The details:
- **Signature:** `(inode, size, mtime_ns)` of the path. An inode change catches a replacement even when the size and time look alike.
- **Poll** every 250 ms (a `QTimer` on the main thread).
- **Settle:** read only once the signature has stayed the same for **1.0 s** after a change, so a write in progress isn't read. These two numbers are provisional until step 0.
- **One read at a time:** if the file changes again during a read, the result is discarded and the read starts over once it settles (a generation counter).
- **Retry:** after a failed read, retry 2 s later, up to 3 times while the signature stays the same, then wait for the next change. A completed save always changes the signature, so it's always picked up.
- **Missing file:** keep the last import and keep polling. If it's gone for more than 3 s (provisional), the status bar and banner say "Song.cpr not found; waiting for it". When it reappears it's read as a change. See design question 4.
- **What to watch:** every supported format is a single file (`.mid`, `.dawproject` zip, `.cpr`, `.reason`), so only the file itself is watched. A package or folder format would need its own rule if one is ever added.
- **Reads** use the existing `payload_from_path` and `read_payload`, read-only as always. The 64 MB MIDI limit and the readers' errors apply unchanged.

## Code

- **New `core/mirror.py`** (pure, no Qt):
  - `carry_over(ws, result) -> dict`: a workspace snapshot for the new import;
  - it matches tracks with `placement._assign` (exposed under a public name), reuses ids, and carries colour, export channel, controller override and mute/solo;
  - it keeps ranges and drops ids that have gone;
  - it returns counts for the status message.
- **New `ui/mirror.py`:**
  - `MirrorWatcher(path, clock, executor)`: `poll()`, settle, generation, retry, missing-file handling, and signals `imported(result)` and `failed(message)`;
  - tests inject the clock and a synchronous executor and call `poll()` directly, the pattern `test_session.py` uses for the lifecycle.
- **`ui/controller.py`:**
  - `mirroring`;
  - `enter_mirror(result)`: clear, import at bar 1, no checkpoint;
  - `apply_mirror(result)`: `carry_over`, then `ws.restore`, the refresh signals, no checkpoint;
  - `leave_mirror()`: clear the undo and redo stacks;
  - the guard on the editing methods and `checkpoint()`.
- **`ui/main_window.py`:**
  - the Open & Mirror and Unmirror actions and the toolbar button;
  - the banner and frame widgets;
  - the window title;
  - enabling and disabling actions;
  - menus built for mirror mode;
  - drop and `import_paths` refusal;
  - deferral of a finished read during gestures.
- **`ui/timeline.py`:** `_clip_action` returns None while mirroring, so no clip gesture or cursor starts; `keyPressEvent` ignores M.
- **`ui/track_panel.py`:** header widgets read-only or disabled while mirroring; the grip is inert; the tinted backgrounds.
- **`ui/theme.py`:** `MIRROR`, `MIRROR_TEXT`, the tinted backgrounds, and `apply(app, mirror=False)`.
- **`ui/session.py`:** no change. A test proves a mirrored session restores as a normal one.

## Tests (headless)

A new `tests/test_mirror_mode.py`, using `from test_ui_assembly import app, win` and the `helpers` builders. Never a hand-built `MainWindow`. Files live in `tmp_path`; the watcher runs with a fake clock and a synchronous executor.

- **Watcher, with simulated saves:**
  - an in-place rewrite;
  - temp file then `os.replace`;
  - a partial write, then the complete file: no read before it settles, then one read;
  - truncated or garbage content, then good: the last import stays, the notice appears, and the good save is picked up;
  - deleted, then restored: the waiting notice, then a re-import;
  - two saves inside the settle time: one read;
  - a change during a read: the stale result is discarded;
  - a real Cubase and Reason fixture from `samples/` copied into `tmp_path` and replaced.
- **Carry-over** (`core/mirror.py`):
  - a matched track keeps its id, colour, export channel, override and mute/solo (per design question 2);
  - a locked range keeps its exclusions for matched tracks;
  - a new track is included per the existing rules;
  - a gone track leaves the ranges cleanly;
  - repeated names pair in order;
  - a renamed track arrives new;
  - the tempo map is replaced;
  - the ranges, selection, zoom and scroll are unchanged.
- **No undo:** after entering and after any number of re-imports and range or mute edits, `can_undo()` and `can_redo()` are False.
- **Read-only:**
  - every controller method in the table returns without changing the workspace snapshot;
  - every listed action is disabled or absent, including the clip and track menus, the Tempo Map menus and the header widgets;
  - an Alt-drag, an Option-drag, a Cmd-click and M do nothing;
  - a drop and `import_paths` are refused with the notice.
- **Allowed while mirroring:**
  - creating, editing and deleting ranges, toggles and locks;
  - mute and solo, and the Sources dialog's solo;
  - Save MIDI bytes and the drag-out payload equal those of the same workspace not mirrored.
- **Unmirror:**
  - the workspace equals the last import;
  - undo and redo are empty;
  - every edit works again;
  - the cue is gone;
  - later file changes are ignored.
- **Cue:** the title names the file; the banner and Unmirror are visible; the frame overlay covers the central area and passes mouse events through; the banner text's contrast is at least 4.5:1.
- **Session:**
  - `capture` while mirroring, then `apply_session`: a normal workspace, not mirroring, with the same tracks and ranges;
  - the recovery path (a crash) restores a normal workspace.
- **Entering over a non-empty workspace** asks first; Cancel changes nothing.
- After adding the UI tests, run the full suite (`.venv/bin/python -m pytest -q`) **four times**.

## Docs and checklist (the build makes these)

- **README:**
  - a new section, "Mirror a project while you work", in the How to use it steps: the command, what's allowed, Unmirror, that only saved changes count, and that relaunch restores a normal workspace;
  - the toolbar list in "The window" (Mirror…);
  - a quick-reference row;
  - the session paragraph in "Returning to your workspace";
  - a Known limitations line: only saved changes are seen, and a track renamed in the DAW arrives as a new track.
- **TEST_CHECKLIST:** a new section **8s. Mirror mode (`feature/mirror-mode`)**, before section 9 (from the manual test below).
- **DEVELOPMENT.md:**
  - the project layout gains `core/mirror.py` and `ui/mirror.py`;
  - a short "Mirror mode" note under the conventions: polling, not `QFileSystemWatcher`, and why; the settle numbers and the step-0 evidence behind them; the controller's mirroring guard as the one place that refuses edits.
- **This plan:** the step-0 results go in a new "Save evidence" section before the build starts.
- **ROADMAP:** remove the entry when built, and set this plan's status to built.

## Manual test (owner, with Cubase and Reason)

- With something in the workspace, choose File ▸ Open & Mirror… and pick a Cubase project. A confirmation appears.
- After accepting:
  - the frame, the tint, the banner and the title make the mode obvious;
  - the tracks are at bar 1.
- Make two ranges, lock one with a track left out, and mute a track.
- In Cubase, move a part and save. Within about two seconds:
  - the timeline updates;
  - the status bar names the time;
  - the ranges, the lock and the mute are still there.
- Rename a track in Cubase and save: it arrives as a new track (the expected limitation).
- Add a track in Cubase and save: it appears and is included in the unlocked range.
- Drag out a range into Cubase, and Save MIDI. Both work while mirroring.
- Try to edit:
  - an Alt-drag on a clip, a split, the ✕, a rename, a file drop, Open and New are all unavailable;
  - Undo and Redo are greyed.
- Save a large project and watch: no half-read state appears.
- Rename the project file in Finder, then rename it back: "not found; waiting", then a re-import.
- Unmirror: the workspace stays, editing works, Undo is empty, and further saves in Cubase change nothing here.
- Repeat the save and range checks with a Reason song.
- Quit while mirroring and relaunch: a normal workspace, not mirroring.

## Decisions settled with the owner (2026-11-22)

All the recommendations were agreed:

1. **Entering over a non-empty workspace:** ask first, then replace it.
2. **Mute and solo across saves:** a track muted or soloed in the app keeps that setting until unmirror; other tracks follow what the DAW saved.
3. **Renamed tracks in the DAW:** arrive as new tracks for now. Reordering is harmless.
4. **File moved or deleted:** keep the last import and wait at the same path, showing "not found; waiting". Moves aren't followed.
5. **Unmirror:** no confirmation.
6. **Visual cue:** option (a), a cyan frame, a cyan banner with an Unmirror button, the mode named in the title bar, and tinted chrome. The lanes are left untouched.
7. **Settle time:** provisionally 1.0 s after the last change, polling every 250 ms, to be adjusted once step 0 shows how long each DAW's save takes.

**Still blocking the build:** step 0, the owner-run save logging in Cubase and Reason.
