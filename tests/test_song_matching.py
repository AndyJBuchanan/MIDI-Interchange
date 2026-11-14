"""Name matching with song titles removed (studio round trip, 2026-11-10).

Staccato names every track "part - song" and writes the song as the conductor
track's name. A later generation came back as "Heavy EBM Drums - Staccato
Generation" and failed to land on "Heavy EBM Drums - Industrial EBM Anthem".
The real song is samples/non-synthetic; what Staccato sent back is rebuilt
from it the way Staccato changed it (renamed, Lead dropped, channels moved).
"""
import io
from fractions import Fraction as F
from pathlib import Path

import mido

from helpers import conductor, note, reparse, smf, track

from midi_interchange.core.document import Workspace
from midi_interchange.core.export_smf import ExportMode, ExportOptions, build_exports
from midi_interchange.core.import_smf import import_smf_bytes
from midi_interchange.core.names import song_title
from midi_interchange.core.placement import Placement, place_imports

SONG = Path(__file__).resolve().parent.parent / "samples" / "non-synthetic" / "Industrial EBM Anthem_1793561268176.mid"
OLD, NEW = "Industrial EBM Anthem", "Staccato Generation"


def to_bytes(mf: mido.MidiFile) -> bytes:
    buf = io.BytesIO()
    mf.save(file=buf)
    return buf.getvalue()


def staccato_regeneration() -> bytes:
    """The first set of the song's parts, as a new Staccato generation: renamed to
    the new song, Piercing Lead missing, Pads and Chant moved to ch 2 and 3."""
    mf = mido.MidiFile(str(SONG))
    out = mido.MidiFile(type=1, ticks_per_beat=mf.ticks_per_beat)
    out.tracks.append(mido.MidiTrack(m.copy(name=NEW) if m.type == "track_name" else m for m in mf.tracks[0]))
    for ti, ch in ((1, 9), (2, 0), (4, 1), (5, 2)):
        trk = mido.MidiTrack()
        for m in mf.tracks[ti]:
            if m.type == "track_name":
                m = m.copy(name=m.name.replace(OLD, NEW))
            elif hasattr(m, "channel"):
                m = m.copy(channel=ch)
            trk.append(m)
        out.tracks.append(trk)
    return to_bytes(out)


def song_workspace() -> Workspace:
    ws = Workspace()
    ws.add_import(*import_smf_bytes(SONG.read_bytes(), SONG.name))
    return ws


def parts(*names: str, conductor_name: str | None = None) -> bytes:
    ppq = 480
    cond = conductor(ppq)
    if conductor_name:
        cond.insert(0, mido.MetaMessage("track_name", name=conductor_name, time=0))
    return smf([cond] + [track(note(i, 60 + i, 0, ppq), name=n) for i, n in enumerate(names)], ppq=ppq)


# -- song titles ---------------------------------------------------------------------
def test_song_title_comes_from_the_conductor_track():
    src, _ = import_smf_bytes(SONG.read_bytes(), SONG.name)
    assert src.song == OLD
    src, _ = import_smf_bytes(staccato_regeneration(), "Staccato Generation_1794335906187.mid")
    assert src.song == NEW


def test_song_title_from_an_ending_every_track_shares():
    # a file that lost its conductor name (e.g. an older MIDI Interchange export)
    assert song_title("", ["Drums - Anthem", "Bass - Anthem"]) == "Anthem"
    assert song_title("", ["Drums - Anthem", "Bass - Ballad"]) == ""        # differ: no song
    assert song_title("", ["Lead - Verse"]) == ""                           # one track: never
    assert song_title("", ["Drums - Anthem", "Bass"]) == ""
    assert song_title("Transport", ["Drums - Anthem", "Bass - Anthem"]) == "Anthem"   # Reason-style conductor


# -- matching ------------------------------------------------------------------------
def test_new_staccato_generation_lands_on_the_same_parts():
    """The studio screenshot: dropped on Heavy EBM Drums, all four parts must
    join their existing tracks (the first of each repeated name), none new."""
    ws = song_workspace()
    before = [t.id for t in ws.tracks]
    names = [t.name for t in ws.tracks]
    _, stats = place_imports(ws, [import_smf_bytes(staccato_regeneration(), "Staccato Generation_1.mid")],
                             Placement(F(32), ws.tracks[0].id))
    assert [t.id for t in ws.tracks] == before
    assert stats["new_tracks"] == 0 and stats["onto_existing"] == 4 and stats["by_song"] == 4
    assert set(stats["songs_ignored"]) == {OLD, NEW}
    got = [i for i, t in enumerate(ws.tracks) if len(t.clips) == 2]
    assert got == [0, 1, 3, 4], [names[i] for i in got]            # Drums, Bass, Pads, Chant


def test_exact_names_are_paired_before_song_matches():
    # existing: "Drums - Anthem" (song Anthem) and a plain "Drums" drag
    ws = Workspace()
    ws.add_import(*import_smf_bytes(parts("Drums - Anthem", "Bass - Anthem", conductor_name="Anthem"), "a.mid"))
    ws.add_import(*import_smf_bytes(parts("Drums"), "d.mid"))
    plain = ws.tracks[2]
    # the incoming file has both an exact "Drums" ... and a song-only match
    src = import_smf_bytes(parts("Drums - Ballad", "Drums", conductor_name="Ballad"), "b.mid")
    place_imports(ws, [src], Placement(F(8), plain.id))
    assert len(ws.tracks) == 3
    assert [len(t.clips) for t in ws.tracks] == [2, 1, 2]
    assert plain.clips[-1].name == "Drums"                          # the exact one, not "Drums - Ballad"


def test_section_names_are_not_song_titles():
    """'Lead - Verse' and 'Lead - Chorus' are DAW clips, not songs: no match."""
    ws = Workspace()
    ws.add_import(*import_smf_bytes(parts("Lead - Verse"), "verse.mid"))
    _, stats = place_imports(ws, [import_smf_bytes(parts("Lead - Chorus"), "chorus.mid")],
                             Placement(F(8), ws.tracks[0].id))
    assert len(ws.tracks) == 2 and stats["onto_existing"] == 0


def test_a_different_part_of_the_same_song_does_not_match():
    ws = song_workspace()
    lead = next(t for t in ws.tracks if t.name.startswith("Piercing Lead"))
    _, stats = place_imports(ws, [import_smf_bytes(parts("Mystery Synth - Staccato Generation", "Choir - Staccato Generation",
                                                         conductor_name=NEW), "x.mid")],
                             Placement(F(8), lead.id))
    assert stats["onto_existing"] == 0 and stats["new_tracks"] == 2


# -- export keeps the song --------------------------------------------------------------
def test_export_writes_the_song_title_and_round_trips():
    ws = song_workspace()
    mf = reparse(build_exports(ws, ExportOptions(mode=ExportMode.WHOLE))[0].midi)
    assert [m.name for m in mf.tracks[0] if m.type == "track_name"] == [OLD]
    src, _ = import_smf_bytes(to_bytes(mf), "MIDI Interchange Export.mid")
    assert src.song == OLD


def test_export_of_mixed_songs_writes_no_title():
    ws = song_workspace()
    ws.add_import(*import_smf_bytes(parts("Drums"), "d.mid"))
    mf = reparse(build_exports(ws, ExportOptions(mode=ExportMode.WHOLE))[0].midi)
    assert not [m for m in mf.tracks[0] if m.type == "track_name"]


# -- the real files from the studio (2026-11-10) -----------------------------------------
REAL_GEN = SONG.parent / "Staccato Generation_1794336609801.mid"
CUBASE = SONG.parent.parent / "cubase-check"


def test_real_staccato_generation_matches_on_every_row_it_has():
    """The real new generation (no Piercing Lead) dropped on each row of the song.
    Rows it has: all four parts join their tracks. Piercing Lead rows: no match
    under the cursor, so new tracks (the 2026-11-09 rule)."""
    src, tracks = import_smf_bytes(REAL_GEN.read_bytes(), REAL_GEN.name)
    assert src.song == NEW and len(tracks) == 4
    for lane in range(10):
        ws = song_workspace()
        target = ws.tracks[lane]
        _, stats = place_imports(ws, [import_smf_bytes(REAL_GEN.read_bytes(), REAL_GEN.name)],
                                 Placement(F(8), target.id))
        if target.name.startswith("Piercing Lead"):
            assert stats["onto_existing"] == 0 and stats["new_tracks"] == 4
        else:
            assert stats["onto_existing"] == 4 and stats["new_tracks"] == 0, target.name


def test_real_cubase_section_clips_never_match_by_song():
    for name in ("Lead - Verse.mid", "Lead - Chorus.mid", "Verse.mid", "Chorus.mid"):
        src, _ = import_smf_bytes((CUBASE / name).read_bytes(), name)
        assert src.song == "", name
    ws = Workspace()
    ws.add_import(*import_smf_bytes((CUBASE / "Lead - Verse.mid").read_bytes(), "Lead - Verse.mid"))
    _, stats = place_imports(ws, [import_smf_bytes((CUBASE / "Lead - Chorus.mid").read_bytes(), "Lead - Chorus.mid")],
                             Placement(F(8), ws.tracks[0].id))
    assert stats["onto_existing"] == 0 and len(ws.tracks) == 2


def test_a_drop_that_matches_nothing_says_why(qapp=None):
    """The status bar names the reason, so a failed studio drop explains itself."""
    from midi_interchange.interchange.payload import Payload
    from midi_interchange.ui.controller import Controller
    ctl = Controller()
    msgs: list[str] = []
    ctl.message.connect(msgs.append)
    ctl.import_payloads([Payload(SONG.name, SONG.read_bytes())])
    lead = next(t for t in ctl.ws.tracks if t.name.startswith("Piercing Lead"))
    ctl.import_payloads([Payload(REAL_GEN.name, REAL_GEN.read_bytes())], Placement(F(8), lead.id))
    assert "new because nothing matches “Piercing Lead - Industrial EBM Anthem”" in msgs[-1]
    assert "its song title is “Staccato Generation”" in msgs[-1]
    assert "the track's song title is “Industrial EBM Anthem”" in msgs[-1]


def test_studio_sequence_through_window_drops(qapp=None):
    """The exact studio steps (2026-11-10), with the studio's own files, through the
    window's drag events: Range 1 into empty space, Range 2 onto Heavy EBM Drums at
    bar 9, the new Staccato generation onto Heavy EBM Drums at bar 3. The preview
    must say where it goes, and the parts must land on their tracks."""
    import pytest
    pytest.importorskip("PySide6")
    from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
    from PySide6.QtGui import QDragEnterEvent, QDropEvent
    from PySide6.QtWidgets import QApplication
    from midi_interchange.ui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])
    ranges = SONG.parent.parent / "complex-matching"
    w = MainWindow()
    w.resize(1600, 1000)
    w.show()
    tl = w.timeline

    def drop(path: Path, lane: int, beat: float) -> str:
        tl.set_zoom(25.0, 0)
        tl.horizontalScrollBar().setValue(0)
        tl.verticalScrollBar().setValue(0)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(path))])
        pt = tl.viewport().mapTo(w, QPoint(int(tl.x_of(beat)), tl.header_h() + lane * tl.lane_h + tl.lane_h // 2))
        w.dragEnterEvent(QDragEnterEvent(pt, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
        preview = tl._drop_ind[2]
        w.dropEvent(QDropEvent(QPointF(pt), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
        app.processEvents()
        return preview

    try:
        drop(ranges / "Range 1.mid", 30, 0.1)
        assert len(w.ctl.ws.tracks) == 10
        assert drop(ranges / "Range 2.mid", 0, 32.1).startswith("Onto “Heavy EBM Drums - Industrial EBM Anthem”")
        assert len(w.ctl.ws.tracks) == 10
        preview = drop(REAL_GEN, 0, 8.1)
        assert preview.startswith("Onto “Heavy EBM Drums - Industrial EBM Anthem”"), preview
        assert len(w.ctl.ws.tracks) == 10
        got = [t.name for t in w.ctl.ws.tracks if len(t.clips) == 3]
        assert got == ["Heavy EBM Drums - Industrial EBM Anthem", "Galloping Synth Bass - Industrial EBM Anthem",
                       "Detuned Saw Pads - Industrial EBM Anthem", "Monotone Chant - Industrial EBM Anthem"]
        assert "matched ignoring song titles" in w.statusBar().currentMessage()
    finally:
        w.close()
