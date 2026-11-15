"""Native Reason song (.reason) reader: synthetic songs through the reader and
registry, failure handling and sessions; the local probe songs through the
app's exporter against Reason's own MIDI exports when present. Decoding:
test_reason_format.py; findings: docs/plans/reason-import.md."""
import glob
import hashlib
import io
import json
import os
import struct
from fractions import Fraction as F
from pathlib import Path

import mido
import pytest

from midi_interchange.core import reason_format as rf
from midi_interchange.core.document import Workspace
from midi_interchange.core.events import pair_notes
from midi_interchange.core.export_smf import ExportMode, ExportOptions, build_exports
from midi_interchange.core.import_reason import import_reason
from midi_interchange.core.import_smf import ImportError_
from midi_interchange.core.session import Session, decode, encode
from midi_interchange.interchange.readers import FILE_FILTER, payload_from_path, read_payload
from test_reason_format import PAGE, PROBE, B, chunk, clip_rec, container, group, rec, s32, vlq

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- builders

def points(pts) -> bytes:
    out, prev = b'', 0
    for pos, value in pts:
        out += vlq((pos - prev) & 0xFFFFFFFF) + struct.pack('>i', value) + bytes(10)
        prev = pos
    return out


def notes_clip(start, length, notes=(), *, muted=False, controllers=(), name='') -> bytes:
    """notes: (pos, pitch, velocity, length); controllers: (lane id, lo, hi, [(pos, value)])."""
    body, prev = struct.pack('>I', len(notes)), 0
    for pos, pitch, vel, ln in notes:
        body += vlq((pos - prev) & 0xFFFFFFFF) + bytes([pitch, vel]) + vlq(ln) + b'\0'
        prev = pos
    body += struct.pack('>I', len(controllers))
    for lane_id, lo, hi, pts in controllers:
        body += bytes([0, lane_id, 0]) + struct.pack('>iiI', lo, hi, len(pts)) + points(pts)
    return group(b'FORM', b'SNIF', chunk(b'SNIC', clip_rec(start, length, name, muted)), chunk(b'SNTE', rec(2, body)))


def auto_clip(start, length, kind, lo, hi, pts) -> bytes:
    saut = rec(2, bytes([kind]) + struct.pack('>iiI', lo, hi, len(pts)) + points(pts))
    return group(b'FORM', b'SNIF', chunk(b'SNIC', clip_rec(start, length)), chunk(b'SAUT', saut))


def pattern_clip(start, length) -> bytes:
    return group(b'FORM', b'SNIF', chunk(b'SNIC', clip_rec(start, length)), chunk(b'SPTN', rec(1, bytes(6))))


def lane(kind, clips, *, name='Lane 1', muted=False) -> bytes:
    return group(b'FORM', b'LANF', chunk(b'LANC', rec(3, bytes([kind]) + s32(name) + bytes([muted]))),
                 group(b'CAT ', b'LCCT', group(b'FORM', b'LCFM', chunk(b'LCAI', b'\0'),
                                               group(b'CAT ', b'SNCT', *clips))))


def track(device, lanes, *, muted=False, trsc=b'') -> bytes:
    trdc = rec(5, bytes(6) + struct.pack('>H', device) + bytes([muted]) + bytes(13))
    return group(b'FORM', b'TRFM', chunk(b'TRDC', trdc), group(b'CAT ', b'LNCT', *lanes),
                 *([chunk(b'TRSC', trsc)] if trsc else []))


def song(tracks, devices, *, generation=b'RS1300', version='14.1.0', seq_tempo=120000, hashed=True) -> bytes:
    meta = group(b'CAT ', b'WWWI', group(b'FORM', b'WWWI', chunk(b'WWID', rec(1, b'\0' + s32('PROGRAMVERSION'))),
                                         chunk(b'BODY', s32(version))))
    devl = group(b'CAT ', b'DEVL', *(group(b'FORM', b'DEVI', chunk(b'DESC', rec(3, b'\xff' + struct.pack('>I', d) + s32(n))))
                                    for d, n in devices.items()))
    seq_trdc = rec(1, bytes(18) + struct.pack('>I', seq_tempo) + bytes([4, 4, 0, 0, 0]))
    seq = group(b'CAT ', b'SQCT', chunk(b'TRDC', seq_trdc), group(b'CAT ', b'TSCT', *tracks))
    body = generation + b'\x1a' + bytes(121)
    body += group(b'CAT ', b'RS10', devl, seq) if generation == b'RS1300' else os.urandom(64)
    form = group(b'FORM', b'X15S', meta, chunk(b'BODY', body))
    stream = form + chunk(b'Hash', rec(1, hashlib.sha256(form).digest())) if hashed else form
    return container({4: stream}, 5)


TRANSPORT = {1: 'Hardware Interface II', 7: 'Lead', 8: 'Bass'}


def transport(*lanes, trsc=b''):
    return track(1, list(lanes) or [lane(0x5D, [])], trsc=trsc)


def read(data, name='s.reason'):
    return import_reason(None, name, data)


def notes_of(t):
    """(start, end, pitch, velocity) of unmuted clips, workspace beats."""
    return sorted((c.offset + n.start, c.offset + n.end, n.pitch, n.velocity)
                  for c in t.clips if not c.muted for n in pair_notes(c.events, c.length)[0])


# ---------------------------------------------------------------- synthetic

def test_tracks_clips_mutes_and_source():
    data = song([transport(),
                 track(7, [lane(0x59, [notes_clip(4 * B, 4 * B, [(0, 60, 100, B)], name='Riff'),
                                       notes_clip(8 * B, 4 * B, [(B, 62, 90, B)], muted=True)]),
                           lane(0x59, [notes_clip(0, 4 * B, [(0, 48, 80, 2 * B)])], name='Lane 2', muted=True)]),
                 track(8, [lane(0x59, [notes_clip(0, 4 * B, [(0, 36, 70, B)])])], muted=True)], TRANSPORT)
    source, tracks = read(data)
    assert (source.input_format, source.format_version, source.app, source.ppq) == ('reason', '14.1.0', 'Reason 14.1.0', rf.PPQ)
    assert source.file_summary.startswith('Reason song 14.1.0')
    lead, bass = tracks
    assert (lead.name, lead.muted, bass.name, bass.muted) == ('Lead', False, 'Bass', True)
    # lanes merged into the track; the muted lane's clip and the muted clip are kept, muted
    assert [(c.start, c.name, c.muted) for c in sorted(lead.clips, key=lambda c: c.start)] == \
           [(0, '', True), (4, 'Riff', False), (8, '', True)]
    assert notes_of(lead) == [(4, 5, 60, 100)]
    assert all(e.msg.channel == 0 for c in lead.clips for e in c.events)
    assert not any('folder' in w for w in source.warnings)


def test_covered_clip_splits_into_visible_stretches():
    data = song([transport(), track(7, [lane(0x59, [
        notes_clip(0, 8 * B, [(0, 60, 100, 8 * B), (6 * B, 64, 100, B)]),
        notes_clip(2 * B, 2 * B, [(0, 62, 100, B)])])])], TRANSPORT)
    _, (lead,) = read(data)
    # the long clip shows either side of the cover
    assert [(c.start, c.end) for c in sorted(lead.clips, key=lambda c: c.start)] == [(0, 2), (2, 4), (4, 8)]
    # the long note is cut where the cover starts; the note after the cover plays
    assert notes_of(lead) == [(0, 2, 60, 100), (2, 3, 62, 100), (6, 7, 64, 100)]


def test_tempo_map_from_transport_clips_and_static_tempo():
    trsc = struct.pack('>I', 1) + struct.pack('>Hi', rf.TEMPO_PARAM, 100000) + struct.pack('>ii', 1000, 999999)
    tempo = lane(0x5B, [auto_clip(4 * B, 4 * B, 0, 1000, 999999, [(0, 120000), (B, 90000)])], name='')
    sig = lane(0x5B, [auto_clip(8 * B, 6 * B, 2, 0, 65535, [(0, 4 << 8 | 3)])], name='')
    data = song([transport(tempo, sig, lane(0x5D, []), trsc=trsc),
                 track(7, [lane(0x59, [notes_clip(0, 4 * B, [(0, 60, 100, B)])])])], TRANSPORT, seq_tempo=130000)
    source, _ = read(data)
    tm = source.tempo_map
    steps = [(c.time, c.us_per_beat) for c in tm.tempos]
    # outside clips the Transport's static tempo (100), not the sequencer's (130)
    assert steps[0] == (0, 600000) and steps[-1] == (8, 600000)
    assert steps[1] == (4, 500000) and (5, 666666) in steps          # 90 BPM, truncated to whole microseconds
    assert (F(4) + F(1, 32), 60_000_000_000 // 119062) in steps     # 120 - 30/32 BPM, truncated
    assert [(c.time, c.numerator, c.denominator) for c in tm.timesigs] == [(0, 4, 4), (8, 3, 4), (14, 4, 4)]


def test_controllers_ramp_jump_and_reset():
    data = song([transport(), track(7, [lane(0x59, [notes_clip(0, 2 * B, [(0, 60, 100, B)], controllers=[
        (0x01, 0, 127, [(0, 0), (B // 8, 8)]),          # mod wheel: a line, 1/32-beat steps
        (0x40, 0, 127, [(B // 2, 127), (B, 0)]),         # sustain: jumps
        (0xFF, -8192, 8191, [(0, -100)])])])])], TRANSPORT)
    _, (lead,) = read(data)
    (clip,) = lead.clips
    cc1 = [(e.time, e.msg.value) for e in clip.events if e.msg.type == 'control_change' and e.msg.control == 1]
    assert cc1 == [(0, 0), (F(1, 32), 2), (F(2, 32), 4), (F(3, 32), 6), (F(1, 8), 8), (2, 0)]
    cc64 = [(e.time, e.msg.value) for e in clip.events if e.msg.type == 'control_change' and e.msg.control == 64]
    assert cc64 == [(0, 127), (F(1, 2), 127), (1, 0), (2, 0)]      # the first value holds from the clip start
    pw = [(e.time, e.msg.pitch) for e in clip.events if e.msg.type == 'pitchwheel']
    assert pw == [(0, -100), (2, 0)]


def test_skipped_material_is_reported():
    data = song([transport(), track(7, [lane(0x59, [notes_clip(0, 4 * B, [(0, 60, 100, B)])]),
                                        lane(0x5A, [pattern_clip(0, 4 * B)], name='')])], TRANSPORT)
    source, _ = read(data)
    assert any('Pattern clips are not imported' in w for w in source.warnings)


def test_registry_detects_reason_by_extension_and_content(tmp_path):
    assert '*.reason' in FILE_FILTER
    data = song([transport(), track(7, [lane(0x59, [notes_clip(0, 4 * B, [(0, 60, 100, B)])])])], TRANSPORT)
    path = tmp_path / 'tune.reason'
    path.write_bytes(data)
    p = payload_from_path(str(path))
    assert p.data == b'' and p.byte_size == len(data)                      # path-backed
    result = read_payload(p)
    assert result.preserve_track_state and result.source.byte_size == len(data)
    source, _ = import_reason(None, 'renamed.bin', data)                    # by content
    assert source.byte_size == len(data)


def test_encrypted_and_old_songs_ask_for_a_resave():
    with pytest.raises(ImportError_, match=r'saved by Reason 12\.2\.7.*Reason 13 or later'):
        read(song([], {}, generation=b'RS1200', version='12.2.7'))
    # Reason 10 and earlier: no Hash chunk
    with pytest.raises(ImportError_, match=r'saved by Reason 9\.1\.0.*Reason 13 or later'):
        read(song([], {}, generation=b'RSN900', version='9.1.0', hashed=False))


@pytest.mark.parametrize('damage', [
    lambda d: d[:len(d) // 2],                       # truncated
    lambda d: b'RIFF' + d[4:],                       # wrong magic
    lambda d: d[:52 + 3 * PAGE + 100] + b'\x00' * 64 + d[52 + 3 * PAGE + 164:],   # song stream: hash fails
])
def test_damaged_songs_fail_without_workspace_change(damage):
    data = damage(song([transport(), track(7, [lane(0x59, [notes_clip(0, 4 * B, [(0, 60, 100, B)])])])], TRANSPORT))
    ws = Workspace()
    with pytest.raises(ImportError_):
        ws.add_import(*read(data))
    assert ws.tracks == []


def test_song_without_note_clips_fails_cleanly():
    with pytest.raises(ImportError_, match='no note clips'):
        read(song([transport()], TRANSPORT))


def test_input_file_is_never_modified(tmp_path):
    path = tmp_path / 'tune.reason'
    path.write_bytes(song([transport(), track(7, [lane(0x59, [notes_clip(0, 4 * B, [(0, 60, 100, B)])])])], TRANSPORT))
    before = path.read_bytes(), path.stat().st_mtime_ns
    read_payload(payload_from_path(str(path)))
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_session_roundtrip_keeps_reason_source_and_exports():
    data = song([transport(), track(7, [lane(0x59, [notes_clip(0, 4 * B, [(0, 60, 100, B)], controllers=[
        (0x01, 0, 127, [(0, 0), (B, 64)])])])])], TRANSPORT)
    source, tracks = read(data)
    ws = Workspace()
    ws.add_import(source, tracks, preserve_track_state=True)
    restored = Workspace()
    restored.restore(decode(json.loads(json.dumps(encode(Session(ws.snapshot(), {}))))).workspace)
    assert (restored.sources[0].input_format, restored.sources[0].format_version) == ('reason', '14.1.0')
    for mode in ExportMode:
        a = [(r.label, [list(map(str, t)) for t in r.midi.tracks]) for r in build_exports(ws, ExportOptions(mode=mode))]
        b = [(r.label, [list(map(str, t)) for t in r.midi.tracks]) for r in build_exports(restored, ExportOptions(mode=mode))]
        assert a == b


# ---------------------------------------------- probe songs through the app's exporter

PAIRS = sorted(m for m in glob.glob(os.path.join(PROBE, '**', '*.mid'), recursive=True)
               if os.path.exists(m[:-4] + '.reason'))
# Differences that are not decoding errors (see the plan):
EXPECTED_NOTE_GAPS = {
    'r14.mid': 'track mute is kept (Reason exports muted tracks)',
    'Day01-0-3(14).mid': 'track mute is kept on Voclas Raw MIDI Ref',
}
CONTROL_GAPS = {     # (song, track): why Reason's export differs
    ('Day 15(2019)-002(14).mid', 'PAD'): 'device automation exported as CC 64 by Reason, not imported',
    ('Day01-0-3(14).mid', 'Piano L'): 'Reason leaves out aftertouch the device does not take',
    ('Day01-0-3(14).mid', 'Piano R'): 'Reason leaves out aftertouch the device does not take',
    ('Oct08-01-13-instr-rarity-sd4.mid', '008 Seq Trigger'): 'Reason leaves out expression the device does not take',
    ('r26.mid', 'Lead'): 'strongest curves (k about 12): see test_strong_curves_are_close',
    ('r27.mid', 'Lead'): 'strongest curves (k about 12): see test_strong_curves_are_close',
}


def app_export(reason_path):
    result = read_payload(payload_from_path(reason_path))
    ws = Workspace()
    ws.add_import(result.source, result.tracks, preserve_track_state=result.preserve_track_state)
    buf = io.BytesIO()
    build_exports(ws, ExportOptions())[0].midi.save(file=buf)
    buf.seek(0)
    return mido.MidiFile(file=buf)


def timeline(midi):
    """Per track name: (notes multiset, controller timeline with redundant
    values dropped, tempo/signature events)."""
    out, timing = {}, []
    for tr in midi.tracks:
        t, on, notes, ctl = 0, {}, [], []
        for m in tr:
            t += m.time
            tick = round(F(t, midi.ticks_per_beat) * rf.PPQ)
            if m.type == 'note_on' and m.velocity:
                on.setdefault(m.note, []).append((tick, m.velocity))
            elif m.type in ('note_off', 'note_on'):
                s, v = on[m.note].pop(0)
                notes.append((s, tick - s, m.note, v))
            elif m.type == 'control_change' and m.control in (1, 11, 64):    # others: device automation
                ctl.append((tick, m.control, m.value))
            elif m.type == 'pitchwheel':
                ctl.append((tick, 'pw', m.pitch))
            elif m.type == 'aftertouch':
                ctl.append((tick, 'at', m.value))
            elif m.type == 'set_tempo':
                timing.append((tick, m.tempo))
            elif m.type == 'time_signature':
                timing.append((tick, m.numerator, m.denominator))
        last = {}
        for tick, k, v in ctl:
            last[(tick, k)] = v                 # the last value at a tick wins
        cur, eff = {}, []
        for (tick, k), v in sorted(last.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
            if cur.get(k, 0) != v:
                eff.append((tick, k, v))
                cur[k] = v
        if notes or eff:
            out.setdefault(tr.name, []).append((sorted(notes), eff))
    return out, sorted(timing, key=lambda e: (e[0], len(e)))


@pytest.mark.skipif(not PAIRS, reason='local Reason probe songs not present')
@pytest.mark.parametrize('mid', PAIRS, ids=lambda m: os.path.relpath(m, PROBE))
def test_probe_song_round_trip_matches_reason_export(mid):
    name = os.path.basename(mid)
    ours, our_timing = timeline(app_export(mid[:-4] + '.reason'))
    theirs, their_timing = timeline(mido.MidiFile(mid))
    assert our_timing == their_timing
    for track_name, versions in ours.items():
        (our_notes, our_ctl), = versions
        # Reason may export a same-named automation track too; compare with the one that has notes
        cands = theirs.get(track_name, [])
        their_notes, their_ctl = next((v for v in cands if v[0]), cands[0] if cands else ([], []))
        assert our_notes == their_notes, track_name
        if (name, track_name) not in CONTROL_GAPS:
            assert our_ctl == their_ctl, track_name
    missing = {n for n, vs in theirs.items() if any(v[0] for v in vs)} - set(ours)
    assert not missing or name in EXPECTED_NOTE_GAPS, missing


@pytest.mark.skipif(not PAIRS, reason='local Reason probe songs not present')
def test_curved_mod_wheel_matches_reason_event_for_event():
    """Day 15's Swell: three curved segments (k = 2.1, -4.7, -1.8). Every event
    Reason exports after the clip start (where it leaves out the value 0,
    already current) and before its end, and no others."""
    mid = next((m for m in PAIRS if os.path.basename(m) == 'Day 15(2019)-002(14).mid'), None)
    if mid is None:
        pytest.skip('Day 15 not present')
    song, _ = rf.open_song(open(mid[:-4] + '.reason', 'rb').read())
    lo, hi = 64 * B, 88 * B
    ours = sorted((t, v) for tr, ctl in rf.played_controls(song) if tr.name == 'Swell'
                  for t, i, v in ctl if i == 0x01 and lo < t < hi)
    theirs, t = [], 0
    for tr in mido.MidiFile(mid).tracks:
        if tr.name == 'Swell':
            for m in tr:
                t += m.time
                if m.type == 'control_change' and m.control == 1 and lo < t < hi:
                    theirs.append((t, m.value))
    assert ours == sorted(theirs)


@pytest.mark.skipif(not PAIRS, reason='local Reason probe songs not present')
@pytest.mark.parametrize('name, lane_id, tolerance', [('r26', 0x01, 1), ('r27', 0x01, 0), ('r27', 0xFF, 64)])
def test_strong_curves_are_close(name, lane_id, tolerance):
    """r26/r27 hold full-strength curves (k about +-12). Reason's last piece of
    such a curve runs about 6% steeper than the line between its joins (open
    question in the plan), and a few pitch-bend joins round the other way: at
    any moment the value is within one mod-wheel step, or 64 of 16383 bend."""
    path = os.path.join(PROBE, name)
    if not os.path.exists(path + '.mid'):
        pytest.skip(f'{name} not present')
    song, _ = rf.open_song(open(path + '.reason', 'rb').read())
    ours = sorted((t, v) for tr, ctl in rf.played_controls(song) if tr.name == 'Lead' for t, i, v in ctl if i == lane_id)
    theirs, t = [], 0
    for tr in mido.MidiFile(path + '.mid').tracks:
        if tr.name == 'Lead':
            for m in tr:
                t += m.time
                if lane_id == 0x01 and m.type == 'control_change' and m.control == 1:
                    theirs.append((t, m.value))
                elif lane_id == 0xFF and m.type == 'pitchwheel':
                    theirs.append((t, m.pitch))

    def at(seq, tick):
        vals = [v for t_, v in seq if t_ <= tick]
        return vals[-1] if vals else 0
    ticks = sorted({t_ for t_, _ in ours} | {t_ for t_, _ in theirs})
    assert max(abs(at(ours, k) - at(theirs, k)) for k in ticks) <= tolerance
