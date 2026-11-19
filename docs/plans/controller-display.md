# Plan: show controller data on a track

Status: **plan for review (2026-11-19); all design questions settled, awaiting the owner's go-ahead to build.** Branch, when built: `feature/controller-display` from `release/0.5.0`.

Draw a clip's controller data (a CC, pitch bend or channel aftertouch) as a line, either in a strip under the notes or over them. You pick one controller for the whole timeline, and a track can override it from a small box in its header.

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
- The list is the union over all tracks and clips, muted ones included. It counts what each clip shows, so a controller that sits only in a trimmed-away part isn't listed. The list refreshes when tracks change: import, delete, trim, undo and redo.
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
  - **Style button: Steps** (the default) **or Joined lines.**
    - Steps icon: a staircase.
    - Joined icon: a slanted line through points.
    - Tooltip, for example: "Controller drawn as steps. Click to join the points with lines."
- Each click changes every visible lane at once, so the effect is obvious.

### The track's controller box (track header)

- Each track header gets a small **boxed button directly under its delete (✕) button**, at the right end of the info line. It shows the controller this track displays, in short form: **CC1**, **CC11**, **PB** (pitch bend), **AT** (aftertouch). The info line gives up the room the box takes. Row height is unchanged.
- **Normal or red:**
  - When the track follows the picker, the box is drawn normally: an outlined box with dim text, in the M button's unchecked look.
  - When the track is overridden, the box is drawn **red** (`theme.SOLO`), the same way a checked Solo button is.
  - An override to None shows a red box with "–".
- A track that follows the picker but has none of its controller shows the picker's label dimmed, so you can see what it follows and that it shows nothing.
- **Clicking the box** pops up the override choice:
  - **Follow view**, naming the current choice: "Follow view (7 Volume)", or "Follow view (Off)"
  - **None**
  - a separator, then **the controllers this track has**, in the picker's order and with its labels.

  The current choice is ticked. Choosing an entry applies it and closes the popup; Esc or clicking outside changes nothing.
- The tooltip gives the full state, for example "Controller: 11 Expression (this track; click to change)" or "Controller: follows view (1 Mod Wheel)".
- The colour-box menu is **unchanged**. It stays for colour and the export channel.

### What is drawn

- **Values:** CCs and aftertouch scale from 0 at the bottom to 127 at the top. Pitch bend has its centre (8192, mido's 0) in the middle, with a faint centre line so a bend left off-centre is visible.
- **Steps** (default): each value holds until the next event. This matches how Reason imports controller data (owner, 2026-11-18), and how Cubase imports it until switched to ramp mode.
- **Joined lines:** straight lines between event points, as a DAW in ramp mode draws them. This is useful to preview Simplified data.
- **Time:** event times are already quarter notes from the clip's start, and the timeline is linear in quarter notes. So a point's x is `(event time + clip offset) × zoom`, with no tempo mapping. The source's display offset is recorded only, not applied, so it doesn't move anything.
- **Clip edges** match what export writes, in both styles:
  - From an untrimmed clip's start, nothing is drawn until the first event, since no earlier value is known.
  - From a trimmed start, the line begins at the value carried in from before the trim. This is the same point export writes at that edge (state-carry in `export_smf._extract_clips`). In Joined style it runs from there to the next point.
  - After the last point inside the clip, the line holds flat to the clip's visible end, in both styles. Export drops points after a trimmed end, so nothing slopes toward a point beyond it.
  - Nothing is drawn outside the clip's rectangle, as for notes.
- **Loops:** none to handle. Reason loops are written out at import, and duplicated clips share their events, so each copy draws the same line.
- **No data, nothing drawn:** a track or clip without the chosen controller shows nothing. In Lane mode a track with none of it keeps its full note area.
- **Mute and ranges:** the line greys with its clip exactly as the notes do (disabled regions, muted clips).
- **Colour:**
  - Lane: a slightly darker strip inside the clip, with the line in the lightened track colour and a faint fill under it.
  - Overlay: the line only, light, with a thin dark edge so it reads over the notes.
- **Interaction is unchanged.** The strip and the line are drawn only. Clicks, drags, trims, splits and range creation behave exactly as they do now.

### Several channels on one track (existing rules, followed)

A track's channels are `Track.channels`, recomputed from what its clips show (`visible_msgs`). The header lists them as "ch 1,4", and a multi-channel track keeps them as they are. A set export channel moves every channel message onto that one channel, and Simplify then thins the merged stream as one, keyed on the final output channel.

The display follows the same rule:
- **Original channels:** one line per channel in `Track.channels`, drawn alike.
- **An export channel set:** the channels are drawn merged into one line, which is what the receiving DAW gets.

### Lane height (agreed)

All rows share one lane height (28–220 px, default 68), so a strip can't make one row taller. The strip is carved out of the note area of tracks that show a controller:

- The strip is 35% of the note area, at least 10 px. The notes compress into the rest (`note_rows` already compresses a wide pitch range).
- If the note area is under 30 px (the shortest lanes), the track draws as Overlay instead, and the mode button's tooltip says so. Taller Lanes or Alt+wheel brings the strip back.

### Undo and saving

- **The per-track override is undoable**, like the export channel:
  - it's stored on the track, so it's part of every undo snapshot;
  - each change is one undo step;
  - choosing the current value makes no step.
  - A new track, including one made by moving or copying a clip, starts on Follow view. A merged-away track's override goes with it.
- **The picker, the mode and the style are view state**, like zoom, lane height and Show Markers. They make no undo step, and undo or redo doesn't change them.
- **Everything is saved with the session:** the picker, the mode, the style and the overrides. Sessions are a short-term convenience, not project files, so old or mismatched ones only need to load safely:
  - A **schema-5 session** (0.4.0 and the 0.5.0 builds so far) loads with defaults: Off, Lane, Steps, every track on Follow view.
  - An **unsupported or damaged session** never crashes the app. That's already how it works: `decode` raises `SessionError`, and `SessionLifecycle.start` catches every exception and calls `_recover`, which keeps the rejected file until quit, starts with an empty workspace and default settings, and shows one notice. The same path covers an older app given a session from this build.
- A picker choice that no longer exists is kept, not cleared (agreed). For example, a deleted track held the only Volume data:
  - the picker keeps "7 Volume", greyed and marked "(none in workspace)", and draws nothing;
  - it shows again as soon as an import, undo or redo brings the data back.

  An override whose controller the track has lost behaves the same: its box stays red and the track draws nothing.

## Code

- **New `core/controllers.py`** (pure, no Qt):
  - controller keys as short strings (`"pb"`, `"at"`, `"cc7"`), their long labels from a standard-name table, and short box labels ("CC7", "PB", "AT");
  - the ordering, with exclusions reusing `SEQUENCE_CCS` and `MODE_CCS`;
  - `clip_controllers(clip)`: the keys a clip shows, from `visible_msgs`, so trims count as export cuts them;
  - `controller_points(clip, key, channel)`: sorted times and values scaled to 0–1, plus the value carried into a trimmed start. It takes a channel, or all channels merged for a set export channel.
- **`core/document.py`:** `Track.controller: str | None = None` (None follows the view, `"none"` shows nothing, otherwise a key). `Track.copy` already carries it into snapshots.
- **`core/session.py`:**
  - add the field to `RECORDS[Track]` and bump `SCHEMA_VERSION` to 6, the existing mechanism for a changed track record (the field-coverage test requires it);
  - schema 5 stays readable through the two-line default `source_transpose` used in schema 5: `if cls is Track and version < 6`, the field defaults to None;
  - validate the value: None, `"none"` or a well-formed key;
  - no other migration.
- **`ui/controller.py`:**
  - `set_track_controller(track_id, value)`, with `checkpoint()` and `tracksChanged`, like `set_export_channel`;
  - view state: the global key, overlay and joined, with setters that emit a new `controllerViewChanged` signal and never call `checkpoint()`;
  - `shown_controller(track)`;
  - `workspace_controllers()`, the union, cached per clip.
- **`ui/timeline.py`:**
  - `_paint_track` splits the note area through a `track_layout(track)` helper that tests can call;
  - a new `_paint_controller` draws each line (steps or joined), culled with `bisect` to the visible span, starting from the point before it;
  - when points are denser than one per pixel, it draws each pixel column as its min–max span, so the cost follows the view width, not the event count (a Reason curve has a point every 1/32 beat);
  - points are cached per clip id beside `ClipRender`, and pruned in `_content_changed`;
  - repaints on `controllerViewChanged`.
- **`ui/track_panel.py`:**
  - a `ControllerBox` button in `TrackHeader`, placed under `remove_btn` at the right of the info line, with the info label narrowed beside it;
  - styled from `refresh()` the way the Solo button's red is (`background: theme.SOLO` when overridden);
  - its popup menu calls `ctl.set_track_controller`, built and replaced the way `_show_color_menu` handles its menu;
  - refreshes on `controllerViewChanged`.
- **`ui/main_window.py`:** the picker (`QComboBox`) and the two icon buttons (painted like `InfoButton`), refilled on `tracksChanged`; the View menu mirror.
- **`ui/session.py`:**
  - `capture` adds `controller_view: {show, overlay, joined}`;
  - `validate_settings` accepts it as optional (missing means defaults) and rejects malformed values like other bad settings;
  - the lifecycle marks the session dirty on `controllerViewChanged`.
- **`ui/theme.py`:** strip background and overlay edge colours.

## Tests (headless)

A new `tests/test_controller_display.py`, using `from test_ui_assembly import app, win` and the `helpers` builders (`smf`, `track`, `conductor`, `note`), in the pattern of `tests/test_track_export_channel.py`. Never a hand-built `MainWindow`.

- **Pure (`core/controllers.py`):**
  - order: Pitch Bend, Aftertouch, then CCs ascending, with names, and "CC n" for unnamed CCs;
  - short labels: CC1, CC11, PB, AT;
  - CC 0, 32, 6, 38, 96–101, 120–127 and poly pressure aren't listed;
  - step values hold; pitch bend centres at 0.5, and CC 127 gives 1.0;
  - joined points are the event points themselves, with a flat hold after the last;
  - an untrimmed start has no value before the first event;
  - a trimmed start carries the export's value, checked against `audible_events` for the same clip;
  - nothing past a trimmed end;
  - a controller only in a trimmed-away part isn't listed.
- **Channels:** a two-channel track gives one line per channel; with an export channel set, one merged line.
- **Picker:**
  - defaults to Off;
  - lists the union in order after importing two files;
  - updates after delete, trim, undo and redo;
  - a choice with no data left stays selected, greyed and marked, and returns when undo brings the data back;
  - the View menu mirror stays in step with the toolbar.
- **Mode and style buttons:** both disabled while nothing is shown; each toggles; tooltips follow the setting; the style setting reaches the painter.
- **Controller box:**
  - **Position:** its geometry sits under the ✕ (`remove_btn`), right-aligned with it, inside the header at the default lane height, and clear of the info text.
  - **Red only when overridden:** normal while following, including when the picker changes; red for a controller override and for None; normal again on Follow view.
  - **Label:** it shows the shown controller's short label.
  - **Popup:** "Follow view (…)" naming the current choice, None, then exactly this track's controllers in the picker's order, with the current choice ticked.
  - **Undo:** choosing an override is one undo step; undo and redo restore it and the box colour; choosing the current value makes no step; a new track from a clip move starts on Follow view.
  - **The colour-box menu** has no controller entry (regression).
- **Layout (`track_layout`):**
  - Lane mode gives a strip only to tracks that have the controller, and the notes stay inside the remaining area;
  - Overlay leaves the note area unchanged;
  - below the threshold, a track falls back to Overlay.
- **View state:** picker, mode and style changes make no undo step (`can_undo()` unchanged).
- **Painting:** paint the viewport to a pixmap with a dense curve (every 1/32 beat over 200 bars) at the widest and narrowest zoom, in both modes and both styles. It completes, and the decimated point count stays within twice the view width.
- **Display only (regression):** export bytes are identical with display off and in every mode and style, in all four export modes, with and without overrides, and the drag-out payload too.
- **Session (`tests/test_session.py`):**
  - `controller_view` and `Track.controller` round-trip;
  - a schema-5 session loads with defaults (use the existing schema-4 upgrade test as the pattern);
  - an unsupported schema and malformed values are rejected through the existing recovery without a crash (extend `test_bad_settings_rejected_before_model_applied` and the malformed-workspace cases);
  - the field-coverage test passes with the new field.
- **Real data:** a Reason fixture in `samples/` with dense curves lists its controllers and draws without error.
- After adding the UI tests, run the full suite (`.venv/bin/python -m pytest -q`) **four times**.

## Docs and checklist

- README:
  - the toolbar list in "The window" names the Controller list and its two buttons;
  - the track header description names the controller box (red when the track overrides the picker);
  - rows in the quick reference;
  - a line that it's display only and saved with the session.
- `docs/DEVELOPMENT.md`: the schema note says schema 6 adds `Track.controller`.
- TEST_CHECKLIST: new section **8r. Controller display (`feature/controller-display`)**, before section 9 (below).
- ROADMAP: remove the entry when built, and set this plan's status to built.

## Manual test

- Import a Reason song with mod-wheel and pitch-bend curves, and a Cubase project with CC data. The picker lists exactly what they hold: Pitch Bend and Aftertouch first, then the CCs, with no bank select or RPN entries.
- Pick each controller in turn. The curves look like the DAW's own lanes. Pitch bend shows its centre line. The View menu shows the same choice.
- Click the mode button: every track switches between the strip and the overlay at once. Click the style button: every line switches between steps and joined lines.
- Each header's box shows the controller (CC1, PB, …). Click one track's box and pick its own controller, then None:
  - the box turns red each time, and only that track changes;
  - Follow view returns it to normal;
  - undo and redo step through these choices.
- The colour-box menu still holds only colour and the export channel.
- On a track with two channels, set an export channel: the lines merge into one.
- Trim a clip in the middle of a curve. The line starts at the held value at the new edge. Export the clip into Reason or Cubase: the first value there matches.
- Zoom fully out on a long, dense song, and scroll. It stays responsive.
- Shrink the lanes to the minimum, then grow them: the strip gives way to the overlay, then returns. Note what the controller box does at short heights.
- Quit and reopen: the picker, mode, style and overrides come back.
- Export with display on and off: the files are the same.

## Decisions settled with the owner (2026-11-19)

1. **View state.** The picker, the mode and the style make no undo step, like zoom, lane height and Show Markers. Only the per-track override is undoable. Agreed.
2. **The box when the picker is Off and the track follows it.** An **empty** outlined box, still clickable, so a single track can show a controller with the picker Off. Agreed.
3. **The box at short lane heights.** Hidden below about 45 px, where the info line is already clipped. An overridden track still draws its own controller on the timeline. Agreed.

No design questions remain open.
