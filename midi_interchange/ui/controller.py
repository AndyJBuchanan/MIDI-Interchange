"""UI-facing owner of the Workspace: mutations, undo/redo, signals."""
from __future__ import annotations

from fractions import Fraction

from PySide6.QtCore import QObject, Signal

from ..core.document import Workspace
from ..core.export_smf import ExportMode, ExportOptions, ExportResult, build_exports
from ..core.import_smf import ImportError_, import_smf_bytes
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
        self.export_mode = ExportMode.WHOLE
        self.trim = False
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
    def import_payloads(self, payloads: list[Payload]) -> list[str]:
        """Import payloads accumulatively. Returns error strings for failures."""
        errors: list[str] = []
        parsed = []
        for p in payloads:
            try:
                parsed.append(import_smf_bytes(p.data, p.name, path=p.path, app=p.app))
            except ImportError_ as exc:
                errors.append(f"{p.name}: {exc}")
        if parsed:
            self.checkpoint()
            had_tempo = self.ws.tempo_source_id
            notes: list[str] = []
            n_tracks = 0
            for source, tracks in parsed:
                notes += self.ws.add_import(source, tracks)
                notes += [f"{source.name}: {w}" for w in source.warnings]
                n_tracks += len(tracks)
            self.tracksChanged.emit()
            if had_tempo != self.ws.tempo_source_id:
                self.tempoChanged.emit()
            summary = f"Imported {len(parsed)} file(s), {n_tracks} track(s)"
            self.message.emit("  ·  ".join([summary, *notes]))
        return errors

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

    def set_all_enabled(self, enabled: bool) -> None:
        self.checkpoint()
        for t in self.ws.tracks:
            t.enabled = enabled
        self.tracksChanged.emit()

    def move_clip(self, track_id: str, clip_id: str, offset: Fraction) -> None:
        """Live clip move (caller checkpoints once at drag start)."""
        t = self.ws.track(track_id)
        clip = next((c for c in t.clips if c.id == clip_id), None) if t else None
        if clip and clip.offset != offset:
            clip.offset = max(offset, ZERO)
            self.tracksChanged.emit()

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
            self.export_mode = ExportMode.PRESERVE
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
