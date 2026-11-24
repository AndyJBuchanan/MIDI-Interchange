"""Mirror mode, pure logic: what carries across when a watched file is re-imported.

The new import replaces the sources, tracks and tempo map. Tracks are matched
to the old ones by the rule placement uses for drops (placement.assign_tracks),
so a matched track keeps its id: range selections and locks (``Range.excluded``
holds track ids) keep applying. Ranges are kept by time. Design:
docs/plans/0.5.0/mirror-mode.md.
"""
from __future__ import annotations

from .document import Track, Workspace
from .import_result import ImportResult
from .placement import assign_tracks, track_songs
from .timing import TempoMap


MuteState = dict[str, tuple[bool, bool]]       # track id -> (muted, soloed) as the file last saved them


def carry_over(ws: Workspace, result: ImportResult,
               file_state: MuteState | None = None) -> tuple[dict, dict, MuteState]:
    """The workspace snapshot for a fresh import, counts for the status message, and the file's mute state.

    Changes nothing in ``ws`` except taking colours from its colour cycle for
    new tracks. Returns (snapshot, {"tracks": n, "new": n, "gone": n}, file_state).
    Mute and solo: ``file_state`` is what the previous import's file said for each
    track id (none: unmuted, unsoloed). A matched track whose setting in the app
    differs from that is the owner's and keeps it; any other track takes what the
    new file saved (when its reader keeps that). The returned state is the new
    file's, by track id.
    """
    previous = file_state or {}
    source, tracks = result.source, list(result.tracks)
    old = list(ws.tracks)
    # No preferred target: a name the file uses once pairs with the first same-named track.
    dummy = Track(id="", name="", source_id="", clips=[])
    matches = assign_tracks(old, dummy, [t.name for t in tracks], source.song,
                            lambda t: track_songs(ws, t))
    nw = Workspace(sources=[source], ranges=[r.copy() for r in ws.ranges])
    nw._color_cycle = ws._color_cycle
    keep_file_state = result.preserve_track_state
    matched: set[str] = set()
    new_state: MuteState = {}
    for t, o in zip(tracks, matches):
        if o is None:
            muted, soloed = t.muted, t.soloed
            nw._add_track(t)                    # next colour, joins ranges, joins a solo group
            if keep_file_state:
                t.muted, t.soloed = muted, soloed
            new_state[t.id] = (t.muted, t.soloed)
            continue
        matched.add(o.id)
        file_muted, file_soloed = (t.muted, t.soloed) if keep_file_state else (False, False)
        t.id = o.id
        t.color, t.export_channel, t.controller = o.color, o.export_channel, o.controller
        new_state[t.id] = (file_muted, file_soloed)
        if (o.muted, o.soloed) != previous.get(o.id, (False, False)):
            t.muted, t.soloed = o.muted, o.soloed          # the owner's setting
        else:
            t.muted, t.soloed = file_muted, file_soloed
        nw.tracks.append(t)
    live = {t.id for t in nw.tracks}
    for r in nw.ranges:
        r.excluded &= live
    if not source.tempo_map.is_empty:
        nw.tempo_map, nw.tempo_source_id = source.tempo_map, source.id
    else:
        nw.tempo_map, nw.tempo_source_id = TempoMap(), None
    nw.sync_ranges()
    counts = {"tracks": len(tracks), "new": len(tracks) - len(matched), "gone": len(old) - len(matched)}
    return nw.snapshot(), counts, new_state
