from fractions import Fraction as F

import mido
import pytest

from midi_interchange.core.import_smf import ImportError_, import_smf_bytes

from helpers import cc, conductor, load, note, smf, track


def test_format1_multitrack_conductor_dropped():
    data = smf([conductor(480), track(note(0, 60, 0, 480), "Piano"), track(note(1, 40, 0, 960), "Bass")])
    ws = load(data)
    assert [t.name for t in ws.tracks] == ["Piano", "Bass"]
    assert [t.channels for t in ws.tracks] == [(0,), (1,)]
    assert ws.tempo_map.effective_tempos()[0].bpm == pytest.approx(120)
    # tempo/timesig lifted out of tracks
    for t in ws.tracks:
        assert all(e.msg.type not in ("set_tempo", "time_signature", "track_name") for e in t.clips[0].events)


def test_format0_split_by_channel_with_meta_track():
    ev = note(0, 60, 0, 480) + note(9, 36, 0, 120) + note(0, 62, 480, 480)
    ev += [(0, mido.MetaMessage("set_tempo", tempo=600000)), (240, mido.MetaMessage("lyrics", text="la"))]
    data = smf([track(ev, "Song")], type_=0)
    ws = load(data)
    names = [t.name for t in ws.tracks]
    assert names == ["Song · Ch 1", "Song · Ch 10", "Song · Meta"]
    assert ws.tracks[0].channels == (0,)
    assert ws.tracks[1].channels == (9,)
    assert ws.tracks[2].auxiliary
    assert ws.tempo_map.effective_tempos()[0].us_per_beat == 600000
    # channel and order preserved
    msgs = [e.msg for e in ws.tracks[0].clips[0].events]
    assert [m.note for m in msgs if m.type == "note_on"] == [60, 62]


def test_single_track_file_uses_stem():
    data = smf([track(note(0, 60, 0, 480))])
    ws = load(data, "riff.mid")
    assert ws.tracks[0].name == "riff"


def test_meta_only_track_is_auxiliary():
    lyr = [(0, mido.MetaMessage("lyrics", text="Hello")), (480, mido.MetaMessage("marker", text="A"))]
    ws = load(smf([conductor(480), track(lyr, "Lyrics"), track(note(0, 60, 0, 480), "Vox")]))
    lyrics = ws.tracks[0]
    assert lyrics.name == "Lyrics" and lyrics.auxiliary and lyrics.channels == ()


def test_accumulative_imports_and_color_cycle():
    ws = load(smf([track(note(0, 60, 0, 480), "A")]))
    load(smf([track(note(0, 62, 0, 480), "B"), track(note(1, 30, 0, 480), "C")]), ws=ws)
    assert [t.name for t in ws.tracks] == ["A", "B", "C"]
    assert len(ws.sources) == 2
    assert len({t.color for t in ws.tracks}) == 3


def test_different_ppq_exact_times():
    ws = load(smf([track(note(0, 60, 96, 48), "low")], ppq=96))
    load(smf([track(note(0, 60, 960, 480), "high")], ppq=960), ws=ws)
    a = ws.tracks[0].clips[0].events
    b = ws.tracks[1].clips[0].events
    assert a[0].time == F(1) and a[1].time == F(3, 2)
    assert b[0].time == F(1) and b[1].time == F(3, 2)


def test_end_of_track_sets_clip_length():
    trk = track(note(0, 60, 0, 480), "X")
    trk[-1] = mido.MetaMessage("end_of_track", time=480 * 7)  # end at 8 beats
    ws = load(smf([trk]))
    assert ws.tracks[0].clips[0].length == F(8)


def test_provenance_retained():
    data = smf([conductor(480), track(note(0, 60, 0, 480), "P")])
    src, tracks = import_smf_bytes(data, "p.mid", path="/x/p.mid", app="Cubase")
    assert src.raw == data and src.ppq == 480 and src.smf_format == 1
    assert src.app == "Cubase" and src.path == "/x/p.mid"
    assert src.track_names == ("", "P")
    assert tracks[0].original_name == "P"
    assert "Cubase" in src.describe()


def test_rejects_non_midi():
    with pytest.raises(ImportError_):
        import_smf_bytes(b"RIFF....WAVE", "x.wav")


def test_tempo_conflict_reported_not_merged():
    ws = load(smf([conductor(480, tempos=((0, 100.0),)), track(note(0, 60, 0, 480), "A")]))
    src, tracks = import_smf_bytes(smf([conductor(480, tempos=((0, 140.0),)), track(note(0, 60, 0, 480), "B")]), "b.mid")
    notes = ws.add_import(src, tracks)
    assert notes and "tempo map differs" in notes[0]
    assert ws.tempo_map.effective_tempos()[0].bpm == pytest.approx(100, abs=0.01)
    ws.adopt_tempo_map(src.id)
    assert ws.tempo_map.effective_tempos()[0].bpm == pytest.approx(140, abs=0.01)


def test_controller_events_preserved():
    ws = load(smf([track([(0, cc(3, 7, 99)), (10, cc(3, 64, 127))] + note(3, 60, 0, 100), "C")]))
    types = [(e.msg.type, getattr(e.msg, "control", None)) for e in ws.tracks[0].clips[0].events]
    assert ("control_change", 7) in types and ("control_change", 64) in types
