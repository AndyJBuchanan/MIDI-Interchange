"""Generate demo MIDI files for manual testing: python tools/make_demo_midi.py [outdir]"""
from __future__ import annotations

import os
import sys

import mido


def _track(name: str, events: list[tuple[int, mido.Message]]) -> mido.MidiTrack:
    trk = mido.MidiTrack()
    trk.append(mido.MetaMessage("track_name", name=name, time=0))
    prev = 0
    for tick, msg in sorted(events, key=lambda e: e[0]):
        trk.append(msg.copy(time=tick - prev))
        prev = tick
    trk.append(mido.MetaMessage("end_of_track", time=0))
    return trk


def note(ch, pitch, start, dur, vel=96):
    return [(start, mido.Message("note_on", channel=ch, note=pitch, velocity=vel)),
            (start + dur, mido.Message("note_off", channel=ch, note=pitch, velocity=0))]


def piano(ppq=480, bars=16):
    prog = [(60, 64, 67), (57, 60, 64), (53, 57, 60), (55, 59, 62)]
    ev = [(0, mido.Message("program_change", channel=0, program=0)),
          (0, mido.Message("control_change", channel=0, control=7, value=100))]
    for bar in range(bars):
        chord = prog[bar % 4]
        for beat in range(4):
            t = (bar * 4 + beat) * ppq
            for p in chord:
                ev += note(0, p, t, ppq - 20, 70 + (beat == 0) * 25)
        ev.append((bar * 4 * ppq, mido.Message("control_change", channel=0, control=64, value=127)))
        ev.append(((bar * 4 + 4) * ppq - 10, mido.Message("control_change", channel=0, control=64, value=0)))
    conductor = mido.MidiTrack([
        mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(96), time=0),
        mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0),
        mido.MetaMessage("marker", text="Verse", time=0),
        mido.MetaMessage("marker", text="Chorus", time=8 * 4 * ppq),
        mido.MetaMessage("end_of_track", time=0),
    ])
    mf = mido.MidiFile(type=1, ticks_per_beat=ppq)
    mf.tracks += [conductor, _track("Piano", ev)]
    return mf


def bass(ppq=96, bars=16):
    roots = [36, 33, 29, 31]
    ev = [(0, mido.Message("program_change", channel=1, program=33))]
    for bar in range(bars):
        r = roots[bar % 4]
        for i, (off, dur, p) in enumerate([(0, 3, r), (3, 1, r), (4, 2, r + 7), (6, 2, r + 12)]):
            ev += note(1, p, bar * 4 * ppq + off * ppq // 2, dur * ppq // 2 - 4, 100)
        ev.append((bar * 4 * ppq + 2 * ppq, mido.Message("pitchwheel", channel=1, pitch=1200)))
        ev.append((bar * 4 * ppq + 3 * ppq, mido.Message("pitchwheel", channel=1, pitch=0)))
    mf = mido.MidiFile(type=1, ticks_per_beat=ppq)
    mf.tracks += [mido.MidiTrack([mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(96)),
                                  mido.MetaMessage("end_of_track")]), _track("Bass", ev)]
    return mf


def melody_with_lyrics(ppq=960):
    words = "Hel- lo out there in the dark to- night".split()
    pitches = [72, 74, 76, 79, 77, 76, 74, 72, 71]
    ev = []
    t = 4 * 4 * ppq  # starts at bar 5
    for w, p in zip(words, pitches):
        ev.append((t, mido.MetaMessage("lyrics", text=w)))
        ev += note(2, p, t, ppq * 3 // 2, 90)
        t += 2 * ppq
    ev.append((4 * 4 * ppq, mido.Message("sysex", data=[0x7E, 0x7F, 0x09, 0x01])))
    ev.append((4 * 4 * ppq, mido.UnknownMetaMessage(type_byte=0x60, data=(1, 2, 3))))
    mf = mido.MidiFile(type=1, ticks_per_beat=ppq)
    mf.tracks += [mido.MidiTrack([mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(96)),
                                  mido.MetaMessage("time_signature", numerator=4, denominator=4),
                                  mido.MetaMessage("end_of_track")]),
                  _track("Vocal", ev)]
    return mf


def drums_format0(ppq=480, bars=8):
    ev = []
    for bar in range(bars):
        for eighth in range(8):
            t = bar * 4 * ppq + eighth * ppq // 2
            ev += note(9, 42, t, ppq // 4, 70)
            if eighth in (0, 4):
                ev += note(9, 36, t, ppq // 4, 110)
            if eighth in (2, 6):
                ev += note(9, 38, t, ppq // 4, 105)
    ev += [(0, mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(96)))]
    trk = _track("Drums", ev)
    mf = mido.MidiFile(type=0, ticks_per_beat=ppq)
    mf.tracks.append(trk)
    return mf


def main(outdir: str) -> None:
    os.makedirs(outdir, exist_ok=True)
    for name, mf in [("piano_96bpm.mid", piano()), ("bass_96ppq.mid", bass()),
                     ("vocal_lyrics.mid", melody_with_lyrics()), ("drums_format0.mid", drums_format0())]:
        path = os.path.join(outdir, name)
        mf.save(path)
        print(path)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "samples"))
