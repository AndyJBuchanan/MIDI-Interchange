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
  (import_smf.song_title), never guessed from one name, so "Lead - Verse"
  never joins "Lead - Chorus". Exact matches are paired first, then these.
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
from .import_smf import SONG_SEP
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


def without_song(name: str, songs) -> set[str]:
    """The normalised name, plus the name with each known song title removed from its end."""
    n = norm_name(name)
    out = {n} if n else set()
    for song in songs:
        suffix = SONG_SEP + norm_name(song) if song.strip() else ""
        if suffix and n.endswith(suffix) and len(n) > len(suffix):
            out.add(n[:-len(suffix)])
    return out


def song_match(track: Track, name: str, song: str, track_songs) -> bool:
    """Whether `name` (from a file whose song is `song`) matches `track` once
    known song titles are removed from both (the second matching level)."""
    if not song and not track_songs:
        return False
    mine = without_song(track.name, track_songs) | without_song(track.original_name, track_songs)
    return bool(mine & without_song(name, [song]))


def target_matches(target: Track | None, names: list[str], songs: list[str] | None = None,
                   song_of=lambda _t: set()) -> bool:
    """Whether a drop on `target` matches by name at all: some imported track must match it."""
    if target is None:
        return False
    songs = songs or [""] * len(names)
    return any(names_match(target, n) or song_match(target, n, s, song_of(target))
               for n, s in zip(names, songs))


def assign_tracks(candidates: list[Track], target: Track, names: list[str],
                  songs: list[str] | None = None, song_of=lambda _t: set()) -> list[Track | None]:
    """For one imported file's track names, the existing track each joins (None = new track).

    Only call when target_matches() is true. Exact name matches are paired
    first; the remaining tracks then try again with song titles removed
    (`songs[i]` is imported track i's song, `song_of(track)` an existing
    track's songs). Each existing track takes at most one imported track per
    file, so a file that repeats a name (Staccato does) pairs its copies in
    order with the existing same-named tracks: the first copy joins the first
    such track in display order, the second the next, and any extra copies
    become new tracks. A name the file uses only once prefers the target if it
    matches, else the first same-named track.
    """
    songs = songs or [""] * len(names)
    counts: dict[str, int] = {}
    for n in names:
        counts[norm_name(n)] = counts.get(norm_name(n), 0) + 1
    used: set[str] = set()
    out: list[Track | None] = [None] * len(names)
    levels = (lambda t, n, s: names_match(t, n),
              lambda t, n, s: song_match(t, n, s, song_of(t)))
    for matches in levels:
        for i, (n, s) in enumerate(zip(names, songs)):
            if out[i] is not None:
                continue
            free = [t for t in candidates if t.id not in used and matches(t, n, s)]
            if counts[norm_name(n)] == 1 and target in free:
                dest = target
            else:
                dest = free[0] if free else None
            if dest is not None:
                used.add(dest.id)
                out[i] = dest
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
    "replaced": n clips replaced by an exact (same start and end) overlap,
    "by_song": n of the onto_existing matched only with song titles removed,
    "songs_ignored": [those song titles]}.
    """
    notes: list[str] = []
    stats = {"new_tracks": 0, "onto_existing": 0, "onto_names": [], "replaced": 0,
             "by_song": 0, "songs_ignored": []}
    target = ws.track(placement.target_track_id) if placement.target_track_id else None
    existing = list(ws.tracks)           # tracks made by this drop are never match candidates
    old_clips = {c.id for t in existing for c in t.clips}   # only these can be replaced
    def song_of(track: Track) -> set[str]:
        sids = {c.source_id for c in track.clips} | {track.source_id}
        return {src.song for sid in sids if (src := ws.source(sid)) and src.song}

    matching = not placement.end_to_end and target_matches(
        target, [t.name for _, tracks in parsed for t in tracks],
        [src.song for src, tracks in parsed for _ in tracks], song_of)
    cursor = max(placement.time, ZERO)
    run: list[Track] = []               # end-to-end: the new track for each track position

    for source, tracks in parsed:
        length = source_length(tracks)
        for t in tracks:
            for c in t.clips:
                c.offset += cursor
        fresh: list[Track] = []
        dests = (assign_tracks(existing, target, [t.name for t in tracks], [source.song] * len(tracks), song_of)
                 if matching else [None] * len(tracks))
        for i, (t, dest) in enumerate(zip(tracks, dests)):
            if dest is not None:
                if not names_match(dest, t.name):
                    stats["by_song"] += 1
                    for song in [source.song, *sorted(song_of(dest))]:
                        if song and song not in stats["songs_ignored"]:
                            stats["songs_ignored"].append(song)
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
