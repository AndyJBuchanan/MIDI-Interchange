#!/usr/bin/env python3
"""Compare actual app-exported MIDI against paired DAW MIDI exports.

Run: .venv/bin/python scripts/compare_project_exports.py [project-set-directory]
The comparison serializes and reparses the app output, normalizes PPQ, handles
velocity-zero note-offs, and separates one-reference-tick differences from changed
note lengths and unmatched notes. No source files are rewritten.
"""
import argparse
import io
import json
import sys
from collections import Counter
from fractions import Fraction
from pathlib import Path

import mido

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from midi_interchange.core.document import Workspace
from midi_interchange.core.events import Event, is_note_off, pair_notes
from midi_interchange.core.export_smf import build_exports, ExportOptions, ExportMode
from midi_interchange.core.ranges import Range
from midi_interchange.interchange.readers import payload_from_path, read_payload


def midi_tracks(midi):
    tracks = []
    for track in midi.tracks:
        tick = 0
        events = []
        for seq, msg in enumerate(track):
            tick += msg.time
            events.append(Event(Fraction(tick, midi.ticks_per_beat), msg, seq))
        notes, orphans = pair_notes(events, Fraction(tick, midi.ticks_per_beat))
        tracks.append(dict(name=track.name, notes=notes, events=events,
                           orphan_releases=len(orphans), unreleased=sum(n.off is None for n in notes)))
    return tracks


def note_signature(note, ppq):
    return (note.start*ppq, note.end*ppq, note.pitch, note.velocity, note.channel)


def match_notes(actual, expected, ppq):
    """Disjoint tiers, preserving multiplicity and repeated pitches."""
    actual = Counter(note_signature(n, ppq) for n in actual)
    expected = Counter(note_signature(n, ppq) for n in expected)
    common = actual & expected
    actual -= common
    expected -= common
    result = dict(exact=sum(common.values()), within_one_tick=0, changed_duration=0)
    examples = []
    for category in ('within_one_tick', 'changed_duration'):
        for a in list(actual):
            while actual[a]:
                candidates = [b for b in expected if expected[b] and a[2:] == b[2:]
                              and abs(a[0]-b[0]) <= 1
                              and (category == 'changed_duration' or abs(a[1]-b[1]) <= 1)]
                if not candidates:
                    break
                b = min(candidates, key=lambda b: (abs(a[0]-b[0])+abs(a[1]-b[1]), b))
                actual[a] -= 1
                expected[b] -= 1
                result[category] += 1
                if category == 'changed_duration' and len(examples) < 5:
                    examples.append(dict(app=list(map(float, a)), cubase=list(map(float, b))))
    result.update(app_only=sum(actual.values()), cubase_only=sum(expected.values()),
                  duration_examples=examples,
                  app_only_examples=[list(map(float, n)) for n in list(actual.elements())[:5]],
                  cubase_only_examples=[list(map(float, n)) for n in list(expected.elements())[:5]])
    return result


def event_summary(track):
    events = track['events'] if track else []
    return dict(controllers=dict(sorted(Counter(e.msg.control for e in events if e.msg.type == 'control_change').items())),
                pitch_bends=sum(e.msg.type == 'pitchwheel' for e in events),
                release_velocities=dict(sorted(Counter(e.msg.velocity for e in events if is_note_off(e.msg)).items())),
                orphan_releases=track['orphan_releases'] if track else 0,
                unreleased_notes=track['unreleased'] if track else 0)


def compare(project_path, midi_path, *, window=None):
    result = read_payload(payload_from_path(str(project_path)))
    source, tracks = result
    workspace = Workspace()
    workspace.add_import(source, tracks, preserve_track_state=result.preserve_track_state)
    buffer = io.BytesIO()
    options = ExportOptions()
    if window is not None:
        start, end = map(Fraction, window)
        if start < 0 or end <= start:
            raise ValueError('Comparison window must have 0 <= start < end')
        workspace.ranges = [Range(start, end, 'Reference window')]
        options.mode = ExportMode.REBASE
    build_exports(workspace, options)[0].midi.save(file=buffer)
    buffer.seek(0)
    actual = mido.MidiFile(file=buffer)
    reference = mido.MidiFile(midi_path)
    a_tracks, b_tracks = midi_tracks(actual), midi_tracks(reference)
    rows = []
    remaining = list(b_tracks)
    for track in a_tracks:
        # Conductor/empty tracks are structural differences, listed separately.
        if not any(not e.msg.is_meta for e in track['events']):
            continue
        match = next((t for t in remaining if t['name'] == track['name']), None)
        if match is not None:
            remaining.remove(match)
        rows.append(dict(track=track['name'], app_notes=len(track['notes']),
                         cubase_notes=len(match['notes']) if match else 0,
                         notes=match_notes(track['notes'], match['notes'] if match else [], reference.ticks_per_beat),
                         app_events=event_summary(track), cubase_events=event_summary(match)))
    def timing(midi):
        events = [[float(e.time), e.msg.type, {k:v for k,v in e.msg.dict().items() if k not in ('type', 'time')}]
                  for t in midi_tracks(midi) for e in t['events'] if e.msg.type in ('set_tempo', 'time_signature')]
        return sorted(events, key=lambda e: (e[0], e[1]))
    return dict(project=project_path.name, reference=midi_path.name, warnings=source.warnings,
                source_window_beats=list(map(float, window)) if window is not None else None,
                comparison_tick_unit=f'1/{reference.ticks_per_beat} beat',
                note_example_fields=['start_tick', 'end_tick', 'pitch', 'attack_velocity', 'channel'],
                app_ppq=actual.ticks_per_beat, cubase_ppq=reference.ticks_per_beat,
                app_timing=timing(actual), cubase_timing=timing(reference),
                app_track_names=[t['name'] for t in a_tracks], cubase_track_names=[t['name'] for t in b_tracks],
                tracks=rows,
                unmatched_cubase_tracks=[dict(track=t['name'], notes=len(t['notes']), events=event_summary(t))
                                         for t in remaining if any(not e.msg.is_meta for e in t['events'])])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', nargs='?', type=Path,
                        default=Path(__file__).resolve().parents[1] / 'samples/project-sets')
    parser.add_argument('--window', action='append', nargs=3, default=[],
                        metavar=('PROJECT_STEM', 'START_BEAT', 'END_BEAT'),
                        help='Explicit diagnostic export window, rebased to zero; never inferred or applied to input files')
    args = parser.parse_args()
    windows = {name: (Fraction(start), Fraction(end)) for name, start, end in args.window}
    projects = sorted(args.directory.glob('*.dawproject'))
    unknown = windows.keys() - {p.stem for p in projects}
    if unknown:
        parser.error('Unknown project window: ' + ', '.join(sorted(unknown)))
    results = []
    for project in projects:
        midi = project.with_suffix('.mid')
        if not midi.exists():
            midi = Path(str(project)+'.midi')
        results.append(compare(project, midi, window=windows.get(project.stem)))
    print(json.dumps(results, indent=2))
