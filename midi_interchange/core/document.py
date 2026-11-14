"""Workspace -> Sources -> Tracks -> Clips -> Events.

Sources are immutable provenance records. Tracks and clips are lightweight and
copied for undo snapshots; their event lists are shared, never mutated.
"""
from __future__ import annotations

import itertools
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime
from fractions import Fraction

from .events import Event, is_channel_msg
from .ranges import Range
from .timing import TempoMap, ZERO

TRACK_COLORS = [
    "#4F9DDE", "#E0884A", "#6CC17A", "#C46BD6", "#E3C04E", "#E0607E",
    "#4EC9C2", "#9C8CE8", "#A3C94E", "#D98E6C",
]


def new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass(frozen=True)
class Source:
    id: str
    name: str                    # filename or clip label
    ppq: int
    smf_format: int
    imported_at: datetime
    raw: bytes = field(default=b"", repr=False)  # reserved; imports do not retain originals
    tempo_map: TempoMap = field(default_factory=TempoMap)
    path: str | None = None
    app: str | None = None       # source application, when known
    track_names: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    song: str = ""              # song title, when known (see names.song_title)
    byte_size: int | None = None  # original input size, independent of retained bytes

    input_format: str = 'smf'
    format_version: str | None = None

    @property
    def file_summary(self) -> str:
        size = f"{self.byte_size:,} bytes" if self.byte_size is not None else "size unknown"
        format_ = (f"SMF format {self.smf_format}" if self.input_format == "smf"
                   else f"DAWproject {self.format_version or '—'}")
        return f"{format_} · {self.ppq} PPQ · {size}"

    def describe(self) -> str:
        lines = [
            f"Source: {self.name}",
            f"Path: {self.path or '—'}",
            f"Application: {self.app or 'unknown'}",
            self.file_summary,
            f"Imported: {self.imported_at:%Y-%m-%d %H:%M:%S}",
        ]
        if self.song:
            lines.append(f"Song: {self.song}")
        if self.track_names:
            lines.append("Original tracks: " + ", ".join(n or "(unnamed)" for n in self.track_names))
        if not self.tempo_map.is_empty:
            t = self.tempo_map.effective_tempos()[0]
            ts = self.tempo_map.effective_timesigs()[0]
            lines.append(f"Tempo map: {t.bpm:.2f} BPM, {ts.numerator}/{ts.denominator}"
                         f" ({len(self.tempo_map.tempos)} tempo, {len(self.tempo_map.timesigs)} TS events)")
        lines.extend(f"⚠ {w}" for w in self.warnings)
        return "\n".join(lines)


@dataclass
class Clip:
    id: str
    events: list[Event]          # times relative to clip start, sorted by (time, seq)
    length: Fraction             # explicit end (end-of-track or last event)
    offset: Fraction = ZERO      # workspace position of the clip's time zero
    source_track_index: int = 0
    name: str = ""
    source_id: str = ""          # Source this clip's events came from (clips can move between tracks)
    # Edge trims, in clip time. ``events`` and ``length`` stay the full extent;
    # the trims only choose what shows and exports (cutting rules: export_smf).
    trim_start: Fraction = ZERO
    trim_end: Fraction | None = None     # None = not trimmed: the full length

    muted: bool = False         # disabled project clips remain editable but do not export

    def __post_init__(self) -> None:
        if self.trim_end is None:
            self.trim_end = self.length

    @property
    def start(self) -> Fraction:
        """Visible start (workspace time)."""
        return self.offset + self.trim_start

    @property
    def end(self) -> Fraction:
        """Visible end (workspace time)."""
        return self.offset + self.trim_end

    @property
    def full_start(self) -> Fraction:
        return self.offset

    @property
    def full_end(self) -> Fraction:
        return self.offset + self.length

    @property
    def is_trimmed(self) -> bool:
        return self.trim_start > ZERO or self.trim_end < self.length

    def set_start(self, start: Fraction) -> None:
        """Position the clip so its visible start is at ``start``. Every
        positioning goes through here, so trims travel with the clip."""
        self.offset = start - self.trim_start


@dataclass
class Track:
    id: str
    name: str
    source_id: str
    clips: list[Clip]
    original_name: str = ""
    muted: bool = False         # retained under solo; solo overrides it without clearing it
    soloed: bool = False
    color: str = TRACK_COLORS[0]
    auxiliary: bool = False      # holds only meta/sysex data (lyrics, markers, ...)
    channels: tuple[int, ...] = ()
    auto_trim: bool = False
    export_channel: int | None = None  # displayed channel 1–16; None preserves original channels

    @property
    def start(self) -> Fraction:
        return min((c.start for c in self.clips), default=ZERO)

    @property
    def end(self) -> Fraction:
        return max((c.end for c in self.clips), default=ZERO)

    def copy(self) -> Track:
        return replace(self, clips=[replace(c) for c in self.clips])

    def clip(self, clip_id: str) -> Clip | None:
        return next((c for c in self.clips if c.id == clip_id), None)

    def source_ids(self) -> list[str]:
        """Sources of this track's clips, in clip order, without duplicates."""
        out: list[str] = []
        for c in self.clips:
            sid = c.source_id or self.source_id
            if sid not in out:
                out.append(sid)
        return out or [self.source_id]

    def refresh_channels(self) -> None:
        """Recompute channels after clips were added or removed. A track that
        gains channel data stops being auxiliary; one never becomes auxiliary
        by losing it (it is removed instead when it has no clips)."""
        from .export_smf import visible_msgs     # the edge rules live with export (imported late: it needs this module)
        self.channels = msg_channels([m for c in self.clips for m in visible_msgs(c)])
        if self.channels:
            self.auxiliary = False

    def sort_clips(self) -> None:
        self.clips.sort(key=lambda c: (c.start, c.id))

    def overlaps(self) -> list[tuple[Fraction, Fraction]]:
        """Spans where two or more of this track's clips overlap."""
        spans: list[tuple[Fraction, Fraction]] = []
        cs = sorted(self.clips, key=lambda c: c.start)
        for i, a in enumerate(cs):
            for b in cs[i + 1:]:
                if b.start >= a.end:
                    break
                lo, hi = b.start, min(a.end, b.end)
                if hi > lo:
                    spans.append((lo, hi))
        return spans


@dataclass
class Workspace:
    sources: list[Source] = field(default_factory=list)
    tracks: list[Track] = field(default_factory=list)
    tempo_map: TempoMap = field(default_factory=TempoMap)
    tempo_source_id: str | None = None   # source whose map is authoritative
    ranges: list[Range] = field(default_factory=list)
    _color_cycle: itertools.count = field(default_factory=itertools.count, repr=False)

    # -- queries ---------------------------------------------------------
    def source(self, source_id: str) -> Source | None:
        return next((s for s in self.sources if s.id == source_id), None)

    def track(self, track_id: str) -> Track | None:
        return next((t for t in self.tracks if t.id == track_id), None)

    def range(self, range_id: str) -> Range | None:
        return next((r for r in self.ranges if r.id == range_id), None)

    @property
    def end(self) -> Fraction:
        return max((t.end for t in self.tracks), default=ZERO)

    def has_solos(self) -> bool:
        return any(t.soloed for t in self.tracks)

    def global_tracks(self) -> list[Track]:
        solo = self.has_solos()
        return [t for t in self.tracks if (t.soloed if solo else not t.muted)]

    def sync_ranges(self) -> None:
        included = {t.id for t in self.global_tracks()}
        for r in self.ranges:
            if not r.track_locked:
                r.excluded = {t.id for t in self.tracks if t.id not in included}


    # -- mutation ----------------------------------------------------------
    def _add_track(self, track: Track, index: int | None = None) -> None:
        """New tracks always start audible to export, joining an existing solo group."""
        track.muted = False
        track.soloed = self.has_solos()
        track.color = TRACK_COLORS[next(self._color_cycle) % len(TRACK_COLORS)]
        self.tracks.insert(len(self.tracks) if index is None else index, track)
        for r in self.ranges:
            r.set_included(track.id, True)
        self.sync_ranges()

    def add_import(self, source: Source, tracks: list[Track], *,
                   preserve_track_state: bool = False) -> list[str]:
        """Add an imported source and its tracks. Returns informational notes.

        Tempo policy: the first source carrying a tempo map becomes the
        authoritative workspace map. Later sources keep their map on the
        Source record; conflicts are reported, never silently merged.
        """
        notes: list[str] = []
        self.sources.append(source)
        for t in tracks:
            muted, soloed = t.muted, t.soloed
            self._add_track(t)
            if preserve_track_state:
                t.muted, t.soloed = muted, soloed
        self.sync_ranges()
        if not source.tempo_map.is_empty:
            if self.tempo_source_id is None:
                self.adopt_tempo_map(source.id)
            elif not source.tempo_map.equivalent(self.tempo_map):
                notes.append(f"{source.name}: tempo map differs from the workspace map "
                             f"(kept with source; use Timing ▸ Tempo Map to adopt it)")
        return notes

    def adopt_tempo_map(self, source_id: str) -> None:
        src = self.source(source_id)
        if src is None:
            raise KeyError(source_id)
        self.tempo_map = src.tempo_map
        self.tempo_source_id = source_id

    def remove_track(self, track_id: str) -> None:
        self.tracks = [t for t in self.tracks if t.id != track_id]
        self.prune_sources()
        self.sync_ranges()

    def prune_sources(self) -> None:
        # Sources stay referenced while any clip uses them; keep the
        # authoritative tempo source even if its clips are gone.
        used = {sid for t in self.tracks for sid in t.source_ids()}
        self.sources = [s for s in self.sources if s.id in used or s.id == self.tempo_source_id]

    def remove_empty_tracks(self) -> list[str]:
        gone = [t.id for t in self.tracks if not t.clips]
        if gone:
            self.tracks = [t for t in self.tracks if t.clips]
            self.prune_sources()
        self.sync_ranges()
        return gone

    def find_clip(self, clip_id: str) -> tuple[Track, Clip] | None:
        for t in self.tracks:
            c = t.clip(clip_id)
            if c is not None:
                return t, c
        return None

    def move_clip_to_track(self, clip_id: str, track_id: str, offset: Fraction | None = None) -> None:
        """Move a clip to another track (and optionally a new position). Empty
        tracks are left in place; call remove_empty_tracks() when the gesture ends."""
        found = self.find_clip(clip_id)
        dest = self.track(track_id)
        if found is None or dest is None:
            return
        src, clip = found
        if offset is not None:
            clip.set_start(max(offset, ZERO))
        if src is not dest:
            src.clips.remove(clip)
            if not clip.source_id:
                clip.source_id = src.source_id
            dest.clips.append(clip)
            src.refresh_channels()
            dest.refresh_channels()
        dest.sort_clips()

    def new_track_for_clip(self, clip_id: str, index: int | None = None,
                           like: Track | None = None) -> Track | None:
        """Move a clip onto a new track named after `like` (default: the clip's current track)."""
        found = self.find_clip(clip_id)
        if found is None:
            return None
        src, clip = found
        like = like or src
        t = Track(id=new_id(), name=like.name, source_id=clip.source_id or src.source_id, clips=[],
                  original_name=like.original_name)
        self._add_track(t, index)
        self.move_clip_to_track(clip_id, t.id)
        return t

    def delete_clip(self, clip_id: str) -> None:
        found = self.find_clip(clip_id)
        if found is None:
            return
        t, clip = found
        t.clips.remove(clip)
        t.refresh_channels()
        self.remove_empty_tracks()

    def duplicate_clip(self, clip_id: str, offset: Fraction | None = None,
                       track_id: str | None = None) -> Clip | None:
        """Copy a clip (events are shared, never mutated). Default position:
        straight after the original on the same track."""
        found = self.find_clip(clip_id)
        if found is None:
            return None
        t, clip = found
        dest = self.track(track_id) if track_id else t
        if dest is None:
            return None
        dup = replace(clip, id=new_id(), source_id=clip.source_id or t.source_id)
        dup.set_start(clip.end if offset is None else max(offset, ZERO))
        dest.clips.append(dup)
        dest.refresh_channels()
        dest.sort_clips()
        return dup

    def can_split_clip(self, clip_id: str, time: Fraction,
                       min_length: Fraction | None = None) -> bool:
        found = self.find_clip(clip_id)
        if found is None:
            return False
        clip = found[1]
        minimum = self._default_min_trim(clip) if min_length is None else min_length
        return minimum > ZERO and clip.start + minimum <= time <= clip.end - minimum

    def split_clip(self, clip_id: str, time: Fraction,
                   min_length: Fraction | None = None) -> Clip | None:
        """Split using shared events and reversible trims; invalid cuts are atomic no-ops."""
        if not self.can_split_clip(clip_id, time, min_length):
            return None
        track, clip = self.find_clip(clip_id)
        right = self.duplicate_clip(clip_id, offset=clip.start)
        self.trim_clip(clip_id, "end", time, min_length)
        self.trim_clip(right.id, "start", time, min_length)
        track.sort_clips()
        return right

    def snap_clip_to_previous(self, clip_id: str) -> bool:
        """Move a clip so it starts where the previous clip on its track ends.
        Returns False when there is no previous clip."""
        found = self.find_clip(clip_id)
        if found is None:
            return False
        t, clip = found
        prev = [c for c in t.clips if c is not clip and c.start < clip.start]
        if not prev:
            return False
        clip.set_start(max(c.end for c in prev))
        t.sort_clips()
        return True

    def _default_min_trim(self, clip: Clip) -> Fraction:
        src = self.source(clip.source_id)
        return Fraction(1, src.ppq if src else 480)

    def can_trim_move(self, clip_id: str, edge: str, direction: int,
                      min_length: Fraction | None = None) -> bool:
        """Whether a clip's visible ``edge`` can still move in ``direction`` (-1 earlier,
        +1 later). The limits are the ones trim_clip clamps to, kept together here."""
        found = self.find_clip(clip_id)
        if found is None:
            return False
        clip = found[1]
        if min_length is None:
            min_length = self._default_min_trim(clip)
        if edge == "start":
            if direction < 0:
                return clip.trim_start > ZERO and clip.start > ZERO
            return clip.trim_start < clip.trim_end - min_length
        if edge == "end":
            if direction > 0:
                return clip.trim_end < clip.length
            return clip.trim_end > clip.trim_start + min_length
        raise ValueError(edge)

    def trim_clip(self, clip_id: str, edge: str, time: Fraction, min_length: Fraction | None = None) -> bool:
        """Move a clip's visible ``edge`` ("start" or "end") to workspace
        ``time``. The edge stays within the clip's full extent, and the two
        edges keep at least ``min_length`` apart (default: one tick of the
        clip's source). Returns whether anything changed."""
        found = self.find_clip(clip_id)
        if found is None:
            return False
        track, clip = found
        if min_length is None:
            min_length = self._default_min_trim(clip)
        t = time - clip.offset                      # clip time
        if edge == "start":
            new = min(max(t, ZERO), max(clip.trim_end - min_length, clip.trim_start))
            changed, clip.trim_start = new != clip.trim_start, new
        elif edge == "end":
            new = max(min(t, clip.length), min(clip.trim_start + min_length, clip.trim_end))
            changed, clip.trim_end = new != clip.trim_end, new
        else:
            raise ValueError(edge)
        if changed:
            track.refresh_channels()
        return changed

    def restore_clip(self, clip_id: str) -> bool:
        """Put both edges back to the clip's full extent."""
        found = self.find_clip(clip_id)
        if found is None or not found[1].is_trimmed:
            return False
        track, clip = found
        clip.trim_start, clip.trim_end = ZERO, clip.length
        track.refresh_channels()
        return True

    def merge_tracks(self, from_id: str, into_id: str) -> None:
        """Move every clip of one track onto another and drop the emptied track."""
        src, dest = self.track(from_id), self.track(into_id)
        if src is None or dest is None or src is dest:
            return
        for c in list(src.clips):
            self.move_clip_to_track(c.id, dest.id)
        self.remove_empty_tracks()

    def clear(self) -> None:
        """Empty the workspace (File ▸ New). The colour cycle restarts."""
        self.sources = []
        self.tracks = []
        self.tempo_map = TempoMap()
        self.tempo_source_id = None
        self.ranges = []
        self._color_cycle = itertools.count()

    def move_track(self, track_id: str, new_index: int) -> None:
        t = self.track(track_id)
        if t is None:
            return
        self.tracks.remove(t)
        self.tracks.insert(max(0, min(new_index, len(self.tracks))), t)

    # -- undo snapshots ----------------------------------------------------------
    def snapshot(self) -> dict:
        return {
            "sources": list(self.sources),
            "tracks": [t.copy() for t in self.tracks],
            "tempo_map": self.tempo_map,
            "tempo_source_id": self.tempo_source_id,
            "ranges": [r.copy() for r in self.ranges],
        }

    def restore(self, snap: dict) -> None:
        self.sources = list(snap["sources"])
        self.tracks = [t.copy() for t in snap["tracks"]]
        self.tempo_map = snap["tempo_map"]
        self.tempo_source_id = snap["tempo_source_id"]
        self.ranges = [r.copy() for r in snap["ranges"]]


def track_channels(events: list[Event]) -> tuple[int, ...]:
    return msg_channels([e.msg for e in events])


def msg_channels(msgs) -> tuple[int, ...]:
    return tuple(sorted({m.channel for m in msgs if is_channel_msg(m)}))
