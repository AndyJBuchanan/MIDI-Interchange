"""UI-facing owner of the Workspace: mutations, undo/redo, signals."""
from __future__ import annotations

from fractions import Fraction

from PySide6.QtCore import QObject, Signal

from ..core.document import Workspace
from ..core.export_smf import ExportMode, ExportOptions, ExportResult, build_exports
from ..core.import_smf import ImportError_, import_smf_bytes
from ..core.placement import Placement, place_imports
from ..core.ranges import Range
from ..core.timing import SnapSetting, ZERO
from ..interchange.payload import Payload

SNAP_CHOICES: list[tuple[str, SnapSetting]] = [
    ("Off", None), ("Bar", "bar"), ("Beat", "beat"),
    ("1/8", Fraction(1, 2)), ("1/16", Fraction(1, 4)), ("1/32", Fraction(1, 8)),
    ("1/8T", Fraction(1, 3)), ("1/16T", Fraction(1, 6)),
]



class Controller(QObject):
    tracksChanged = Signal()
    rangesChanged = Signal()
    selectionChanged = Signal()
    tempoChanged = Signal()
    undoStateChanged = Signal()
    exportSettingsChanged = Signal()
    message = Signal(str)

    UNDO_LIMIT = 200

    def __init__(self) -> None:
        super().__init__()
        self.ws = Workspace()
        self.selected_range_id: str | None = None
        self.snap: SnapSetting = "beat"
        self.export_mode = ExportMode.REBASE   # default (2026-11-10); with no ranges, export is whole
        self.trim = False
        self.solo: tuple[str, dict[str, bool]] | None = None   # (soloed track id, enabled states before)
        self._undo: list[tuple[dict, str | None]] = []
        self._redo: list[tuple[dict, str | None]] = []

    # -- undo --------------------------------------------------------------
    def checkpoint(self) -> None:
        self._undo.append((self.ws.snapshot(), self.selected_range_id))
        del self._undo[:-self.UNDO_LIMIT]
        self._redo.clear()
        self.undoStateChanged.emit()

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> None:
        if self._undo:
            self._redo.append((self.ws.snapshot(), self.selected_range_id))
            snap, sel = self._undo.pop()
            self._apply(snap, sel)

    def redo(self) -> None:
        if self._redo:
            self._undo.append((self.ws.snapshot(), self.selected_range_id))
            snap, sel = self._redo.pop()
            self._apply(snap, sel)

    def _apply(self, snap: dict, sel: str | None) -> None:
        self.ws.restore(snap)
        self.selected_range_id = sel if self.ws.range(sel or "") else None
        self.tracksChanged.emit()
        self.tempoChanged.emit()
        self.rangesChanged.emit()
        self.selectionChanged.emit()
        self.undoStateChanged.emit()

    # -- import ---------------------------------------------------------------
    def parse_payloads(self, payloads: list[Payload]) -> tuple[list, list[str]]:
        parsed, errors = [], []
        for p in payloads:
            try:
                parsed.append(import_smf_bytes(p.data, p.name, path=p.path, app=p.app))
            except ImportError_ as exc:
                errors.append(f"{p.name}: {exc}")
        return parsed, errors

    def import_payloads(self, payloads: list[Payload], placement: Placement | None = None) -> list[str]:
        """Import payloads accumulatively. Returns error strings for failures."""
        parsed, errors = self.parse_payloads(payloads)
        if parsed:
            self.checkpoint()
            had_tempo = self.ws.tempo_source_id
            notes, stats = place_imports(self.ws, parsed, placement or Placement())
            for source, _tracks in parsed:
                notes += [f"{source.name}: {w}" for w in source.warnings]
            self.tracksChanged.emit()
            if had_tempo != self.ws.tempo_source_id:
                self.tempoChanged.emit()
            summary = f"Imported {len(parsed)} file(s)"
            parts = []
            if stats["new_tracks"]:
                parts.append(f"{stats['new_tracks']} new track(s)")
            if stats["onto_existing"]:
                names = ", ".join(f"“{n}”" for n in stats["onto_names"])
                parts.append(f"{stats['onto_existing']} onto existing {names}")
            if stats["replaced"]:
                parts.append(f"replacing {stats['replaced']} identical clip(s)")
            if placement and placement.time:
                parts.append(f"at {self.ws.tempo_map.format_bbt(placement.time)}")
            if parts:
                summary += ": " + ", ".join(parts)
            self.message.emit("  ·  ".join([summary, *notes]))
        return errors

    def new_document(self) -> None:
        """Clear the workspace (one undoable step). Export settings are kept."""
        if not (self.ws.tracks or self.ws.ranges or self.ws.sources):
            return
        self.checkpoint()
        self.ws.clear()
        self.solo = None
        self.selected_range_id = None
        self.tracksChanged.emit()
        self.tempoChanged.emit()
        self.rangesChanged.emit()
        self.selectionChanged.emit()
        self.message.emit("New workspace (Undo brings the previous one back)")

    # -- clips -------------------------------------------------------------
    def move_clip_live(self, clip_id: str, offset: Fraction, track_id: str | None = None) -> None:
        """Live clip move during a drag (caller checkpoints once at drag start)."""
        found = self.ws.find_clip(clip_id)
        if found is None:
            return
        src, clip = found
        offset = max(offset, ZERO)
        dest = track_id or src.id
        if offset != clip.offset or dest != src.id:
            self.ws.move_clip_to_track(clip_id, dest, offset)
            self.tracksChanged.emit()

    def end_clip_gesture(self) -> None:
        if self.ws.remove_empty_tracks():
            self.tracksChanged.emit()

    def move_clip_to_track(self, clip_id: str, track_id: str | None) -> None:
        """Menu command: move to another track, or to a new track when track_id is None."""
        found = self.ws.find_clip(clip_id)
        if found is None:
            return
        self.checkpoint()
        if track_id is None:
            idx = self.ws.tracks.index(found[0]) + 1
            self.ws.new_track_for_clip(clip_id, idx)
        else:
            self.ws.move_clip_to_track(clip_id, track_id)
        self.ws.remove_empty_tracks()
        self.tracksChanged.emit()

    def delete_clip(self, clip_id: str) -> None:
        if self.ws.find_clip(clip_id):
            self.checkpoint()
            self.ws.delete_clip(clip_id)
            self.tracksChanged.emit()

    def duplicate_clip(self, clip_id: str, offset: Fraction | None = None,
                       track_id: str | None = None, checkpoint: bool = True) -> str | None:
        if not self.ws.find_clip(clip_id):
            return None
        if checkpoint:
            self.checkpoint()
        dup = self.ws.duplicate_clip(clip_id, offset, track_id)
        self.tracksChanged.emit()
        return dup.id if dup else None

    def snap_clip_to_previous(self, clip_id: str) -> None:
        found = self.ws.find_clip(clip_id)
        if found is None:
            return
        snap = self.ws.snapshot()
        if self.ws.snap_clip_to_previous(clip_id):
            self._undo.append((snap, self.selected_range_id))
            del self._undo[:-self.UNDO_LIMIT]
            self._redo.clear()
            self.undoStateChanged.emit()
            self.tracksChanged.emit()
        else:
            self.message.emit("No earlier clip on this track to butt against")

    def merge_tracks(self, from_id: str, into_id: str) -> None:
        if self.ws.track(from_id) and self.ws.track(into_id) and from_id != into_id:
            self.checkpoint()
            self.ws.merge_tracks(from_id, into_id)
            self.tracksChanged.emit()

    # -- tracks --------------------------------------------------------------
    def set_track_enabled(self, track_id: str, enabled: bool) -> None:
        t = self.ws.track(track_id)
        if t and t.enabled != enabled:
            self.checkpoint()
            t.enabled = enabled
            self.tracksChanged.emit()

    def rename_track(self, track_id: str, name: str) -> None:
        t = self.ws.track(track_id)
        name = name.strip()
        if t and name and t.name != name:
            self.checkpoint()
            t.name = name
            self.tracksChanged.emit()

    def set_track_color(self, track_id: str, color: str) -> None:
        t = self.ws.track(track_id)
        if t and t.color != color:
            self.checkpoint()
            t.color = color
            self.tracksChanged.emit()

    def move_track(self, track_id: str, new_index: int) -> None:
        t = self.ws.track(track_id)
        if t is None:
            return
        if self.ws.tracks.index(t) == min(max(new_index, 0), len(self.ws.tracks) - 1):
            return
        self.checkpoint()
        self.ws.move_track(track_id, new_index)
        self.tracksChanged.emit()

    def remove_track(self, track_id: str) -> None:
        if self.ws.track(track_id):
            self.checkpoint()
            self.ws.remove_track(track_id)
            self.tracksChanged.emit()

    def solo_track(self, track_id: str) -> None:
        """Enable only this track for export; unsolo() restores the previous selection."""
        if self.ws.track(track_id) is None:
            return
        self.checkpoint()
        # soloing another track while one is soloed keeps the original selection to restore
        still = self.solo is not None and self.is_soloed(self.solo[0])
        before = self.solo[1] if still else {t.id: t.enabled for t in self.ws.tracks}
        for t in self.ws.tracks:
            t.enabled = t.id == track_id
        self.solo = (track_id, before)
        self.tracksChanged.emit()

    def is_soloed(self, track_id: str) -> bool:
        """True while `track_id` is soloed and its solo hasn't been changed by hand since."""
        if self.solo is None or self.solo[0] != track_id:
            return False
        return all(t.enabled == (t.id == track_id) for t in self.ws.tracks)

    def unsolo(self) -> None:
        """Restore the track selection from before the solo (tracks added since stay enabled)."""
        if self.solo is None:
            return
        self.checkpoint()
        before = self.solo[1]
        for t in self.ws.tracks:
            t.enabled = before.get(t.id, True)
        self.solo = None
        self.tracksChanged.emit()

    def set_all_enabled(self, enabled: bool) -> None:
        self.checkpoint()
        for t in self.ws.tracks:
            t.enabled = enabled
        self.tracksChanged.emit()

    def move_clip(self, track_id: str, clip_id: str, offset: Fraction) -> None:
        """Live clip move within its track (caller checkpoints once at drag start)."""
        self.move_clip_live(clip_id, offset)

    def adopt_tempo(self, source_id: str) -> None:
        if source_id != self.ws.tempo_source_id:
            self.checkpoint()
            self.ws.adopt_tempo_map(source_id)
            self.tempoChanged.emit()
            self.tracksChanged.emit()

    # -- ranges -----------------------------------------------------------------
    def add_range(self, start: Fraction, end: Fraction) -> Range:
        r = Range(start, end)
        self.ws.ranges.append(r)
        if self.export_mode is ExportMode.WHOLE:
            self.export_mode = ExportMode.REBASE
            self.exportSettingsChanged.emit()
        self.selected_range_id = r.id
        self.rangesChanged.emit()
        self.selectionChanged.emit()
        return r

    def update_range(self, range_id: str, start: Fraction | None = None, end: Fraction | None = None,
                     name: str | None = None) -> None:
        r = self.ws.range(range_id)
        if r is None:
            return
        if start is not None:
            r.start = max(start, ZERO)
        if end is not None:
            r.end = max(end, ZERO)
        if r.end < r.start:
            r.start, r.end = r.end, r.start
        if name is not None:
            r.name = name
        self.rangesChanged.emit()

    def delete_range(self, range_id: str | None = None, checkpoint: bool = True) -> None:
        range_id = range_id or self.selected_range_id
        if not range_id or not self.ws.range(range_id):
            return
        if checkpoint:
            self.checkpoint()
        self.ws.ranges = [r for r in self.ws.ranges if r.id != range_id]
        if self.selected_range_id == range_id:
            self.selected_range_id = None
            self.selectionChanged.emit()
        self.rangesChanged.emit()

    def clear_ranges(self) -> None:
        if self.ws.ranges:
            self.checkpoint()
            self.ws.ranges = []
            self.selected_range_id = None
            self.rangesChanged.emit()
            self.selectionChanged.emit()

    def select_range(self, range_id: str | None) -> None:
        if range_id != self.selected_range_id:
            self.selected_range_id = range_id
            self.selectionChanged.emit()

    @property
    def selected_range(self) -> Range | None:
        return self.ws.range(self.selected_range_id) if self.selected_range_id else None

    # -- timing helpers ------------------------------------------------------------
    def snap_time(self, t: Fraction, bypass: bool = False) -> Fraction:
        return self.ws.tempo_map.snap(t, None if bypass else self.snap)

    # -- export ------------------------------------------------------------------
    def set_export_mode(self, mode: ExportMode) -> None:
        if mode is not self.export_mode:
            self.export_mode = mode
            self.exportSettingsChanged.emit()

    def set_trim(self, trim: bool) -> None:
        if trim != self.trim:
            self.trim = trim
            self.exportSettingsChanged.emit()

    def export_options(self, track_ids: list[str] | None = None,
                       range_ids: list[str] | None = None) -> ExportOptions:
        ranges = None if range_ids is None else [r for r in self.ws.ranges if r.id in set(range_ids)]
        return ExportOptions(mode=self.export_mode, track_ids=track_ids, ranges=ranges, trim=self.trim)

    def build_exports(self, track_ids: list[str] | None = None,
                      range_ids: list[str] | None = None) -> list[ExportResult]:
        return build_exports(self.ws, self.export_options(track_ids, range_ids))

    def default_export_name(self, track_ids: list[str] | None = None) -> str:
        tracks = [self.ws.track(i) for i in track_ids] if track_ids else self.ws.enabled_tracks()
        tracks = [t for t in tracks if t]
        if len(tracks) == 1:
            return tracks[0].name
        r = self.selected_range
        if r and r.name and self.export_mode is not ExportMode.WHOLE:
            return r.name
        return "MIDI Interchange Export"
