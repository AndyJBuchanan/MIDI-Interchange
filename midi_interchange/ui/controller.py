"""UI-facing owner of the Workspace: mutations, undo/redo, signals."""
from __future__ import annotations

from fractions import Fraction

from PySide6.QtCore import QObject, Signal

from ..core import controllers as ctlr
from ..core.document import Track, Workspace
from ..core.export_smf import (ExportMode, ExportOptions, ExportResult, build_exports, export_name,
                               export_tracks)
from ..core.import_smf import ImportError_
from ..interchange.readers import read_payload
from ..core.mirror import carry_over
from ..core.names import quoted
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
    controllerViewChanged = Signal()   # the picker, mode or style (view state: no undo step)
    mirrorChanged = Signal()           # mirror mode entered or left
    message = Signal(str)

    UNDO_LIMIT = 200

    def __init__(self) -> None:
        super().__init__()
        self.ws = Workspace()
        self.selected_range_id: str | None = None
        self.snap: SnapSetting = "beat"
        self.export_mode = ExportMode.REBASE   # default (2026-11-10); with no ranges, export is whole
        self.trim = False
        self.simplify_controllers = False
        # Controller display (view state, like zoom and Show Markers: never undoable).
        self.controller_show: str | None = None      # the picker; None is Off
        self.controller_overlay = False              # Lane (False) or Overlay
        self.controller_joined = False               # Steps (False) or Joined lines
        self._clip_controllers: dict[str, tuple] = {}
        self.mirroring = False         # mirror mode: every edit is refused (docs/plans/mirror-mode.md)
        self._file_ms: dict[str, tuple[bool, bool]] = {}   # mirroring: each track's (muted, soloed) as the file last saved them
        self.file_drag_active = False  # transient native drag-out; never checkpoint mid-drag
        self._undo: list[tuple[dict, str | None]] = []
        self._redo: list[tuple[dict, str | None]] = []

    # -- undo --------------------------------------------------------------
    def _blocked(self, what: str = "edit") -> bool:
        """The mirror-mode backstop: while mirroring, editing methods return without changing anything."""
        if not self.mirroring:
            return False
        self.message.emit("Mirroring: unmirror to import" if what == "import"
                          else "Mirroring: read-only (unmirror to edit)")
        return True

    def checkpoint(self) -> None:
        if self.mirroring:
            return                       # mirror mode makes no undo steps
        self._undo.append((self.ws.snapshot(), self.selected_range_id))
        del self._undo[:-self.UNDO_LIMIT]
        self._redo.clear()
        self.undoStateChanged.emit()

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> None:
        if self._undo and not self.mirroring:
            self._redo.append((self.ws.snapshot(), self.selected_range_id))
            snap, sel = self._undo.pop()
            self._apply(snap, sel)

    def redo(self) -> None:
        if self._redo and not self.mirroring:
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

    # -- mirror mode ----------------------------------------------------------
    def enter_mirror(self, result) -> None:
        """Mirroring owns the workspace: clear it and import the file at bar 1 as new tracks.
        No undo step (unmirroring starts a clean history)."""
        self.mirroring = True
        self._undo.clear()
        self._redo.clear()
        self.ws.clear()
        self.selected_range_id = None
        notes, _stats = place_imports(self.ws, [result], Placement())
        self._file_ms = {t.id: (t.muted, t.soloed) for t in self.ws.tracks}
        self._clip_controllers.clear()
        self.tracksChanged.emit()
        self.tempoChanged.emit()
        self.rangesChanged.emit()
        self.selectionChanged.emit()
        self.undoStateChanged.emit()
        self.mirrorChanged.emit()
        for n in [*notes, *(f"{result.source.name}: {w}" for w in result.source.warnings)]:
            self.message.emit(n)

    def apply_mirror(self, result) -> dict:
        """A re-import of the mirrored file (no undo step). Returns carry_over's counts."""
        snap, counts, self._file_ms = carry_over(self.ws, result, self._file_ms)
        self.ws.restore(snap)
        if not self.ws.range(self.selected_range_id or ""):
            self.selected_range_id = None
        self.tracksChanged.emit()
        self.tempoChanged.emit()
        self.rangesChanged.emit()
        self.selectionChanged.emit()
        return counts

    def leave_mirror(self) -> None:
        """Unmirror: the workspace stays as it is; undo and redo start clean."""
        self.mirroring = False
        self._file_ms = {}
        self._undo.clear()
        self._redo.clear()
        self.undoStateChanged.emit()
        self.mirrorChanged.emit()

    def ms_differs(self, track_id: str | None = None) -> bool:
        """While mirroring: does this track (or any track) differ in mute or solo from what the file last saved?"""
        if not self.mirroring:
            return False
        tracks = self.ws.tracks if track_id is None else [t for t in self.ws.tracks if t.id == track_id]
        return any((t.muted, t.soloed) != self._file_ms.get(t.id, (t.muted, t.soloed)) for t in tracks)

    def ms_note(self, track_id: str) -> str:
        """For the marker's tooltip: how this track differs from what the file last saved."""
        def words(muted: bool, soloed: bool) -> str:
            return "soloed" if soloed else "muted" if muted else "not muted or soloed"
        t = self.ws.track(track_id)
        if t is None or track_id not in self._file_ms:
            return ""
        return (f"Differs from the file: here it is {words(t.muted, t.soloed)}, the file saved it "
                f"{words(*self._file_ms[track_id])}.\nRight-click the track and choose Follow File's Mute/Solo to match.")

    def sync_mutes(self, track_id: str | None = None) -> None:
        """Mirroring: put this track (or every track) back to the file's mute and solo. No undo step."""
        if not self.ms_differs(track_id):
            return
        for t in self.ws.tracks:
            if track_id in (None, t.id) and t.id in self._file_ms:
                t.muted, t.soloed = self._file_ms[t.id]
        self._ms_changed()

    def restore_session(self, snap: dict, selection: str | None) -> None:
        """Apply validated persistent state using the same refresh path as undo."""
        self._undo.clear()
        self._redo.clear()
        self._apply(snap, selection)

    # -- import ---------------------------------------------------------------
    def parse_payloads(self, payloads: list[Payload]) -> tuple[list, list[str]]:
        parsed, errors = [], []
        for p in payloads:
            try:
                parsed.append(read_payload(p))
            except ImportError_ as exc:
                errors.append(f"{p.name}: {exc}")
        return parsed, errors

    def import_payloads(self, payloads: list[Payload], placement: Placement | None = None) -> list[str]:
        """Import payloads accumulatively. Returns error strings for failures."""
        if self._blocked("import"):
            return []
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
                parts.append(f"{stats['onto_existing']} onto existing {quoted(stats['onto_names'], None)}")
            if stats["by_song"]:
                songs = quoted(stats["songs_ignored"], None)
                word = "title" if len(stats["songs_ignored"]) == 1 else "titles"
                parts.append(f"{stats['by_song']} matched ignoring song {word} {songs}")
            if stats["no_match"]:
                parts.append(f"new because {stats['no_match']}")
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
        if self._blocked() or not (self.ws.tracks or self.ws.ranges or self.ws.sources):
            return
        self.checkpoint()
        self.ws.clear()
        self.selected_range_id = None
        self.tracksChanged.emit()
        self.tempoChanged.emit()
        self.rangesChanged.emit()
        self.selectionChanged.emit()
        self.message.emit("New workspace (Undo brings the previous one back)")

    # -- clips -------------------------------------------------------------
    def move_clip_live(self, clip_id: str, offset: Fraction, track_id: str | None = None) -> None:
        """Live clip move during a drag (caller checkpoints once at drag start)."""
        if self._blocked():
            return
        found = self.ws.find_clip(clip_id)
        if found is None:
            return
        src, clip = found
        offset = max(offset, ZERO)
        dest = track_id or src.id
        if offset != clip.start or dest != src.id:
            self.ws.move_clip_to_track(clip_id, dest, offset)
            self.tracksChanged.emit()

    def trim_clip_live(self, clip_id: str, edge: str, time: Fraction, bypass_snap: bool = False) -> None:
        """Live edge trim during a drag (caller checkpoints once at drag start).
        The edge snaps like a clip move; Shift bypasses. It stays within the
        clip's full extent and keeps a minimum length of one snap step (one
        tick when the snap is bypassed or off)."""
        if self._blocked():
            return
        found = self.ws.find_clip(clip_id)
        if found is None:
            return
        _track, clip = found
        time = self.snap_time(time, bypass_snap)
        if self.ws.trim_clip(clip_id, edge, time, self._min_trim(clip, bypass_snap)):
            self.tracksChanged.emit()

    def trim_can_move(self, clip_id: str, edge: str, direction: int, bypass_snap: bool = False) -> bool:
        """Whether a trim drag's edge can still move that way (the workspace owns the limits)."""
        found = self.ws.find_clip(clip_id)
        if found is None:
            return False
        return self.ws.can_trim_move(clip_id, edge, direction, self._min_trim(found[1], bypass_snap))

    def _min_trim(self, clip, bypass_snap: bool) -> Fraction | None:
        """Smallest clip length a trim may leave (None: one tick)."""
        setting = None if bypass_snap else self.snap
        if setting is None:
            return None
        tm = self.ws.tempo_map
        ts = tm.timesig_at(clip.start)
        return ts.bar_length if setting == "bar" else ts.beat_length if setting == "beat" else Fraction(setting)

    def split_position(self, clip_id: str, time: Fraction,
                       bypass_snap: bool = False) -> Fraction | None:
        """Shared snapped/validated position for preview and execution."""
        found = self.ws.find_clip(clip_id)
        if found is None:
            return None
        time = self.snap_time(time, bypass_snap)
        return time if self.ws.can_split_clip(clip_id, time, self._min_trim(found[1], bypass_snap)) else None

    def split_clip(self, clip_id: str, time: Fraction, bypass_snap: bool = False) -> str | None:
        if self._blocked():
            return
        time = self.split_position(clip_id, time, bypass_snap)
        if time is None:
            return None
        clip = self.ws.find_clip(clip_id)[1]
        self.checkpoint()
        right = self.ws.split_clip(clip_id, time, self._min_trim(clip, bypass_snap))
        self.tracksChanged.emit()
        return right.id

    def toggle_clip_mute(self, clip_id: str) -> None:
        if self._blocked():
            return
        found = self.ws.find_clip(clip_id)
        if found is None:
            return
        self.checkpoint()
        found[1].muted = not found[1].muted
        self.tracksChanged.emit()

    def restore_clip(self, clip_id: str) -> None:
        """Menu command: put a trimmed clip's edges back to its full extent."""
        if self._blocked():
            return
        found = self.ws.find_clip(clip_id)
        if found is None or not found[1].is_trimmed:
            return
        self.checkpoint()
        self.ws.restore_clip(clip_id)
        self.tracksChanged.emit()

    def end_clip_gesture(self) -> None:
        if self.ws.remove_empty_tracks():
            self.tracksChanged.emit()

    def move_clip_to_track(self, clip_id: str, track_id: str | None) -> None:
        """Menu command: move to another track, or to a new track when track_id is None."""
        if self._blocked():
            return
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
        if self._blocked():
            return
        if self.ws.find_clip(clip_id):
            self.checkpoint()
            self.ws.delete_clip(clip_id)
            self.tracksChanged.emit()

    def duplicate_clip(self, clip_id: str, offset: Fraction | None = None,
                       track_id: str | None = None, checkpoint: bool = True) -> str | None:
        if self._blocked():
            return
        if not self.ws.find_clip(clip_id):
            return None
        if checkpoint:
            self.checkpoint()
        dup = self.ws.duplicate_clip(clip_id, offset, track_id)
        self.tracksChanged.emit()
        return dup.id if dup else None

    def snap_clip_to_previous(self, clip_id: str) -> None:
        if self._blocked():
            return
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
        if self._blocked():
            return
        if self.ws.track(from_id) and self.ws.track(into_id) and from_id != into_id:
            self.checkpoint()
            self.ws.merge_tracks(from_id, into_id)
            self.tracksChanged.emit()

    # -- tracks --------------------------------------------------------------
    def _ms_changed(self) -> None:
        self.ws.sync_ranges()
        self.tracksChanged.emit()
        self.rangesChanged.emit()

    def set_mute(self, track_id: str, muted: bool, all_tracks: bool = False) -> None:
        track = self.ws.track(track_id)
        if track is None:
            return
        targets = self.ws.tracks if all_tracks else [track]
        if not any(t.muted != muted or (muted and t.soloed) for t in targets):
            return
        self.checkpoint()
        for t in targets:
            t.muted = muted
            if muted:
                t.soloed = False
        self._ms_changed()

    def toggle_solo(self, track_id: str, exclusive: bool = False) -> None:
        track = self.ws.track(track_id)
        if track is None:
            return
        sole = track.soloed and sum(t.soloed for t in self.ws.tracks) == 1
        on = not sole if exclusive else not track.soloed
        self.checkpoint()
        if exclusive:
            for t in self.ws.tracks:
                t.soloed = False
        track.soloed = on
        self._ms_changed()

    def solo_source_tracks(self, source_id: str) -> None:
        """Exclusively solo the tracks holding clips from a source (one undo step; none if already so)."""
        targets = {t.id for t in self.ws.tracks if any(c.source_id == source_id for c in t.clips)}
        if not targets or targets == {t.id for t in self.ws.tracks if t.soloed}:
            return
        self.checkpoint()
        for t in self.ws.tracks:
            t.soloed = t.id in targets
        self._ms_changed()

    def clear_mutes(self) -> None:
        if any(t.muted for t in self.ws.tracks):
            self.checkpoint()
            for t in self.ws.tracks:
                t.muted = False
            self._ms_changed()

    def clear_solos(self) -> None:
        if any(t.soloed for t in self.ws.tracks):
            self.checkpoint()
            for t in self.ws.tracks:
                t.soloed = False
            self._ms_changed()

    def rename_track(self, track_id: str, name: str) -> None:
        if self._blocked():
            return
        t = self.ws.track(track_id)
        name = name.strip()
        if t and name and t.name != name:
            self.checkpoint()
            t.name = name
            self.tracksChanged.emit()

    def set_export_channel(self, track_id: str, channel: int | None) -> None:
        if self._blocked():
            return
        if channel is not None and (type(channel) is not int or not 1 <= channel <= 16):
            raise ValueError("Export channel must be Original channels or 1–16")
        track = self.ws.track(track_id)
        if track is not None and track.export_channel != channel:
            self.checkpoint()
            track.export_channel = channel
            self.tracksChanged.emit()

    # -- controller display ----------------------------------------------------
    def set_track_controller(self, track_id: str, value: str | None) -> None:
        """A track's own controller: None follows the view, "none" shows nothing, else a key.

        A display choice, so it's allowed while mirroring (carry_over keeps it across re-imports)."""
        if value is not None and value != "none" and not ctlr.is_valid_key(value):
            raise ValueError("Track controller must be None, 'none' or a controller key")
        track = self.ws.track(track_id)
        if track is not None and track.controller != value:
            self.checkpoint()
            track.controller = value
            self.tracksChanged.emit()

    def set_controller_show(self, key: str | None) -> None:
        if key is not None and not ctlr.is_valid_key(key):
            raise ValueError("Not a controller key")
        if key != self.controller_show:
            self.controller_show = key
            self.controllerViewChanged.emit()

    def set_controller_overlay(self, on: bool) -> None:
        if on != self.controller_overlay:
            self.controller_overlay = on
            self.controllerViewChanged.emit()

    def set_controller_joined(self, on: bool) -> None:
        if on != self.controller_joined:
            self.controller_joined = on
            self.controllerViewChanged.emit()

    def shown_controller(self, track: Track) -> str | None:
        """The key a track displays: its own choice, or the view's."""
        if track.controller is None:
            return self.controller_show
        return None if track.controller == "none" else track.controller

    def controller_active(self) -> bool:
        """Whether anything is shown: the picker is not Off, or a track overrides it with a controller."""
        return self.controller_show is not None or any(
            t.controller not in (None, "none") for t in self.ws.tracks)

    def clip_controller_keys(self, clip) -> frozenset[str]:
        """The keys a clip shows (cached per clip; events are shared and never mutated)."""
        stamp = (clip.trim_start, clip.trim_end, clip.length)
        entry = self._clip_controllers.get(clip.id)
        if entry is None or entry[0] is not clip.events or entry[1] != stamp:
            entry = self._clip_controllers[clip.id] = (clip.events, stamp, frozenset(ctlr.clip_controllers(clip)))
        return entry[2]

    def track_controllers(self, track: Track) -> list[str]:
        """The controllers a track has, in picker order."""
        found = set()
        for clip in track.clips:
            found |= self.clip_controller_keys(clip)
        return sorted(found, key=ctlr.sort_key)

    def workspace_controllers(self) -> list[str]:
        """The union over every track and clip (muted ones too), in picker order."""
        live = {c.id for t in self.ws.tracks for c in t.clips}
        for cid in list(self._clip_controllers):
            if cid not in live:
                del self._clip_controllers[cid]
        found = set()
        for t in self.ws.tracks:
            found.update(self.track_controllers(t))
        return sorted(found, key=ctlr.sort_key)

    def set_track_color(self, track_id: str, color: str) -> None:
        if self._blocked():
            return
        t = self.ws.track(track_id)
        if t and t.color != color:
            self.checkpoint()
            t.color = color
            self.tracksChanged.emit()

    def move_track(self, track_id: str, new_index: int) -> None:
        if self._blocked():
            return
        t = self.ws.track(track_id)
        if t is None:
            return
        if self.ws.tracks.index(t) == min(max(new_index, 0), len(self.ws.tracks) - 1):
            return
        self.checkpoint()
        self.ws.move_track(track_id, new_index)
        self.tracksChanged.emit()

    def remove_track(self, track_id: str) -> None:
        if self._blocked():
            return
        if self.ws.track(track_id):
            self.checkpoint()
            self.ws.remove_track(track_id)
            self.tracksChanged.emit()

    def move_clip(self, track_id: str, clip_id: str, offset: Fraction) -> None:
        """Live clip move within its track (caller checkpoints once at drag start)."""
        self.move_clip_live(clip_id, offset)

    def adopt_tempo(self, source_id: str) -> None:
        if self._blocked():
            return
        if source_id != self.ws.tempo_source_id:
            self.checkpoint()
            self.ws.adopt_tempo_map(source_id)
            self.tempoChanged.emit()
            self.tracksChanged.emit()

    # -- ranges -----------------------------------------------------------------
    def add_range(self, start: Fraction, end: Fraction) -> Range:
        r = Range(start, end, excluded={t.id for t in self.ws.tracks if t not in self.ws.global_tracks()})
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

    def set_range_track_included(self, range_id: str, track_id: str, included: bool) -> None:
        """Include/exclude one track in one range (the range's toggle wins over the track's)."""
        r = self.ws.range(range_id)
        if r is None or not r.track_locked or self.ws.track(track_id) is None or r.includes(track_id) == included:
            return
        self.checkpoint()
        r.set_included(track_id, included)
        self.rangesChanged.emit()

    def set_range_locked(self, range_id: str, locked: bool) -> None:
        r = self.ws.range(range_id)
        if r is None or r.track_locked == locked:
            return
        self.checkpoint()
        r.track_locked = locked
        self.ws.sync_ranges()
        self.rangesChanged.emit()

    def set_range_tracks(self, range_id: str, included: bool | None) -> None:
        r = self.ws.range(range_id)
        if r is None:
            return
        if included is None:
            self.set_range_locked(range_id, False)
            return
        if r.track_locked and all(r.includes(t.id) == included for t in self.ws.tracks):
            return
        self.checkpoint()
        r.track_locked = True
        for t in self.ws.tracks:
            r.set_included(t.id, included)
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

    def set_simplify_controllers(self, on: bool) -> None:
        if on != self.simplify_controllers:
            self.simplify_controllers = on
            self.exportSettingsChanged.emit()

    def export_options(self, track_ids: list[str] | None = None,
                       range_ids: list[str] | None = None) -> ExportOptions:
        ranges = None if range_ids is None else [r for r in self.ws.ranges if r.id in set(range_ids)]
        return ExportOptions(mode=self.export_mode, track_ids=track_ids, ranges=ranges, trim=self.trim,
                             simplify_controllers=self.simplify_controllers)

    def build_exports(self, track_ids: list[str] | None = None,
                      range_ids: list[str] | None = None) -> list[ExportResult]:
        return build_exports(self.ws, self.export_options(track_ids, range_ids))

    def export_tracks(self, track_ids: list[str] | None = None) -> list[Track]:
        """The tracks an export would contain: track toggles for a whole
        export, range toggles when exporting ranges."""
        ranges = self.ws.ranges if self.ws.ranges and self.export_mode is not ExportMode.WHOLE else None
        return export_tracks(self.ws, track_ids, ranges)

    def default_export_name(self, track_ids: list[str] | None = None) -> str:
        ranges = None if self.export_mode is ExportMode.WHOLE or not self.ws.ranges else self.ws.ranges
        return export_name(self.export_tracks(track_ids), ranges)
