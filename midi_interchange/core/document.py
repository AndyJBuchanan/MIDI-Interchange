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
    raw: bytes = field(repr=False)
    tempo_map: TempoMap = field(default_factory=TempoMap)
    path: str | None = None
    app: str | None = None       # source application, when known
    track_names: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def describe(self) -> str:
        lines = [
            f"Source: {self.name}",
            f"Path: {self.path or '—'}",
            f"Application: {self.app or 'unknown'}",
            f"SMF format {self.smf_format}, {self.ppq} PPQ, {len(self.raw)} bytes",
            f"Imported: {self.imported_at:%Y-%m-%d %H:%M:%S}",
        ]
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

    @property
    def start(self) -> Fraction:
        return self.offset

    @property
    def end(self) -> Fraction:
        return self.offset + self.length


@dataclass
class Track:
    id: str
    name: str
    source_id: str
    clips: list[Clip]
    original_name: str = ""
    enabled: bool = True
    color: str = TRACK_COLORS[0]
    auxiliary: bool = False      # holds only meta/sysex data (lyrics, markers, ...)
    channels: tuple[int, ...] = ()
    auto_trim: bool = False

    @property
    def start(self) -> Fraction:
        return min((c.start for c in self.clips), default=ZERO)

    @property
    def end(self) -> Fraction:
        return max((c.end for c in self.clips), default=ZERO)

    def copy(self) -> Track:
        return replace(self, clips=[replace(c) for c in self.clips])


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

    def enabled_tracks(self) -> list[Track]:
        return [t for t in self.tracks if t.enabled]

    # -- mutation ----------------------------------------------------------
    def add_import(self, source: Source, tracks: list[Track]) -> list[str]:
        """Add an imported source and its tracks. Returns informational notes.

        Tempo policy: the first source carrying a tempo map becomes the
        authoritative workspace map. Later sources keep their map on the
        Source record; conflicts are reported, never silently merged.
        """
        notes: list[str] = []
        self.sources.append(source)
        for t in tracks:
            t.color = TRACK_COLORS[next(self._color_cycle) % len(TRACK_COLORS)]
            self.tracks.append(t)
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
        used = {t.source_id for t in self.tracks}
        # Sources stay referenced while any track uses them; keep the
        # authoritative tempo source even if its tracks are gone.
        self.sources = [s for s in self.sources if s.id in used or s.id == self.tempo_source_id]

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
            "ranges": [replace(r) for r in self.ranges],
        }

    def restore(self, snap: dict) -> None:
        self.sources = list(snap["sources"])
        self.tracks = [t.copy() for t in snap["tracks"]]
        self.tempo_map = snap["tempo_map"]
        self.tempo_source_id = snap["tempo_source_id"]
        self.ranges = [replace(r) for r in snap["ranges"]]


def track_channels(events: list[Event]) -> tuple[int, ...]:
    return tuple(sorted({e.msg.channel for e in events if is_channel_msg(e.msg)}))
