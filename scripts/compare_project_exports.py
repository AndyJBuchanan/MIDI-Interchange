#!/usr/bin/env python3
"""Compare audible DAWproject notes with paired MIDI exports, without rewriting files.

Run from the repository: .venv/bin/python scripts/compare_project_exports.py
Times are compared at 480 PPQ. Release velocities are reported by neither signature:
Cubase's supplied DAWprojects use zero whereas its MIDI exports often use 64.
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from midi_interchange.core.events import pair_notes
from midi_interchange.core.export_smf import audible_events
from midi_interchange.core.import_smf import import_smf_file
from midi_interchange.interchange.readers import payload_from_path, read_payload


def signature(track):
    events = [e for c in track.clips for e in audible_events(c)]
    events.sort(key=lambda e: (e.time, e.seq))
    notes, _ = pair_notes(events, track.end)
    return Counter((round(n.start*480), round(n.end*480), n.pitch,
                    n.on.msg.velocity, n.channel) for n in notes)


def compare(project_path, midi_path):
    source, tracks = read_payload(payload_from_path(str(project_path)))
    midi_source, midi_tracks = import_smf_file(str(midi_path))
    rows = []
    # Pair repeated names in order rather than silently collapsing them.
    remaining = list(midi_tracks)
    for track in tracks:
        if track.auxiliary:
            continue
        match = next((t for t in remaining if t.name == track.name), None)
        actual = Counter() if track.muted else signature(track)
        expected = signature(match) if match is not None else Counter()
        if match is not None:
            remaining.remove(match)
        rows.append(dict(track=track.name, dawproject=sum(actual.values()), midi=sum(expected.values()),
                         matching=sum((actual & expected).values()),
                         dawproject_only=sum((actual-expected).values()), midi_only=sum((expected-actual).values())))
    return dict(project=project_path.name, warnings=source.warnings,
                dawproject_tempos=[(float(t.time), round(t.bpm, 6)) for t in source.tempo_map.tempos],
                midi_tempos=[(float(t.time), round(t.bpm, 6)) for t in midi_source.tempo_map.tempos],
                tracks=rows, unmatched_midi_tracks=[t.name for t in remaining if not t.auxiliary])


if __name__ == '__main__':
    directory = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / 'samples/project-sets'
    results = []
    for project in sorted(directory.glob('*.dawproject')):
        midi = project.with_suffix('.mid')
        if not midi.exists():
            midi = Path(str(project)+'.midi')
        results.append(compare(project, midi))
    print(json.dumps(results, indent=2))
