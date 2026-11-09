"""Where imported MIDI lands in the workspace.

Rules (agreed 2026-11-09, modelled on Cubase/Reason):

* Everything is placed at the drop time (the insertion cursor). A dragged clip
  carries no position of its own: DAWs write it starting at time zero.
* Dropped on a track (its lane, or its header for time zero): names are
  compared case-insensitively against each track's current and original names.
  If no imported track matches the track under the cursor, everything becomes
  new tracks at the drop time. If one does, it joins that track, and the other
  imported tracks also join existing tracks with matching names (the rest
  become new tracks). So a multi-track file round-tripped from another app,
  dropped on one of its tracks, lands back on all of them. The user can move
  clips afterwards.
* A clip landing on an existing track **replaces** any clip already there with
  exactly the same start and end (a like-for-like round trip). Partial overlaps
  are kept and tinted. Clips added by the same drop are never replaced.
* Dropped anywhere else: every imported track becomes a new track (the way to
  avoid matching).
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


def target_matches(target: Track | None, names: list[str]) -> bool:
    """Whether a drop on `target` matches by name at all: some imported track must match it."""
    return target is not None and any(names_match(target, n) for n in names)


def match_track(candidates: list[Track], target: Track, name: str) -> Track | None:
    """The existing track an imported track named `name` joins, or None for a new track.

    Only call when target_matches() is true. The target wins a tie; otherwise
    the first same-named track in display order.
    """
    if names_match(target, name):
        return target
    return next((t for t in candidates if names_match(t, name)), None)


def source_length(tracks: list[Track]) -> Fraction:
    return max((c.offset + c.length for t in tracks for c in t.clips), default=ZERO)


def place_imports(ws: Workspace, parsed: list[tuple[Source, list[Track]]],
                  placement: Placement) -> tuple[list[str], dict]:
    """Add parsed imports to the workspace according to the placement.

    Returns (notes, stats). stats: {"new_tracks": n, "onto_existing": n,
    "onto_names": [names of the existing tracks that received clips],
    "replaced": n clips replaced by an exact (same start and end) overlap}.
    """
    notes: list[str] = []
    stats = {"new_tracks": 0, "onto_existing": 0, "onto_names": [], "replaced": 0}
    target = ws.track(placement.target_track_id) if placement.target_track_id else None
    existing = list(ws.tracks)           # tracks made by this drop are never match candidates
    old_clips = {c.id for t in existing for c in t.clips}   # only these can be replaced
    matching = target_matches(target, [t.name for _, tracks in parsed for t in tracks])
    cursor = max(placement.time, ZERO)
    run_tracks: dict[str, Track] = {}   # end-to-end: name -> new track made in this drop

    for source, tracks in parsed:
        length = source_length(tracks)
        for t in tracks:
            for c in t.clips:
                c.offset += cursor
        fresh: list[Track] = []
        for t in tracks:
            dest = match_track(existing, target, t.name) if matching else None
            if dest is not None:
                for c in t.clips:
                    same = [o for o in dest.clips
                            if o.id in old_clips and o.start == c.start and o.end == c.end]
                    for o in same:
                        dest.clips.remove(o)
                        old_clips.discard(o.id)
                    stats["replaced"] += len(same)
                dest.clips.extend(t.clips)
                dest.refresh_channels()
                dest.sort_clips()
                stats["onto_existing"] += 1
                if dest.name not in stats["onto_names"]:
                    stats["onto_names"].append(dest.name)
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
    if stats["replaced"]:
        ws.prune_sources()               # a replaced clip may have been its source's last
    return notes, stats
