"""Where imported MIDI lands in the workspace.

Rules (agreed 2026-11-09, modelled on Cubase/Reason):

* Everything is placed at the drop time (the insertion cursor). A dragged clip
  carries no position of its own: DAWs write it starting at time zero.
* Dropped on a track (its lane, or its header for time zero): an imported track
  goes onto that track only when the names match (case-insensitive, compared
  with the track's current and original names). Otherwise it becomes a new
  track at the drop time. The user can then move the clip across.
* Dropped anywhere else: every imported track becomes a new track.
* Several *files* may be laid end to end: each file starts where the previous
  one ended. Same-named tracks from those files then share one new track, so a
  run of parts from one DAW track assembles into one track.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from .document import Source, Track, Workspace
from .timing import ZERO


@dataclass
class Placement:
    time: Fraction = ZERO
    target_track_id: str | None = None
    end_to_end: bool = False


def norm_name(name: str) -> str:
    return " ".join(name.split()).casefold()


def names_match(track: Track, name: str) -> bool:
    n = norm_name(name)
    return bool(n) and n in {norm_name(track.name), norm_name(track.original_name)}


def source_length(tracks: list[Track]) -> Fraction:
    return max((c.offset + c.length for t in tracks for c in t.clips), default=ZERO)


def place_imports(ws: Workspace, parsed: list[tuple[Source, list[Track]]],
                  placement: Placement) -> tuple[list[str], dict]:
    """Add parsed imports to the workspace according to the placement.

    Returns (notes, stats). stats: {"new_tracks": n, "onto_target": n}.
    """
    notes: list[str] = []
    stats = {"new_tracks": 0, "onto_target": 0}
    target = ws.track(placement.target_track_id) if placement.target_track_id else None
    cursor = max(placement.time, ZERO)
    run_tracks: dict[str, Track] = {}   # end-to-end: name -> new track made in this drop

    for source, tracks in parsed:
        length = source_length(tracks)
        for t in tracks:
            for c in t.clips:
                c.offset += cursor
        fresh: list[Track] = []
        for t in tracks:
            if target is not None and names_match(target, t.name):
                for c in list(t.clips):
                    target.clips.append(c)
                target.refresh_channels()
                target.sort_clips()
                stats["onto_target"] += 1
                continue
            key = norm_name(t.name)
            if placement.end_to_end and key and key in run_tracks:
                dest = run_tracks[key]
                dest.clips.extend(t.clips)
                dest.refresh_channels()
                dest.sort_clips()
                continue
            fresh.append(t)
            if placement.end_to_end and key:
                run_tracks[key] = t
        notes += ws.add_import(source, fresh)
        stats["new_tracks"] += len(fresh)
        if placement.end_to_end:
            cursor += length
    return notes, stats
