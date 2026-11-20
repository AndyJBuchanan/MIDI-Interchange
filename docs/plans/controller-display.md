# Plan: show controller data on a track

Status: **first design built (b626d99, 2026-11-20); change to unequal row heights agreed 2026-11-20 and being built.** Branch: `feature/controller-display` from `release/0.5.0`.

Draw a clip's controller data (a CC, pitch bend or channel aftertouch) as a line, either in a strip under the notes or over them. You pick one controller for the whole timeline, and a track can override it from a small box in its header.

**The change to build next** (owner, 2026-11-20). A studio test showed that at lane heights of about 52 px and below, the old overlay fallback made the Lane/Overlay button look dead.

- In Lane mode, a track that shows a controller now gets an **extra strip under its normal lane**, so its row is taller. Rows can therefore differ in height.
- Before this change, the strip was carved out of the note area, and short lanes fell back to Overlay. Both are gone: notes keep the same layout in both modes.
- Everything else built in b626d99 stays as it is.

## Why

Controller data travels with the clips but can't be seen today. Before moving MIDI on, it helps to see what came in: an imported mod-wheel curve, a pitch bend that never returns to centre, a sustain pedal left down, a volume reset at a clip start.

**Display only.** Controller data stays part of the clip. Import, export, clips, trims and Simplify are all unchanged, and export output is byte-identical whatever is shown.

## Behaviour

### The global picker and the two style buttons (toolbar and View menu)

- A **Controller** list on the toolbar, after the **Markers** button and before the separator ahead of Clear All Ranges. It's mirrored in the **View** menu as a Controller submenu, followed by **Overlay on Notes** and **Joined Lines** ticks. (Agreed.)
- Items: **Off** (the default), then every controller type found in the workspace, in this order:
  1. **Pitch Bend**
  2. **Aftertouch** (channel aftertouch)
  3. CCs in number order, as number and standard name: "1 Mod Wheel", "7 Volume", "10 Pan", "11 Expression", "64 Sustain". A CC with no standard name shows as "CC 20".
- The list is the union over all tracks and clips, muted ones included. It counts what each clip shows. The list refreshes when tracks change: import, delete, trim, undo and redo.
  - A controller whose data sits only *before* a clip's trimmed start is still listed and drawn, because export carries its last value into the cut and the line starts from that value (agreed 2026-11-20).
  - A controller that exists only *after* a trimmed end isn't listed.
- **Not listed:**
  - **Controllers that aren't curves**, the same set Simplify never touches (`SEQUENCE_CCS` in `core/simplify.py`), so the two features agree: bank select (0, 32), data entry and increment/decrement (6, 38, 96, 97), and RPN/NRPN (98–101).
  - **Channel mode messages, CC 120–127** (`MODE_CCS`). They're commands, not values.
  - **Polyphonic key pressure.** It has one value per note, so a single line can't show it.
- Only **one controller** shows at a time. Several at once is a later enhancement and isn't designed here.
- Beside the list, two checkable icon buttons. Each paints a small icon, applies to every track, and has a tooltip naming its current setting and what a click does. Both are disabled while nothing is shown: the picker is Off and no track overrides it with a controller.
  - **Mode button: Lane** (the default) **or Overlay.**
    - Lane icon: a block of notes with a strip of line under it.
    - Overlay icon: the line running through the notes.
    - Tooltip, for example: "Controller in a lane under the notes. Click to draw it over the notes."
    - Toggling it changes the height of every track that shows a controller, which makes the effect obvious at any lane height.
  - **Style button: Steps** (the default) **or Joined lines.**
    - Steps icon: a staircase.
    - Joined icon: a slanted line through points.
    - Tooltip, for example: "Controller drawn as steps. Click to join the points with lines."

### The track's controller box (track header)

- Each track header has a small **boxed button directly under its delete (✕) button**, at the right end of the info line. It shows the controller this track displays, in short form: **CC1**, **CC11**, **PB** (pitch bend), **AT** (aftertouch). The info line gives up the room the box takes.
- **Normal or red:**
  - When the track follows the picker, the box is drawn normally: an outlined box with dim text, in the M button's unchecked look.
  - When the track is overridden, the box is drawn **red** (`theme.SOLO`), the same way a checked Solo button is.
  - An override to None shows a red box with "–".
- A track that follows the picker but has none of its controller shows the picker's label dimmed. When it follows an Off picker, the box is empty but still clickable.
- **Clicking the box** pops up the override choice:
  - **Follow view**, naming the current choice: "Follow view (7 Volume)", or "Follow view (Off)"
  - **None**
  - a separator, then **the controllers this track has**, in the picker's order and with its labels.

  The current choice is ticked. Choosing an entry applies it and closes the popup; Esc or clicking outside changes nothing.
- The tooltip gives the full state, for example "Controller: 11 Expression (this track; click to change)" or "Controller: follows view (1 Mod Wheel)".
- The colour-box menu is **unchanged**. It stays for colour and the export channel.
- **With the change:**
  - a header grows with its row;
  - its contents stay anchored to the top (the layout already ends in a stretch), so the box stays under the ✕ and the extra height below is blank header background;
  - the box hides where the **row** is shorter than 45 px, as built (`self.height()` is the row height). See design question 2.

### What is drawn

- **Values:** CCs and aftertouch scale from 0 at the bottom to 127 at the top. Pitch bend has its centre (8192, mido's 0) in the middle, with a faint centre line so a bend left off-centre is visible.
- **Steps** (default): each value holds until the next event. This matches how Reason imports controller data (owner, 2026-11-18), and how Cubase imports it until switched to ramp mode.
- **Joined lines:** straight lines between event points, as a DAW in ramp mode draws them. This is useful to preview Simplified data.
- **Time:** event times are already quarter notes from the clip's start, and the timeline is linear in quarter notes. So a point's x is `(event time + clip offset) × zoom`, with no tempo mapping. The source's display offset is recorded only, not applied, so it doesn't move anything.
- **Clip edges** match what export writes, in both styles:
  - From an untrimmed clip's start, nothing is drawn until the first event, since no earlier value is known.
  - From a trimmed start, the line begins at the value carried in from before the trim. This is the same point export writes at that edge (state-carry in `export_smf._extract_clips`). In Joined style it runs from there to the next point.
  - After the last point inside the clip, the line holds flat to the clip's visible end, in both styles. Export drops points after a trimmed end, so nothing slopes toward a point beyond it.
  - Nothing is drawn outside the clip's horizontal extent, as for notes.
- **Loops:** none to handle. Reason loops are written out at import, and duplicated clips share their events, so each copy draws the same line.
- **No data, no strip:** a track or clip without the chosen controller shows no line. A track with none of it gets no strip and keeps its normal height (see Row heights).
- **Mute and ranges:** the line greys with its clip exactly as the notes do (disabled regions, muted clips).
- **Colour:**
  - Lane: a slightly darker strip, with the line in the lightened track colour and a faint fill under it.
  - Overlay: the line only, light, with a thin dark edge so it reads over the notes.
- **Interaction is unchanged.** The strip and the line are drawn only. Clicks, drags, trims, splits and range creation behave exactly as they do now; with the change, the strip counts as part of its track and clip.

### Several channels on one track (existing rules, followed)

A track's channels are `Track.channels`, recomputed from what its clips show (`visible_msgs`). The header lists them as "ch 1,4", and a multi-channel track keeps them as they are. A set export channel moves every channel message onto that one channel, and Simplify then thins the merged stream as one, keyed on the final output channel.

The display follows the same rule:
- **Original channels:** one line per channel in `Track.channels`, drawn alike.
- **An export channel set:** the channels are drawn merged into one line, which is what the receiving DAW gets.

### Row heights (the change, owner 2026-11-20)

- **Normal lane height:** the lane height setting (Alt+wheel, Taller/Shorter Lanes, 28–220 px, default 68) is the normal lane height, as today. It's saved with the session as now, and means the same thing.
- **Who gets a strip:** in **Lane** mode, a track that **shows a controller and has data for it** gets an extra strip under its normal lane. The controller may come from the picker or from the track's own override, including an override while the picker is Off.
- **Strip size:** about **30% of the normal lane height, at least 10 px** (`max(10, round(0.3 × lane height))`).
- **Rows that stay at the normal height:**
  - every row in **Overlay** mode;
  - tracks with no data for the shown controller;
  - tracks overridden to None;
  - every track while the picker is Off and no track overrides it with a controller.
- **Where the strip sits:**
  - The strip belongs to the track and sits inside its row, under the normal lane.
  - The clip's rounded box extends down through the strip, with a faint divider between notes and strip. So the strip is part of the clip for hit-testing: Alt-drag, split and the clip menu work there too.
  - The lane background, the excluded-range hatching, the overlap marks and the row separator cover the whole row.
- **The note area is never reduced by a strip.** It is laid out from the normal lane height exactly as with display off, and is identical in Lane and Overlay. Lyric and marker ticks stay at the bottom of the normal lane, above the strip.
- **The overlay fallback is removed**, and so is the mode tooltip's "lanes too short" sentence.
- **During a gesture**, heights don't change. A clip drag, a range drag, a track reorder or an external drop can move data onto or off a track, which would change its height under the pointer. So each track's height is frozen by track id when the gesture starts, and recalculated when it ends. The marker row already follows the same rule: it never changes during a drag, and `end_drag` applies it. A track created during the gesture, such as a drag below the last lane, uses the normal height until then.
- **Scroll stays put:** when heights change through the picker, the mode, an override, undo or redo, or an edit that gives or takes a track's data, the track at the top of the view stays at the top. The view keeps the same pixel offset into that track, clamped to its new height.
  - A lane height change keeps today's behaviour (the scroll value is kept).
  - On session restore, the controller view is applied before the scroll position, so the restored offset matches the restored heights.

### Undo and saving

- **The per-track override is undoable**, like the export channel:
  - it's stored on the track, so it's part of every undo snapshot;
  - each change is one undo step;
  - choosing the current value makes no step.
  - A new track, including one made by moving or copying a clip, starts on Follow view. A merged-away track's override goes with it.
- **The picker, the mode and the style are view state**, like zoom, lane height and Show Markers. They make no undo step, and undo or redo doesn't change them. Row heights are derived from these, the override and the data, and are never stored.
- **Everything is saved with the session:** the picker, the mode, the style and the overrides. Sessions are a short-term convenience, not project files, so old or mismatched ones only need to load safely:
  - A **schema-5 session** loads with defaults: Off, Lane, Steps, every track on Follow view.
  - An **unsupported or damaged session** never crashes the app: `decode` raises `SessionError`, and `SessionLifecycle.start` catches it and calls `_recover`, which keeps the rejected file until quit, starts empty with default settings and shows one notice.
  - The change adds nothing to the session.
- A picker choice that no longer exists is kept, not cleared (agreed). For example, a deleted track held the only Volume data:
  - the picker keeps "7 Volume", greyed and marked "(none in workspace)", and draws nothing;
  - it shows again as soon as an import, undo or redo brings the data back.

  An override whose controller the track has lost behaves the same: its box stays red, the track draws nothing and gets no strip.

## Code

### As built in b626d99 (unchanged by this change)

- **New `core/controllers.py`** (pure): keys, labels and short labels, the ordering and exclusions, `clip_controllers`, the per-channel or merged lines.
- **`core/document.py`:** `Track.controller`.
- **`core/session.py`:** schema 6, with the schema-5 default.
- **`ui/controller.py`:**
  - `set_track_controller` (undoable);
  - the view-state setters emitting `controllerViewChanged`;
  - `shown_controller`, `track_controllers` and `workspace_controllers`.
- **`ui/timeline.py`:** `controller_polyline` (bisect culling, min–max decimation), `controller_lines_for` and its cache, `_paint_controller`.
- **`ui/track_panel.py`:** `ControllerBox` and its popup.
- **`ui/main_window.py`:** the picker, the two buttons and the View menu.
- **`ui/session.py`:** `controller_view`.

### The change: per-track row heights

**One source of row geometry**, on `Timeline`:
- `row_h(i)`: the track's row height, `lane_h` plus its strip;
- `row_y(i)`: the content y of the row's top, before scrolling, from cached prefix sums;
- `content_rows_h()`: the total of all rows.

`lane_top(i)` becomes `header_h() + row_y(i) - scroll`. `lane_at(y)` uses `bisect` on the prefix sums, so it stays O(log n).

- **The cache:**
  - It's built in one pass over the tracks: whether each one has a strip, from `shown_controller` and `track_controllers`, whose per-clip key sets are already cached.
  - It's invalidated on `tracksChanged`, `controllerViewChanged` and `set_lane_height`. While a gesture is active, the frozen per-id heights are used instead.
  - Whenever the offsets change, a new `rowsChanged` signal is emitted. The track panel lays itself out from that signal.
- **Painting:**
  - Painting finds the first visible row with `bisect` and stops past the bottom of the view, so the cost follows what's visible, not the track count. `_paint_lanes_bg` today paints every track; it is limited to the visible rows too.
  - No paint loops over all tracks to compute positions.

**Every place that assumes uniform rows**, and how each one changes:

| Where | Today | Change |
|---|---|---|
| `timeline.py` `lane_top`, `lane_at` | `i * lane_h`, `// lane_h` | prefix sums and `bisect` |
| `timeline.py` `_update_scrollbars` | `len(tracks) * lane_h` for the content height | `content_rows_h()`. The single step stays `lane_h // 3` |
| `timeline.py` `paintEvent` | culls with `lane_h`; the split preview line uses `lane_h` | visible-row range; `row_h(i)` |
| `timeline.py` `_paint_lanes_bg` | paints every track, with `lane_h` | visible rows, `row_h(i)` |
| `timeline.py` `_paint_track_regions` | regions of height `lane_h` | `row_h(i)` |
| `timeline.py` `_paint_track` | clip box `lane_h - 5`; overlap fills `lane_h - 5`; texts at `top + lane_h` | clip box and overlaps use `row_h`; note area and texts keep `lane_h`; strip below |
| `timeline.py` `track_layout`, `TrackLayout` | the strip is carved from the note area; `fallback`; `STRIP_SHARE`, `STRIP_GAP`, `STRIP_MIN_AREA` | the note area is unchanged; the strip starts at `top + lane_h`; `fallback` and those three constants are removed; `STRIP_SHARE = 0.30` of `lane_h`, `STRIP_MIN = 10` |
| `timeline.py` `_paint_range_toggles` | culls with `lane_h`; excluded hatching `lane_h - 1` | visible rows; `row_h(i) - 1` |
| `timeline.py` `toggle_rect` | `lane_h < TOGGLE_PX + 6` check; at `lane_top + 4` | unchanged: uses the normal height and stays at the row's top |
| `timeline.py` `_paint_drop_indicator` | the target row is filled with `lane_h`; the new-track box `lane_h - 5` | target row uses `row_h(lane)`; the new-track box stays `lane_h` (a new track is normal height) |
| `timeline.py` `_clip_edge_hit`, `_lane_hit`, `_hit`, `_drag_clip` (below-last-lane test via `lane_top(len)`) | go through `lane_at` and `lane_top` | correct once those change; no other edit |
| `timeline.py` `begin_drag`, `end_drag`, `gesture_active` | — | freeze heights by track id at the start; recalculate at the end |
| `track_panel.py` `TrackPanel._layout` | header at `i * lane_h`, height `lane_h` | `row_y(i)`, `row_h(i)` from the timeline; relays out on `rowsChanged` |
| `track_panel.py` `TrackPanel.paintEvent` | separators and the drop line at `i * lane_h` | `row_y`, `row_h` |
| `track_panel.py` `_index_at_global` | `round(y / lane_h)` | the nearest row boundary, by `bisect` on the prefix sums |
| `track_panel.py` `_grip_move` indicator | `drop_index * lane_h` | `row_y(drop_index)` (or the total for the end) |
| `track_panel.py` `BOX_MIN_LANE` in `TrackHeader.refresh` | compared with `self.height()` | unchanged in code, but `self.height()` is now the row height (design question 2) |
| `main_window.py` `drop_placement` | `timeline.lane_at` | correct once `lane_at` changes |
| `main_window.py` mode tooltip | adds "Lanes too short for a strip…" when `track_layout(...).fallback` | sentence removed |
| `ui/session.py` `apply_session` | sets the vertical scroll before the controller view | apply the controller view first; `lane_height` is unchanged in meaning |
| `main_window.py` Taller/Shorter Lanes, Alt+wheel, `laneHeightChanged` | change `lane_h` | unchanged; strips rescale through the cache. `laneHeightChanged` still marks the session dirty |
| Export | — | nothing: geometry never reaches export |

**Scroll anchoring:** before the offsets are recalculated (outside a gesture, and not for a lane height change), record the top visible track's id and the view's offset into it. Afterwards, set the scroll to that track's new `row_y` plus the offset, clamped to its height.

## Tests (headless)

`tests/test_controller_display.py`, using `from test_ui_assembly import app, win` and the `helpers` builders, as now. Never a hand-built `MainWindow`.

**The existing tests in other files** compute positions as `header_h() + i * lane_h`. They stay valid, because with display Off (the default) every row is the normal height. A new test asserts that invariant, so a later change can't break them silently.

**Replace:** `test_short_lanes_fall_back_to_overlay_and_taller_lanes_bring_the_strip_back`, `test_mode_tooltip_says_when_short_lanes_fall_back_to_overlay` and `test_lane_mode_gives_a_strip_only_to_tracks_that_have_the_controller` (now about row height).

**New:**
- **Row heights:**
  - in Lane mode, a track with data is `lane_h + max(10, round(0.3 × lane_h))`;
  - tracks without data, overridden to None, or with the picker Off and no override are `lane_h`;
  - in Overlay mode, every row is `lane_h`;
  - an override to a controller with data while the picker is Off gets a strip;
  - checked at 28, 52, 68 and 220 px, so there's no fallback at any height.
- **Notes unchanged:** `track_layout`'s note area is identical with display off, in Lane and in Overlay.
- **Geometry agrees:** for unequal rows, `lane_at(lane_top(i))` and `lane_at(lane_top(i) + row_h(i) - 1)` are both `i`, and the vertical scroll range equals header + rows + 24 − viewport.
- **Headers follow rows:** each header's geometry matches the timeline's row (y and height) after:
  - a mode toggle, a pick and an override;
  - undo and redo;
  - a lane height change, and a scroll.
- **Scroll anchor:** with track k at the top, a mode toggle, a pick and an undo of an override each leave track k at the top.
- **Gestures across unequal rows:**
  - an Alt-drag of a clip onto a lower track below a tall row lands on the right track;
  - heights don't change mid-drag, even when the clip brings data to the destination, and are recalculated on release;
  - `drop_placement` and the drop indicator target the right track on a tall row;
  - a grip reorder dropped below a tall row gives the right index.
- **Hit-testing in the strip:** a click in the strip hits the clip, and a range toggle in a lower row is hit at its new position.
- **Culling:** with 200 tracks and one tall row, a paint calls `_paint_track_regions` only for the visible rows.
- **The box:** it stays under the ✕ and anchored top in a tall row; it is visible on a tall row when the normal lane is under 45 px (per design question 2).
- After adding the tests, run the full suite (`.venv/bin/python -m pytest -q`) **four times**.

## Docs and checklist

Not edited by this plan. These sentences become wrong or incomplete with the change:

- **`docs/TEST_CHECKLIST.md` 8r:** "Make the lanes as short as they go: the strip gives way to the overlay and the box under the ✕ hides. Make them taller and both return."
  - This is wrong now: there's no fallback.
  - Replace it with: tracks showing a controller in Lane mode are taller than the rest, at every lane height; Overlay returns them to the normal height; note where the box hides.
- **`docs/TEST_CHECKLIST.md` 8r:** "The first icon button switches every track between a lane under the notes and an overlay on them."
  - This is incomplete. Add: tracks that show a controller grow when the lane appears, and the track at the top of the view stays put.
- **`README.md`, "See controller data":** "The first icon button draws the curve in a **lane** under the notes, or **over** the notes."
  - This is still true, but should add that the lane makes those tracks taller, and only those that have the controller.
- **`README.md`, "The window", item 4** ("A small box under the ✕ …"): still true. No change.

The plan's own **As built** section is marked below where this change supersedes it.

## Manual test

- Import a Reason song with mod-wheel and pitch-bend curves, and a Cubase project with CC data. The picker lists exactly what they hold: Pitch Bend and Aftertouch first, then the CCs, with no bank select or RPN entries.
- Pick each controller in turn. In Lane mode, only the tracks that have it grow a strip under their lane. The notes don't move or squash. Pitch bend shows its centre line.
- Click the mode button at the default height, then at the shortest lanes:
  - the tracks with the controller visibly grow and shrink every time;
  - the track at the top of the view stays at the top.
- Override one track to None: it returns to the normal height. Set the picker to Off and override one track to its own controller: only that track grows.
- Headers stay level with their rows throughout, and the box stays under the ✕.
- Alt-drag a clip with controller data onto a track without any:
  - rows don't jump during the drag;
  - the destination grows on release;
  - undo puts it back.
- Drag a track by its grip past a tall row: it lands where the indicator showed. Drop a MIDI file onto a tall row: it goes to that track.
- Click and Alt-drag inside a strip: it acts on the clip.
- Zoom fully out on a long, dense song with many tracks, and scroll: it stays responsive.
- Quit and reopen in Lane mode: the same rows are tall and the view opens where it was.
- Export with display on and off: the files are the same.

## Decisions settled with the owner

1. **View state** (2026-11-19). The picker, the mode and the style make no undo step. Only the per-track override is undoable.
2. **The box when the picker is Off and the track follows it** (2026-11-19). An empty outlined box, still clickable.
3. **The box at short lane heights** (2026-11-19). Hidden below about 45 px. With the change, this needs restating against row height: see design question 2.
4. **Unequal rows, option B** (2026-11-20). Only tracks that show a controller and have data for it get the extra strip, in Lane mode. Overlay adds nothing. The note area is never compressed, and the overlay fallback is removed.

## As built (2026-11-20, b626d99)

- **Labels:** toolbar label " Controller "; entries "Off", "Pitch Bend", "Aftertouch", "1 Mod Wheel", "CC 20" and so on. A kept choice with no data shows as "7 Volume (none in workspace)", greyed. The View menu has a Controller submenu, then "Overlay on Notes" and "Joined Lines" ticks.
- **Tooltips:**
  - Mode: "Controller in a lane under the notes. Click to draw it over the notes." / "Controller drawn over the notes. Click to draw it in a lane under the notes."
    - *Superseded by the row-height change:* "When lanes are too short for a strip it adds that they draw over the notes."
  - Style: "Controller drawn as steps. Click to join the points with lines." / "Controller joined with lines. Click to draw it as steps."
  - With nothing shown, both add "(Nothing shown: pick a controller first.)"
- **Controller box:** 34 by 16 px, under the ✕. Text is CC1, PB, AT, "–" for None, and empty when the track follows an Off picker. Tooltips: "Controller: follows view (1 Mod Wheel)", "Controller: 11 Expression (this track; click to change)", "Controller: none (this track; click to change)". Popup: "Follow view (7 Volume)" or "Follow view (Off)", "None", a separator, then the track's own controllers.
  - Hidden when the lane is under 45 px. *With the change, this compares the row height; see design question 2.*
- **Strip:** *superseded by the row-height change:* "35% of the note area, at least 10 px, with a 2 px gap; overlay fallback when the note area is under 30 px." Now: an extra 30% of the lane height, at least 10 px, under the lane, and no fallback.
- **Painting test:** the decimated point count is held to at most twice the view width plus 4 (the closing hold and the one-pixel columns at each view edge).
- **Muted clips** still count towards the list and the lines (the lists use an un-muted copy of the clip, since `visible_msgs` returns nothing for a muted trimmed clip).
- **Channel lines** are built per channel that has the controller in the clip, equivalent to one line per channel in `Track.channels` but also correct for muted trimmed clips.

## Risk assessment

**Moderate and contained.**
- Row geometry already goes through two functions, `lane_top` and `lane_at`. Outside them there are about a dozen direct uses of `lane_h` in `timeline.py`, and five in `track_panel.py` (listed above). Hit-testing, clip drags and drop placement go through those two functions, so they follow without their own edits.
- **The real risks:**
  - the track panel and the timeline drifting apart (one source of geometry and the `rowsChanged` signal guard against it);
  - rows reflowing under the pointer during a gesture (handled by freezing heights);
  - scroll jumps on a toggle (handled by anchoring).
- Existing tests assume uniform rows, but that remains true while display is Off, and a test pins it.
- There's no model, export or session-format change.

## Decisions on the row-height change (2026-11-20)

1. **Heights during gestures:** frozen while a drag is in progress, applied on release. Agreed.
2. **The box threshold:** keep comparing the row height. Agreed.
3. **Scroll anchoring:** only for height changes caused by the controller display. Taller/Shorter Lanes and ⌥-wheel stay as they are. Agreed.

No design questions remain open.
