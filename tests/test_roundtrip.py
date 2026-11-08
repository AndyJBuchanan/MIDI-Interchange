"""Unmodified import -> export must be semantically equivalent."""
from fractions import Fraction as F
from pathlib import Path

import mido
import pytest

from midi_interchange.core.export_smf import build_exports
from midi_interchange.core.import_smf import import_smf_bytes
from midi_interchange.core.document import Workspace

from helpers import abs_events, cc, conductor, load, note, smf, to_bytes, track

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def semantic(data: bytes):
    """Per-musical-track event multiset (time-ordered), plus global tempo map.

    Tracks are keyed by name; conductor/timing events are compared as a map.
    """
    mf = mido.MidiFile(file=__import__("io").BytesIO(data))
    ppq = mf.ticks_per_beat
    tempo, sigs, tracks = [], [], {}
    for i, t in enumerate(mf.tracks):
        name = next((m.name for m in t if m.type == "track_name"), f"#{i}")
        evs = []
        for time, m in abs_events(t, ppq):
            if m.type == "set_tempo":
                tempo.append((time, m.tempo))
            elif m.type == "time_signature":
                sigs.append((time, m.numerator, m.denominator))
            elif m.type not in ("end_of_track", "track_name"):
                evs.append((time, m.copy(time=0).bytes() if not m.is_meta else (m.type, repr(m.copy(time=0)))))
        if evs:
            tracks[name] = evs
    return sorted(tempo), sorted(sigs), tracks


def roundtrip(data: bytes) -> bytes:
    ws = load(data)
    return to_bytes(build_exports(ws)[0].midi)


def rich_file(ppq=480) -> bytes:
    ev = note(0, 60, 0, ppq) + note(0, 64, 0, ppq) + [(0, cc(0, 7, 100)), (ppq // 3, cc(0, 1, 64))]
    ev += [(ppq, mido.Message("pitchwheel", channel=0, pitch=-2000)),
           (ppq, mido.Message("aftertouch", channel=0, value=30)),
           (ppq, mido.Message("polytouch", channel=0, note=60, value=20)),
           (0, mido.Message("program_change", channel=0, program=5)),
           (ppq * 2, mido.Message("sysex", data=[0x41, 0x10, 0x42, 0x12])),
           (ppq * 2, mido.MetaMessage("lyrics", text="caf\xc3\xa9")),  # UTF-8 bytes as latin-1
           (ppq * 2, mido.MetaMessage("text", text="hello")),
           (ppq * 3, mido.MetaMessage("marker", text="Chorus")),
           (ppq * 3, mido.MetaMessage("cue_marker", text="cue")),
           (0, mido.MetaMessage("key_signature", key="Eb")),
           (ppq * 3, mido.UnknownMetaMessage(type_byte=0x60, data=(1, 2, 3))),
           (ppq * 3, mido.MetaMessage("sequencer_specific", data=(0x43, 0x7B))),
           ]
    ev += note(0, 60, ppq // 2, ppq)  # overlapping same pitch
    return smf([conductor(ppq, tempos=((0, 90.0), (ppq * 2, 120.0)), sigs=((0, 4, 4), (ppq * 4, 3, 4))),
                track(ev, "Rich"), track(note(9, 36, 0, 10), "Drums")], ppq=ppq)


@pytest.mark.parametrize("ppq", [96, 480, 960, 1000])
def test_rich_roundtrip(ppq):
    data = rich_file(ppq)
    assert semantic(roundtrip(data)) == semantic(data)


def test_double_roundtrip_is_stable():
    once = roundtrip(rich_file())
    twice = roundtrip(once)
    assert once == twice


def test_mixed_ppq_export_is_exact():
    ws = load(smf([track(note(0, 60, 1, 1), "a")], ppq=96))  # 1/96 quarter
    load(smf([track(note(0, 60, 1, 1), "b")], ppq=120), ws=ws)  # 1/120 quarter
    mf = build_exports(ws)[0].midi
    assert mf.ticks_per_beat == 480  # lcm(96, 120)
    ppq = mf.ticks_per_beat
    a = [t for t, m in abs_events(mf.tracks[1], ppq) if m.type.startswith("note")]
    b = [t for t, m in abs_events(mf.tracks[2], ppq) if m.type.startswith("note")]
    assert a == [F(1, 96), F(2, 96)] and b == [F(1, 120), F(2, 120)]


def test_format0_roundtrip_semantics():
    ev = note(0, 60, 0, 480) + note(9, 36, 0, 120) + [(5, mido.MetaMessage("lyrics", text="x"))]
    data = smf([track(ev, "Song")], type_=0)
    out = mido.MidiFile(file=__import__("io").BytesIO(roundtrip(data)))
    all_events = sorted((t, m.bytes()) for trk in out.tracks for t, m in abs_events(trk, out.ticks_per_beat)
                        if not m.is_meta)
    orig = mido.MidiFile(file=__import__("io").BytesIO(data))
    orig_events = sorted((t, m.bytes()) for trk in orig.tracks for t, m in abs_events(trk, orig.ticks_per_beat)
                         if not m.is_meta)
    assert all_events == orig_events


@pytest.mark.parametrize("path", sorted(SAMPLES.glob("*.mid")), ids=lambda p: p.name)
def test_sample_files_roundtrip(path):
    data = path.read_bytes()
    out = roundtrip(data)
    s_in, s_out = semantic(data), semantic(out)
    assert s_out[0] == s_in[0] or not s_in[0]
    assert sorted(sum(s_out[2].values(), []), key=repr) == sorted(sum(s_in[2].values(), []), key=repr)


def test_renamed_track_written_utf8_and_unchanged_name_kept():
    data = smf([track(note(0, 60, 0, 480), "Caf\xe9"), track(note(1, 60, 0, 480), "Bass")])  # latin-1 é
    ws = load(data)
    assert ws.tracks[0].name == "Caf\xe9"
    ws.tracks[1].name = "ベース"
    mf = build_exports(ws)[0].midi
    names = [m.name for t in mf.tracks for m in t if m.type == "track_name"]
    assert names[0] == "Caf\xe9"  # original bytes kept
    assert names[1].encode("latin-1").decode("utf-8") == "ベース"


def test_export_does_not_mutate_workspace():
    ws = load(rich_file())
    before = ws.snapshot()
    build_exports(ws)
    assert [t.clips[0].events for t in ws.tracks] == [t.clips[0].events for t in before["tracks"]]
