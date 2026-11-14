# Plan: Timeline management

Status: **agreed** (2026-11-14). Not built. Branch, when built: `feature/timeline-management` from `main`, merged by PR into the current release branch (see [RELEASING.md, Branches](../RELEASING.md#branches)).

This is a fix, not the larger tempo work: per-section tempo maps are a separate, unagreed roadmap item. It does three things:

- makes the existing tempo map switch easy to find;
- gives markers their own row in the timeline header;
- shows only the markers that would be exported.

## Why

- **The tempo map switch is hard to find.** You can already choose which file supplies the workspace tempo map, but only from Timing ▸ Tempo Map. A studio user couldn't find it (2026-11-14).
- **The info row is overcrowded.** Tempo, time signature and markers share one 16 px row. The time signature is drawn at the event, the tempo 30 px to its right, and a marker 72 px to its right when they share a time. Changes close together overlap, and two files' markers pile up into unreadable text.
- **The header shows markers that won't be exported.** It draws every marker from every track, muted or not.

## Behaviour

### Finding the tempo map switch

- **Right-click on the ruler or the info rows** opens a menu with **Tempo Map ▸**. It lists the same files as Timing ▸ Tempo Map, with the current one ticked. Choosing one adopts that file's map, as the Timing menu does now. It's undoable.
- **Track right-click menu:** add **Use This Track's Tempo Map** for a track whose file has a tempo map. It's ticked when that file is already the tempo source. It's not shown for tracks whose file has no map.
- **No map at all:** the Tempo Map submenu shows the existing disabled line, "No imported tempo maps (using 120 BPM, 4/4)".
- The range strip's right-click menu doesn't change.

### Header rows

Top to bottom:

| Row | Height | Shown | Content |
|---|---|---|---|
| Ruler | 22 px | always | bar numbers |
| Tempo row | 16 px | always | time signature and tempo changes, as now. With no imported map it shows the default 120 BPM, 4/4 |
| Marker row | 16 px | when **Show Markers** is on **and** at least one exported track has a marker | markers and cue markers |
| Range strip | 20 px | always | ranges |

- **Tempo row:** the time signature is drawn at the change and the tempo just after it, as now. The 72 px marker offset is no longer needed.
- **Marker row:**
  - Each marker is drawn in its **track's colour**, with its line in the same colour. A colour too dark to read on the row's background (black, and the darker presets) is lightened. That rule lives in `ui/theme.py`, next to the other colours.
  - Labels are cut short with "…" at 120 px, as now.
- **Which markers are shown:** markers from the tracks that the global mute and solo would export, the same set as an export with no ranges. Mute a track, and its markers leave the header. To choose one file's markers over another's, mute the other file's marker track.
- **Header height changes:** the marker row appears or disappears when the set of shown markers goes from none to some, or back. That happens on import or drop, deleting tracks or clips, mute and solo changes, undo and redo, New, session restore, and toggling Show Markers.
  - The lanes and the track panel on the left move down or up by 16 px with it.
  - It never changes during a drag. A change caused by a drop applies after the drop.
  - Adopting a tempo map never changes the height, since maps hold no markers.

### Show Markers

- A checkable **Markers** button on the toolbar, after the Snap control. The same action is in the Timing menu as **Show Markers**.
- **On by default.** Remembered between runs in the app settings (QSettings key `show_markers`), not in the saved session.
- **Off:** no marker row, so the header is ruler, tempo row and range strip. Markers are still drawn in their own track lanes and are still exported. The setting only affects the header.
- It's listed in the roadmap's future settings page.

## Known restriction

- **A locked range can export a track that's muted globally.** The marker row follows the global mute and solo, not any range's own track choices, because it's one row for the whole song. So a range's export may contain markers the header doesn't show. This is accepted as minor (agreed 2026-11-14).

## Code

- **Header height (`ui/timeline.py`):** `HEADER_H`, `RANGE_TOP` and the other derived positions are module constants today. They become values the timeline works out (`header_h()`, `range_top()`, the marker row's top), from whether the marker row is shown.
  - The timeline emits a signal when the height changes. `ui/track_panel.py` and `ui/main_window.py` use the timeline's value instead of importing `HEADER_H`.
  - Hit testing, painting, drag-in auto-scroll and the drop marker on the ruler all use the new values.
- **Which markers (`core/`):** one function gives the tracks the global mute and solo would export, reusing the export's own rule (`Workspace.global_tracks()`) rather than repeating it. The marker row and the "is the marker row shown" check both use it.
- **Tempo Map menu:** one function builds the Tempo Map submenu. The Timing menu, the ruler/info row menu and the track menu all use it; the track menu's item uses the same adopt call (`controller.adopt_tempo`).
- **Show Markers:** one `QAction` (checkable), used by the toolbar and the Timing menu. Its state is read from and written to QSettings in `ui/main_window.py`.

## Tests (headless)

- **Menu:**
  - Right-click on the ruler and on the tempo row offers Tempo Map with every file that has a map, the current one ticked.
  - Choosing one adopts it, and undo puts the previous map back.
  - The track menu item adopts that track's file's map, and is missing for a file without one.
- **Header height:**
  - No markers: ruler + tempo row + range strip.
  - Import a file with markers: the marker row appears and the lanes move down 16 px. Undo removes it.
  - Mute the only marker track: the row goes. Unmute: it's back. Solo another track: the row follows the export set.
  - Show Markers off: no row even with markers. The setting persists across a new `MainWindow` built with the same INI settings.
  - Adopting a different tempo map doesn't change the height.
- **Hit testing:** with and without the marker row, a click in the range strip still hits ranges, a click on the ruler still starts a range, and lane clicks hit the right track.
- **Colour:** a marker on a black track is drawn in a lightened colour, not black.

## Manual checks (TEST_CHECKLIST, new section)

- Right-click the ruler and the tempo row: Tempo Map is there and switching works, including undo.
- Track right-click ▸ Use This Track's Tempo Map.
- Load two files that both have markers (for example two Staccato or Cubase exports with Transport tracks). Both sets show, each in its track's colour, on their own row without overlapping the tempo text. Mute one file's marker track: only the other's markers remain.
- Toggle Markers on the toolbar: the header shrinks and grows, and the setting survives a restart.
- Drag a file with markers into a workspace without any: the header grows after the drop, not during it.
