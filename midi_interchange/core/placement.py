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
* Several *files* may be laid end to end (revised 2026-11-10): each file starts
  where the previous one ended, and the files' tracks line up by position, so
  single-track files (DAW parts) become **one** new track named after the first
  file's track; for multi-track files the first tracks share a track, the
  second tracks share another, and so on. Names are ignored and nothing is
  matched to existing tracks (re-dropping an end-to-end run isn't supported).
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


def assign_tracks(candidates: list[Track], target: Track, names: list[str]) -> list[Track | None]:
    """For one imported file's track names, the existing track each joins (None = new track).

    Only call when target_matches() is true. Each existing track takes at most
    one imported track per file, so a file that repeats a name (Staccato does)
    pairs its copies in order with the existing same-named tracks: the first
    copy joins the first such track in display order, the second the next, and
    any extra copies become new tracks. A name the file uses only once prefers
    the target if it matches, else the first same-named track.
    """
    counts: dict[str, int] = {}
    for n in names:
        counts[norm_name(n)] = counts.get(norm_name(n), 0) + 1
    used: set[str] = set()
    out: list[Track | None] = []
    for n in names:
        free = [t for t in candidates if t.id not in used and names_match(t, n)]
        if counts[norm_name(n)] == 1 and target in free:
            dest = target
        else:
            dest = free[0] if free else None
        if dest is not None:
            used.add(dest.id)
        out.append(dest)
    return out


def end_to_end_names(names_per_file: list[list[str]]) -> list[str]:
    """Names of the tracks an end-to-end drop creates: one per track position,
    named after the first file that has a track there."""
    out: list[str] = []
    for names in names_per_file:
        out += names[len(out):]
    return out


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
    matching = not placement.end_to_end and target_matches(
        target, [t.name for _, tracks in parsed for t in tracks])
    cursor = max(placement.time, ZERO)
    run: list[Track] = []               # end-to-end: the new track for each track position

    for source, tracks in parsed:
        length = source_length(tracks)
        for t in tracks:
            for c in t.clips:
                c.offset += cursor
        fresh: list[Track] = []
        dests = assign_tracks(existing, target, [t.name for t in tracks]) if matching else [None] * len(tracks)
        for i, (t, dest) in enumerate(zip(tracks, dests)):
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
            if placement.end_to_end and i < len(run):
                dest = run[i]
                dest.clips.extend(t.clips)
                dest.refresh_channels()
                dest.sort_clips()
                continue
            fresh.append(t)
            if placement.end_to_end:
                run.append(t)
        notes += ws.add_import(source, fresh)
        stats["new_tracks"] += len(fresh)
        if placement.end_to_end:
            cursor += length
    if stats["replaced"]:
        ws.prune_sources()               # a replaced clip may have been its source's last
    return notes, stats
