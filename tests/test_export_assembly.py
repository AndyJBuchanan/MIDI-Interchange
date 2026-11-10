"""Proof that clips assembled onto one track export as ONE track holding EVERY note.

Each scenario builds the assembly through the same calls the app makes
(drop -> Controller.import_payloads with the drop's Placement; real Option-drags
with QTest; the clip and track menu commands), then exports through the two
user-facing paths:

* **save**: Controller.build_exports + save_exports to disk (what Save MIDI… does);
* **drag**: export_panel.start_file_drag, the Drag MIDI out tile's own function,
  with QDrag.exec stubbed so the test doesn't block, reading the temp files it wrote.

Every file is read back from disk with mido. The expected notes come from the
part definitions in tools/make_assembly_midi.py (pitches unique per part), never
from the workspace model, so the test can't agree with a broken model.
"""
from __future__ import annotations

import os
import sys
from fractions import Fraction as F

import mido
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QDrag  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from helpers import notes_of  # noqa: E402

from midi_interchange.core.export_smf import ExportMode, save_exports  # noqa: E402
from midi_interchange.core.placement import Placement  # noqa: E402
from midi_interchange.core.ranges import Range  # noqa: E402
from midi_interchange.interchange.payload import Payload  # noqa: E402
from midi_interchange.ui.export_panel import start_file_drag  # noqa: E402
from midi_interchange.ui.timeline import HEADER_H  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import make_assembly_midi as gen  # noqa: E402

SAMPLES = os.path.join(ROOT, "samples", "assembly")
A, B, C, D, E, KEYS = ("bass_part_A.mid", "bass_part_B.mid", "bass_part_C_96ppq.mid",
                       "bass_part_D_ch2.mid", "bass_part_E_long.mid", "keys_part.mid")


# -- oracle ---------------------------------------------------------------------------
def part_notes(part: gen.Part, offset) -> list[tuple]:
    off = F(offset)
    return [(off + F(s), off + F(s) + F(d), part.channel, p) for s, d, p in part.notes]


def expected(placed: list[tuple[gen.Part, object]], segs=None) -> list[tuple]:
    """placed: (part, offset beats). segs: [(start, end, dst)] or None for the whole thing."""
    notes = [n for part, off in placed for n in part_notes(part, off)]
    if segs is None:
        return sorted(notes)
    out = []
    for s, e, dst in segs:
        s, e, dst = F(s), F(e), F(dst)
        for ns, ne, ch, p in notes:
            if ne <= s or ns >= e:
                continue
            out.append((max(ns, s) - s + dst, min(ne, e) - s + dst, ch, p))
    return sorted(out)


# -- fixtures and helpers ----------------------------------------------------------------
@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(app):
    from midi_interchange.ui.main_window import MainWindow
    w = MainWindow()
    w.resize(1400, 800)
    w.show()
    QTest.qWaitForWindowExposed(w)
    yield w
    w.close()


def test_committed_samples_match_generator():
    for name, mf in gen.all_files().items():
        on_disk = mido.MidiFile(os.path.join(SAMPLES, name))
        assert on_disk.ticks_per_beat == mf.ticks_per_beat
        assert [list(t) for t in on_disk.tracks] == [list(t) for t in mf.tracks], name


def payload(name: str) -> Payload:
    path = os.path.join(SAMPLES, name)
    with open(path, "rb") as f:
        return Payload(name, f.read(), path=path)


def drop(win, name: str, placement: Placement | None = None) -> None:
    errors = win.ctl.import_payloads([payload(name)], placement or Placement())
    assert not errors, errors
    QApplication.processEvents()


def track_named(win, name):
    hits = [t for t in win.ctl.ws.tracks if t.name == name]
    assert len(hits) == 1, [t.name for t in win.ctl.ws.tracks]
    return hits[0]


def export_save(win, tmp_path, track_ids=None) -> list[mido.MidiFile]:
    results = win.ctl.build_exports(track_ids=track_ids)
    paths = save_exports(results, str(tmp_path / "export.mid"))
    return [mido.MidiFile(p) for p in paths]


def export_drag(win, monkeypatch, track_ids=None) -> list[mido.MidiFile]:
    import tempfile
    from midi_interchange.interchange import drag_export
    monkeypatch.setattr(drag_export, "_DIR", tempfile.mkdtemp(prefix="drag-test-"))   # not the user's drag folder
    urls: list = []
    monkeypatch.setattr(QDrag, "exec", lambda self, *a, **k: urls.extend(self.mimeData().urls()) or Qt.CopyAction)
    done: list = []
    errors: list = []
    start_file_drag(win.export_panel, win.ctl, track_ids, errors.append, done.append)
    assert not errors, errors
    paths = [u.toLocalFile() for u in urls]
    assert paths and paths == done[0]
    return [mido.MidiFile(p) for p in paths]


def assert_single_track(mf: mido.MidiFile, name: str, exp: list[tuple], only: bool) -> None:
    """Exactly one track called `name`, holding exactly `exp` (no stuck notes); its notes nowhere else."""
    named = [t for t in mf.tracks if any(m.type == "track_name" and m.name == name for m in t)]
    assert len(named) == 1, f"{len(named)} tracks named {name!r}"
    got = notes_of(named[0], mf.ticks_per_beat)       # also asserts no stuck / orphan notes
    missing = sorted(set(exp) - set(got))
    extra = sorted(set(got) - set(exp))
    assert got == exp, f"missing {missing[:6]}… ({len(missing)}), extra {extra[:6]}… ({len(extra)})"
    pitches = {n[3] for n in exp}
    for t in mf.tracks:
        if t is not named[0]:
            assert not [n for n in notes_of(t, mf.ticks_per_beat) if n[3] in pitches], "assembled notes leaked"
    if only:
        with_notes = [t for t in mf.tracks if any(m.type == "note_on" for m in t)]
        assert len(mf.tracks) == 2, f"{len(mf.tracks)} tracks in file"
        assert len(with_notes) == (1 if exp else 0)


def set_ranges(win, mode, spans):
    win.ctl.ws.ranges = [Range(F(s), F(e)) for s, e in spans]
    win.ctl.set_export_mode(mode)


# Export cases: (id, mode, range spans, segments per output file)
CASES = [
    ("whole", ExportMode.WHOLE, [], [None]),
    ("rebase-one-range", ExportMode.REBASE, [(6, 30)], [[(6, 30, 0)]]),
    ("rebase-two-ranges", ExportMode.REBASE, [(2, 10), (20, 24)], [[(2, 10, 0), (20, 24, 8)]]),
    ("preserve", ExportMode.PRESERVE, [(6, 30)], [[(6, 30, 6)]]),
    ("separate", ExportMode.SEPARATE, [(2, 10), (20, 24)], [[(2, 10, 0)], [(20, 24, 0)]]),
]


def check_all_cases(win, tmp_path, monkeypatch, name, placed, track_ids=None, only=True):
    for case_id, mode, spans, segs_per_file in CASES:
        set_ranges(win, mode, spans)
        for how in ("save", "drag"):
            files = (export_save(win, tmp_path / f"{case_id}-{how}", track_ids) if how == "save"
                     else export_drag(win, monkeypatch, track_ids))
            assert len(files) == len(segs_per_file), (case_id, how, len(files))
            for mf, segs in zip(files, segs_per_file):
                try:
                    assert_single_track(mf, name, expected(placed, segs), only)
                except AssertionError as exc:
                    raise AssertionError(f"[{case_id} / {how}] {exc}") from exc


@pytest.fixture
def tmpdirs(tmp_path):
    for case_id, *_ in CASES:
        for how in ("save", "drag"):
            (tmp_path / f"{case_id}-{how}").mkdir()
    return tmp_path


def P(name):
    return gen.PARTS[name]


# -- scenarios ---------------------------------------------------------------------------
def test_cubase_workflow_drop_parts_onto_matching_track(win, tmpdirs, monkeypatch):
    """Five Bass parts dropped one by one onto the Bass track at their bars; two overlap;
    one is 96 PPQ, one on channel 2, one has notes crossing the range edges."""
    drop(win, A)
    bass = track_named(win, "Bass")
    for name, at in ((B, 8), (C, 16), (D, 20), (E, 28)):
        drop(win, name, Placement(F(at), bass.id))
    assert len(win.ctl.ws.tracks) == 1 and len(bass.clips) == 5
    placed = [(P(A), 0), (P(B), 8), (P(C), 16), (P(D), 20), (P(E), 28)]
    check_all_cases(win, tmpdirs, monkeypatch, "Bass", placed)


def _lane_y(win, i):
    tl = win.timeline
    return HEADER_H + i * tl.lane_h + tl.lane_h // 2


def _option_drag(win, from_lane, from_beat, to_lane, to_beat, mods=Qt.AltModifier):
    tl = win.timeline
    tl.set_zoom(20.0, 0)
    tl.horizontalScrollBar().setValue(0)
    tl.verticalScrollBar().setValue(0)
    vp = tl.viewport()
    p0 = QPoint(int(tl.x_of(from_beat)), _lane_y(win, from_lane))
    p1 = QPoint(int(tl.x_of(to_beat)), _lane_y(win, to_lane))
    QTest.mousePress(vp, Qt.LeftButton, mods, p0)
    for i in range(1, 9):
        QTest.mouseMove(vp, p0 + (p1 - p0) * i / 8)
    QTest.mouseRelease(vp, Qt.LeftButton, mods, p1)
    QApplication.processEvents()


def test_option_drag_clip_onto_other_track(win, tmpdirs, monkeypatch):
    drop(win, A)
    drop(win, KEYS)
    _option_drag(win, 1, 1.25, 0, 5.25)                 # Keys clip -> Bass lane, 4 beats later
    bass = track_named(win, "Bass")
    assert [t.name for t in win.ctl.ws.tracks] == ["Bass"]
    assert sorted(c.start for c in bass.clips) == [0, 4]   # the gesture did what we think
    check_all_cases(win, tmpdirs, monkeypatch, "Bass", [(P(A), 0), (P(KEYS), 4)])


def test_clip_menu_move_to_track(win, tmpdirs, monkeypatch):
    drop(win, A)
    drop(win, KEYS)
    keys = track_named(win, "Keys")
    win.ctl.move_clip_to_track(keys.clips[0].id, track_named(win, "Bass").id)
    assert [t.name for t in win.ctl.ws.tracks] == ["Bass"]
    check_all_cases(win, tmpdirs, monkeypatch, "Bass", [(P(A), 0), (P(KEYS), 0)])   # full overlap


def test_merge_into(win, tmpdirs, monkeypatch):
    drop(win, A)
    drop(win, KEYS, Placement(F(6)))
    win.ctl.merge_tracks(track_named(win, "Keys").id, track_named(win, "Bass").id)
    assert [t.name for t in win.ctl.ws.tracks] == ["Bass"]
    check_all_cases(win, tmpdirs, monkeypatch, "Bass", [(P(A), 0), (P(KEYS), 6)])


def test_end_to_end_drop(win, tmpdirs, monkeypatch):
    errors = win.ctl.import_payloads([payload(A), payload(C), payload(B)], Placement(end_to_end=True))
    assert not errors
    assert [t.name for t in win.ctl.ws.tracks] == ["Bass"]
    check_all_cases(win, tmpdirs, monkeypatch, "Bass", [(P(A), 0), (P(C), 8), (P(B), 16)])


def test_staccato_song_assemble_two_same_named_tracks(win, tmpdirs, monkeypatch):
    """Multi-track file: the second Bass (channel 5) is Option-Shift-dragged onto the first."""
    drop(win, gen.SONG_FILE)
    assert [t.name for t in win.ctl.ws.tracks] == ["Bass", "Lead", "Bass"]
    _option_drag(win, 2, 1.25, 0, 1.25, Qt.AltModifier | Qt.ShiftModifier)
    assert [t.name for t in win.ctl.ws.tracks] == ["Bass", "Lead"]
    bass1, lead, bass2 = gen.SONG          # file order: Bass, Lead, Bass
    placed = [(bass1, 0), (bass2, 0)]
    # only the assembled track (Save This Track / solo)
    bass = track_named(win, "Bass")
    check_all_cases(win, tmpdirs, monkeypatch, "Bass", placed, track_ids=[bass.id])
    # every enabled track (the drag tile's default): Bass still one track, Lead separate
    check_all_cases(win, tmpdirs, monkeypatch, "Bass", placed, only=False)
    check_all_cases(win, tmpdirs, monkeypatch, "Lead", [(lead, 0)], only=False)


def test_same_pitch_overlap_keeps_every_note_and_no_stuck_notes(win, tmpdirs, monkeypatch):
    """The same part twice, a quarter beat apart: identical pitches overlap."""
    drop(win, A)
    drop(win, A, Placement(F(1, 4), track_named(win, "Bass").id))
    assert len(track_named(win, "Bass").clips) == 2
    check_all_cases(win, tmpdirs, monkeypatch, "Bass", [(P(A), 0), (P(A), F(1, 4))])
