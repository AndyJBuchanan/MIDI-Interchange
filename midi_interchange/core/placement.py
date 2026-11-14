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
* Song titles (added 2026-11-10): when no name matches exactly, names are
  compared again with a known song title removed from the end (" - <song>"),
  on both sides. Staccato names tracks "Drums - <song>" and changes the song
  between generations, so "Drums - Staccato Generation" joins
  "Drums - Industrial EBM Anthem". A song is known only from the file itself
  (names.song_title), never guessed from one name, so "Lead - Verse"
  never joins "Lead - Chorus". Exact matches are paired first, then these.
* A clip landing on an existing track **replaces** any clip already there with
  exactly the same start and end (a like-for-like round trip). A trimmed clip
  counts by its visible edges (``Placement.compare_full_extent`` compares the
  full extents instead). Partial overlaps are kept and tinted. Clips added by the same drop are never replaced.
* Dropped anywhere else: every imported track becomes a new track (the way to
  avoid matching).
* Several *files* may be laid end to end (revised 2026-11-10): each file starts
  where the previous one ended, and the files' tracks line up by position, so
  single-track files (DAW parts) become **one** new track named after the first
  file's track; for multi-track files the first tracks share a track, the
  second tracks share another, and so on. Names are ignored and nothing is
  matched to existing tracks (re-dropping an end-to-end run isn't supported).

All of this is decided in one place, plan_drop(): the drop preview, the
several-files dialog and the drop itself all use it, so what the cursor
says is what happens. Name rules live in names.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from .document import Source, Track, Workspace
from .names import norm_name, quoted, without_song
from .timing import ZERO


@dataclass
class Placement:
    time: Fraction = ZERO
    target_track_id: str | None = None
    end_to_end: bool = False
    compare_full_extent: bool = False    # replace-on-drop compares full extents, not visible edges


def names_match(track: Track, name: str) -> bool:
    """First level: the same name (current or original), ignoring case and spacing."""
    n = norm_name(name)
    return bool(n) and n in {norm_name(track.name), norm_name(track.original_name)}


def song_match(track: Track, name: str, song: str, track_songs) -> bool:
    """Second level: `name` (from a file whose song is `song`) matches `track`
    once known song titles are removed from both."""
    if not song and not track_songs:
        return False
    mine = without_song(track.name, track_songs) | without_song(track.original_name, track_songs)
    return bool(mine & without_song(name, [song]))


def track_songs(ws: Workspace, track: Track) -> set[str]:
    """The song titles known for an existing track: those of its clips' sources."""
    sids = {c.source_id for c in track.clips} | {track.source_id}
    return {src.song for sid in sids if (src := ws.source(sid)) and src.song}


# A destination: an existing Track, an int (end-to-end: the run track at that
# position, made earlier in the same drop), or None (a new track).
Dest = Track | int | None


@dataclass
class DropPlan:
    """What a drop will do, decided before anything changes."""
    target: Track | None
    matching: bool                                  # names are matched against existing tracks
    dests: list[list[Dest]] = field(default_factory=list)       # per file, per imported track
    by_song: list[list[bool]] = field(default_factory=list)     # joined only with song titles removed
    new_names: list[str] = field(default_factory=list)          # tracks the drop makes, in order
    songs_ignored: list[str] = field(default_factory=list)
    no_match: str = ""                              # dropped on a track that nothing matched: why

    def onto(self) -> list[Track]:
        """The existing tracks that receive clips, in order, each once."""
        out: list[Track] = []
        for d in (d for ds in self.dests for d in ds):
            if isinstance(d, Track) and d not in out:
                out.append(d)
        return out


def _assign(candidates: list[Track], target: Track, names: list[str], song: str,
            song_of) -> list[Track | None]:
    """For one imported file's track names, the existing track each joins (None = new track).

    Exact name matches are paired first; the remaining tracks then try again
    with song titles removed. Each existing track takes at most one imported
    track per file, so a file that repeats a name (Staccato does) pairs its
    copies in order with the existing same-named tracks: the first copy joins
    the first such track in display order, the second the next, and any extra
    copies become new tracks. A name the file uses only once prefers the
    target if it matches, else the first same-named track.
    """
    counts: dict[str, int] = {}
    for n in names:
        counts[norm_name(n)] = counts.get(norm_name(n), 0) + 1
    used: set[str] = set()
    out: list[Track | None] = [None] * len(names)
    levels = (lambda t, n: names_match(t, n),
              lambda t, n: song_match(t, n, song, song_of(t)))
    for matches in levels:
        for i, n in enumerate(names):
            if out[i] is not None:
                continue
            free = [t for t in candidates if t.id not in used and matches(t, n)]
            dest = target if counts[norm_name(n)] == 1 and target in free else (free[0] if free else None)
            if dest is not None:
                used.add(dest.id)
                out[i] = dest
    return out


def plan_drop(ws: Workspace, files: list[tuple[Source, list[Track]]], placement: Placement) -> DropPlan:
    """Decide where each imported track goes. Changes nothing."""
    target = ws.track(placement.target_track_id) if placement.target_track_id else None
    existing = list(ws.tracks)           # tracks made by this drop are never match candidates

    def song_of(track: Track) -> set[str]:
        return track_songs(ws, track)

    matching = (not placement.end_to_end and target is not None and any(
        names_match(target, t.name) or song_match(target, t.name, src.song, song_of(target))
        for src, tracks in files for t in tracks))
    plan = DropPlan(target, matching)
    run_len = 0
    for src, tracks in files:
        names = [t.name for t in tracks]
        if matching:
            dests: list[Dest] = list(_assign(existing, target, names, src.song, song_of))
        elif placement.end_to_end:
            dests = [i if i < run_len else None for i in range(len(tracks))]
            run_len = max(run_len, len(tracks))
        else:
            dests = [None] * len(tracks)
        by_song = [isinstance(d, Track) and not names_match(d, n) for d, n in zip(dests, names)]
        for d, song_only in zip(dests, by_song):
            if song_only:
                for song in [src.song, *sorted(song_of(d))]:
                    if song and song not in plan.songs_ignored:
                        plan.songs_ignored.append(song)
        plan.new_names += [n for d, n in zip(dests, names) if d is None]
        plan.dests.append(dests)
        plan.by_song.append(by_song)
    if target is not None and not placement.end_to_end and not matching:
        file_songs = sorted({src.song for src, _ in files if src.song})
        detail = [f"the file's tracks are {quoted(t.name for _, ts in files for t in ts)}"]
        detail.append(f"its song title is {quoted(file_songs)}" if file_songs else "it has no song title")
        tsongs = sorted(song_of(target))
        detail.append(f"the track's song title is {quoted(tsongs)}" if tsongs else "the track has no song title")
        plan.no_match = f"nothing matches “{target.name}” ({'; '.join(detail)})"
    return plan


def source_length(tracks: list[Track]) -> Fraction:
    return max((c.end for t in tracks for c in t.clips), default=ZERO)


def place_imports(ws: Workspace, parsed: list[tuple[Source, list[Track]]],
                  placement: Placement) -> tuple[list[str], dict]:
    """Add parsed imports to the workspace: carry out plan_drop().

    Returns (notes, stats). stats: {"new_tracks": n, "onto_existing": n,
    "onto_names": [names of the existing tracks that received clips],
    "replaced": n clips replaced by an exact (same start and end) overlap,
    "by_song": n of the onto_existing matched only with song titles removed,
    "songs_ignored": [those song titles], "no_match": plan.no_match}.
    """
    plan = plan_drop(ws, parsed, placement)
    notes: list[str] = []
    stats = {"new_tracks": 0, "onto_existing": 0, "onto_names": [t.name for t in plan.onto()],
             "replaced": 0, "by_song": sum(map(sum, plan.by_song)),
             "songs_ignored": list(plan.songs_ignored), "no_match": plan.no_match}
    old_clips = {c.id for t in ws.tracks for c in t.clips}   # only these can be replaced
    cursor = max(placement.time, ZERO)
    run: list[Track] = []               # end-to-end: the new track for each track position

    for result, dests in zip(parsed, plan.dests):
        source, tracks = result
        length = source_length(tracks)
        for t in tracks:
            for c in t.clips:
                c.set_start(c.start + cursor)
        fresh: list[Track] = []
        for t, dest in zip(tracks, dests):
            if isinstance(dest, Track):
                for c in t.clips:
                    edges = ((lambda x: (x.full_start, x.full_end)) if placement.compare_full_extent
                             else (lambda x: (x.start, x.end)))
                    same = [o for o in dest.clips if o.id in old_clips and edges(o) == edges(c)]
                    for o in same:
                        dest.clips.remove(o)
                        old_clips.discard(o.id)
                    stats["replaced"] += len(same)
                stats["onto_existing"] += 1
            elif isinstance(dest, int):
                dest = run[dest]
            else:
                fresh.append(t)
                if placement.end_to_end:
                    run.append(t)
                continue
            dest.clips.extend(t.clips)
            dest.refresh_channels()
            dest.sort_clips()
        notes += ws.add_import(source, fresh, preserve_track_state=getattr(result, 'preserve_track_state', False))
        stats["new_tracks"] += len(fresh)
        if placement.end_to_end:
            cursor += length
    if stats["replaced"]:
        ws.prune_sources()               # a replaced clip may have been its source's last
    return notes, stats
