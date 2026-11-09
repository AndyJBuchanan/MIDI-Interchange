"""Range export, boundary handling, modes, trim, track selection."""
import os
from fractions import Fraction as F

import mido

from midi_interchange.core.export_smf import ExportMode, ExportOptions, build_exports, choose_ppq, save_exports
from midi_interchange.core.ranges import Range, merge_ranges

from helpers import abs_events, cc, conductor, load, note, notes_of, on, off, smf, track, track_by_name

PPQ = 480
Q = PPQ  # one quarter in ticks


def export(ws, mode, ranges, **kw):
    res = build_exports(ws, ExportOptions(mode=mode, ranges=ranges, **kw))
    return [r.midi for r in res]


def basic_ws():
    ev = []
    ev += note(0, 60, 0, Q)              # [0,1)
    ev += note(0, 62, 3 * Q, 3 * Q)      # [3,6) crosses start of [4,8)
    ev += note(0, 64, 5 * Q, Q)          # [5,6) inside
    ev += note(0, 65, 7 * Q, 2 * Q)      # [7,9) crosses end
    ev += note(0, 67, 2 * Q, 10 * Q)     # [2,12) crosses both
    return load(smf([conductor(PPQ), track(ev, "Keys")]))


def test_boundary_clipping_preserve():
    ws = basic_ws()
    mf, = export(ws, ExportMode.PRESERVE, [Range(F(4), F(8))])
    notes = notes_of(track_by_name(mf, "Keys"), mf.ticks_per_beat)
    assert notes == [
        (F(4), F(6), 0, 62),
        (F(4), F(8), 0, 67),
        (F(5), F(6), 0, 64),
        (F(7), F(8), 0, 65),
    ]


def test_boundary_clipping_rebase():
    ws = basic_ws()
    mf, = export(ws, ExportMode.REBASE, [Range(F(4), F(8))])
    notes = notes_of(track_by_name(mf, "Keys"), mf.ticks_per_beat)
    assert notes == [(F(0), F(2), 0, 62), (F(0), F(4), 0, 67), (F(1), F(2), 0, 64), (F(3), F(4), 0, 65)]
    eot = abs_events(track_by_name(mf, "Keys"), mf.ticks_per_beat)[-1]
    assert eot[1].type == "end_of_track" and eot[0] == F(4)  # loop length preserved


def test_partial_notes_can_be_excluded():
    ws = basic_ws()
    mf, = export(ws, ExportMode.REBASE, [Range(F(4), F(8))], partial_notes=False)
    notes = notes_of(track_by_name(mf, "Keys"), mf.ticks_per_beat)
    assert [n[3] for n in notes] == [64, 65]


def test_overlapping_same_pitch_fifo_no_stuck_notes():
    ev = [(0, on(0, 60)), (Q, on(0, 60)), (2 * Q, off(0, 60)), (3 * Q, off(0, 60))]
    ws = load(smf([track(ev, "Ov")]))
    mf, = export(ws, ExportMode.REBASE, [Range(F(1, 2), F(5, 2))])
    notes = notes_of(track_by_name(mf, "Ov"), mf.ticks_per_beat)
    assert notes == [(F(0), F(3, 2), 0, 60), (F(1, 2), F(2), 0, 60)]


def test_unterminated_note_closed_at_clip_end_or_range_end():
    ev = [(0, on(0, 50))] + note(0, 52, Q, Q)  # source track ends at beat 2
    ws = load(smf([track(ev, "Hang")]))
    mf, = export(ws, ExportMode.REBASE, [Range(F(0), F(4))])
    assert (F(0), F(2), 0, 50) in notes_of(track_by_name(mf, "Hang"), mf.ticks_per_beat)
    mf, = export(ws, ExportMode.REBASE, [Range(F(0), F(1))])
    assert (F(0), F(1), 0, 50) in notes_of(track_by_name(mf, "Hang"), mf.ticks_per_beat)


def test_controller_state_carried_in_original_order():
    ev = [(0, cc(0, 0, 1)), (1, cc(0, 32, 2)), (2, mido.Message("program_change", channel=0, program=10)),
          (Q, cc(0, 7, 90)), (2 * Q, cc(0, 7, 70)), (2 * Q, cc(0, 64, 127)),
          (2 * Q, mido.Message("pitchwheel", channel=0, pitch=500)),
          (2 * Q, cc(0, 123, 0)),  # all notes off: must NOT be carried
          (Q, mido.MetaMessage("key_signature", key="D"))]
    ev += note(0, 60, 5 * Q, Q)
    ws = load(smf([track(ev, "St")]))
    mf, = export(ws, ExportMode.REBASE, [Range(F(4), F(8))])
    evs = [(t, m) for t, m in abs_events(track_by_name(mf, "St"), mf.ticks_per_beat)
           if m.type not in ("track_name", "end_of_track")]
    at0 = [m for t, m in evs if t == 0]
    kinds = [(m.type, getattr(m, "control", None)) for m in at0]
    assert kinds == [("control_change", 0), ("control_change", 32), ("program_change", None),
                     ("key_signature", None), ("control_change", 7), ("control_change", 64),
                     ("pitchwheel", None)]
    assert [m.value for m in at0 if m.type == "control_change" and m.control == 7] == [70]
    assert not any(m.type == "control_change" and m.control == 123 for _, m in evs)


def test_tempo_and_timesig_state_at_range_start():
    cond = conductor(PPQ, tempos=((0, 100.0), (6 * Q, 140.0)), sigs=((0, 4, 4), (4 * Q, 3, 4)))
    ws = load(smf([cond, track(note(0, 60, 0, 12 * Q), "N")]))
    mf, = export(ws, ExportMode.REBASE, [Range(F(5), F(9))])
    c = abs_events(mf.tracks[0], mf.ticks_per_beat)
    tempos = [(t, round(mido.tempo2bpm(m.tempo))) for t, m in c if m.type == "set_tempo"]
    sigs = [(t, m.numerator, m.denominator) for t, m in c if m.type == "time_signature"]
    assert tempos == [(F(0), 100), (F(1), 140)]
    assert sigs == [(F(0), 3, 4)]


def test_lyrics_and_meta_in_range_only():
    lyr = [(i * Q, mido.MetaMessage("lyrics", text=w)) for i, w in enumerate("a b c d e f".split())]
    lyr += [(2 * Q, mido.Message("sysex", data=[1, 2])), (3 * Q, mido.UnknownMetaMessage(type_byte=0x60, data=(9,)))]
    ws = load(smf([track(lyr, "Lyr")]))
    mf, = export(ws, ExportMode.REBASE, [Range(F(2), F(4))])
    evs = abs_events(track_by_name(mf, "Lyr"), mf.ticks_per_beat)
    assert [(t, m.text) for t, m in evs if m.type == "lyrics"] == [(F(0), "c"), (F(1), "d")]
    assert any(m.type == "sysex" and t == 0 for t, m in evs)
    assert any(isinstance(m, mido.UnknownMetaMessage) and t == 1 for t, m in evs)


def test_half_open_boundary():
    ev = note(0, 60, 4 * Q, Q) + note(0, 61, 3 * Q, Q)  # one starts at end of range, one ends at start
    ws = load(smf([track(ev, "H")]))
    mf, = export(ws, ExportMode.PRESERVE, [Range(F(0), F(4))])
    notes = notes_of(track_by_name(mf, "H"), mf.ticks_per_beat)
    assert notes == [(F(3), F(4), 0, 61)]


def test_multiple_disjoint_ranges_preserve_and_merge():
    ws = basic_ws()
    assert merge_ranges([Range(F(4), F(6)), Range(F(0), F(1)), Range(F(6), F(8))]) == [(0, 1), (4, 8)]
    mf, = export(ws, ExportMode.PRESERVE, [Range(F(0), F(1)), Range(F(10), F(11))])
    notes = notes_of(track_by_name(mf, "Keys"), mf.ticks_per_beat)
    assert notes == [(F(0), F(1), 0, 60), (F(10), F(11), 0, 67)]


def test_concatenate_in_user_order():
    ev = note(0, 60, 0, Q) + note(0, 70, 8 * Q, Q)
    ws = load(smf([track(ev, "C")]))
    mf, = export(ws, ExportMode.REBASE, [Range(F(8), F(12)), Range(F(0), F(2))])
    notes = notes_of(track_by_name(mf, "C"), mf.ticks_per_beat)
    assert notes == [(F(0), F(1), 0, 70), (F(4), F(5), 0, 60)]
    assert abs_events(track_by_name(mf, "C"), mf.ticks_per_beat)[-1][0] == F(6)


def test_concatenation_boundary_note_off_before_next_on():
    # Note sustained to end of range 1; same pitch starts at start of range 2.
    ev = note(0, 60, 0, 8 * Q) + note(0, 60, 16 * Q, Q)
    ws = load(smf([track(ev, "B")]))
    mf, = export(ws, ExportMode.REBASE, [Range(F(0), F(4)), Range(F(16), F(17))])
    notes = notes_of(track_by_name(mf, "B"), mf.ticks_per_beat)
    assert notes == [(F(0), F(4), 0, 60), (F(4), F(5), 0, 60)]


def test_separate_files(tmp_path):
    ws = basic_ws()
    res = build_exports(ws, ExportOptions(mode=ExportMode.SEPARATE,
                                          ranges=[Range(F(0), F(2), "Intro"), Range(F(4), F(8))]))
    assert [r.label for r in res] == ["Intro", "Range 2"]
    paths = save_exports(res, str(tmp_path / "out.mid"))
    assert [os.path.basename(p) for p in paths] == ["out - Intro.mid", "out - Range 2.mid"]
    mf = mido.MidiFile(paths[1])
    assert notes_of(track_by_name(mf, "Keys"), mf.ticks_per_beat)[0] == (F(0), F(2), 0, 62)


def test_track_selection_and_disabled_tracks():
    ws = load(smf([track(note(0, 60, 0, Q), "A"), track(note(1, 60, 0, Q), "B"), track(note(2, 60, 0, Q), "C")]))
    ws.tracks[1].enabled = False
    mf = build_exports(ws)[0].midi
    names = [m.name for t in mf.tracks for m in t if m.type == "track_name"]
    assert names == ["A", "C"]
    mf = build_exports(ws, ExportOptions(track_ids=[ws.tracks[1].id]))[0].midi
    assert [m.name for t in mf.tracks for m in t if m.type == "track_name"] == ["B"]
    assert ws.tracks[1].enabled is False  # individual export does not change state


def test_renamed_and_reordered_tracks():
    ws = load(smf([track(note(0, 60, 0, Q), "A"), track(note(1, 60, 0, Q), "B")]))
    ws.tracks[0].name = "Lead"
    ws.move_track(ws.tracks[1].id, 0)
    mf = build_exports(ws)[0].midi
    assert [m.name for t in mf.tracks for m in t if m.type == "track_name"] == ["B", "Lead"]


def test_whole_trim_keeps_alignment():
    ws = load(smf([conductor(PPQ, tempos=((0, 100.0), (4 * Q, 130.0))),
                   track(note(0, 60, 8 * Q, Q), "A"), track(note(1, 40, 10 * Q, 2 * Q), "B")]))
    mf, = export(ws, ExportMode.WHOLE, [], trim=True)
    a = notes_of(track_by_name(mf, "A"), mf.ticks_per_beat)
    b = notes_of(track_by_name(mf, "B"), mf.ticks_per_beat)
    assert a == [(F(0), F(1), 0, 60)] and b == [(F(2), F(4), 1, 40)]
    tempos = [(t, round(mido.tempo2bpm(m.tempo))) for t, m in abs_events(mf.tracks[0], mf.ticks_per_beat)
              if m.type == "set_tempo"]
    assert tempos == [(F(0), 130)]
    assert abs_events(track_by_name(mf, "A"), mf.ticks_per_beat)[-1][0] == F(4)  # trailing trimmed


def test_trim_within_ranges():
    ws = load(smf([track(note(0, 60, 9 * Q, Q), "A")]))
    mf, = export(ws, ExportMode.REBASE, [Range(F(8), F(16))], trim=True)
    assert notes_of(track_by_name(mf, "A"), mf.ticks_per_beat) == [(F(0), F(1), 0, 60)]


def test_clip_offset_applied():
    ws = load(smf([track(note(0, 60, 0, Q), "A")]))
    ws.tracks[0].clips[0].offset = F(4)
    mf = build_exports(ws)[0].midi
    assert notes_of(track_by_name(mf, "A"), mf.ticks_per_beat) == [(F(4), F(5), 0, 60)]
    mf, = export(ws, ExportMode.REBASE, [Range(F(4), F(8))])
    assert notes_of(track_by_name(mf, "A"), mf.ticks_per_beat) == [(F(0), F(1), 0, 60)]


def test_unsnapped_range_increases_ppq_exactly():
    ws = load(smf([track(note(0, 60, 0, 4 * Q), "A")], ppq=96))
    mf, = export(ws, ExportMode.PRESERVE, [Range(F(1, 7), F(2))])
    assert mf.ticks_per_beat % 7 == 0
    assert notes_of(track_by_name(mf, "A"), mf.ticks_per_beat)[0][:2] == (F(1, 7), F(2))


def test_choose_ppq_fallback():
    assert choose_ppq([480], [F(1, 7919)]) == 480
    assert choose_ppq([96, 120], []) == 480


def test_no_ranges_falls_back_to_whole():
    ws = basic_ws()
    mf, = export(ws, ExportMode.REBASE, [])
    assert len(notes_of(track_by_name(mf, "Keys"), mf.ticks_per_beat)) == 5
