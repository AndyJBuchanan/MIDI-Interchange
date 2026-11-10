"""Generate clip-assembly test MIDI: python tools/make_assembly_midi.py [outdir]

Default outdir: samples/assembly. The files are committed; tests/test_export_assembly.py
checks they match this generator and uses PARTS / SONG as the independent oracle.

Every part is a DAW-style dragged clip: one named track, notes from time zero,
end_of_track at the part's length. **Each part uses its own pitches**, so any
note in an export identifies the clip it came from.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

import mido

TEMPO_BPM = 120


@dataclass(frozen=True)
class Part:
    track_name: str
    channel: int                    # 0-based
    ppq: int
    length: float                   # beats (end_of_track)
    notes: tuple[tuple[float, float, int], ...]   # (start beat, duration beats, pitch)
    program: int | None = None


def _run(first_pitch: int, count: int, step: float = 1.0, dur: float = 0.5) -> tuple:
    return tuple((i * step, dur, first_pitch + i) for i in range(count))


PARTS: dict[str, Part] = {
    # four 8-beat Bass parts, as dragged one at a time from Cubase
    "bass_part_A.mid": Part("Bass", 0, 480, 8, _run(36, 8)),
    "bass_part_B.mid": Part("Bass", 0, 480, 8, _run(48, 8)),
    "bass_part_C_96ppq.mid": Part("Bass", 0, 96, 8, _run(60, 8)),        # different PPQ
    "bass_part_D_ch2.mid": Part("Bass", 1, 480, 8, _run(72, 8)),         # MIDI channel 2
    # long notes, for cutting at range edges: 2.5-beat notes every 2 beats
    "bass_part_E_long.mid": Part("Bass", 0, 480, 10, _run(96, 4, step=2.0, dur=2.5)),
    # a differently named part, to be moved across onto Bass
    "keys_part.mid": Part("Keys", 0, 480, 8, _run(84, 8), program=0),
}

# A Staccato-style song: one file, several tracks, a repeated track name on another channel.
SONG_FILE = "song_repeated_names.mid"
SONG: list[Part] = [
    Part("Bass", 0, 960, 16, _run(24, 16)),
    Part("Lead", 1, 960, 16, _run(100, 8, step=2.0)),
    Part("Bass", 4, 960, 16, _run(110, 16, dur=0.25)),
]

# Seven distinctly named tracks (A-G, channels 1-7), for range round trips:
# export ranges as separate files, drop them back into a new workspace.
SEVEN_FILE = "seven_tracks_A-G.mid"
SEVEN: list[Part] = [Part(n, i, 480, 16, _run(30 + 10 * i, 16, dur=0.5)) for i, n in enumerate("ABCDEFG")]


def _ticks(beats: float, ppq: int) -> int:
    t = beats * ppq
    assert t == int(t), (beats, ppq)
    return int(t)


def _mtrack(p: Part, ppq: int) -> mido.MidiTrack:
    ev: list[tuple[int, int, mido.Message]] = []
    if p.program is not None:
        ev.append((0, 0, mido.Message("program_change", channel=p.channel, program=p.program)))
    for start, dur, pitch in p.notes:
        ev.append((_ticks(start, ppq), 1, mido.Message("note_on", channel=p.channel, note=pitch, velocity=100)))
        ev.append((_ticks(start + dur, ppq), 0, mido.Message("note_off", channel=p.channel, note=pitch, velocity=0)))
    ev.sort(key=lambda e: (e[0], e[1]))
    trk = mido.MidiTrack([mido.MetaMessage("track_name", name=p.track_name, time=0)])
    prev = 0
    for tick, _k, msg in ev:
        trk.append(msg.copy(time=tick - prev))
        prev = tick
    trk.append(mido.MetaMessage("end_of_track", time=_ticks(p.length, ppq) - prev))
    return trk


def _conductor(ppq: int) -> mido.MidiTrack:
    return mido.MidiTrack([
        mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(TEMPO_BPM), time=0),
        mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0),
        mido.MetaMessage("end_of_track", time=0),
    ])


def build(parts: list[Part]) -> mido.MidiFile:
    ppq = parts[0].ppq
    mf = mido.MidiFile(type=1, ticks_per_beat=ppq)
    mf.tracks.append(_conductor(ppq))
    mf.tracks.extend(_mtrack(p, ppq) for p in parts)
    return mf


def all_files() -> dict[str, mido.MidiFile]:
    out = {name: build([p]) for name, p in PARTS.items()}
    out[SONG_FILE] = build(SONG)
    out[SEVEN_FILE] = build(SEVEN)
    return out


def main(outdir: str) -> None:
    os.makedirs(outdir, exist_ok=True)
    for name, mf in all_files().items():
        mf.save(os.path.join(outdir, name))
        print("wrote", os.path.join(outdir, name))


if __name__ == "__main__":
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(root, "samples", "assembly"))
