"""Reason song decoding (core/reason_format.py) on synthetic files, and on the
local r-series fixtures against Reason's own MIDI exports when present."""
import glob
import hashlib
import os
import struct

import mido
import pytest

from midi_interchange.core import reason_format as rf

PROBE = os.path.join(os.path.dirname(__file__), '..', 'samples', 'reason-probe')
PAGE = 0x40000


# ---------------------------------------------------------------- builders

def chunk(cid: bytes, body: bytes) -> bytes:
    return cid + struct.pack('>I', len(body)) + body + (b'\0' if len(body) & 1 else b'')


def group(kind: bytes, sub: bytes, *kids: bytes) -> bytes:
    return chunk(kind, sub + b''.join(kids))


def rec(version: int, payload: bytes) -> bytes:
    return bytes([0xBC, version, 0, 0, 0]) + payload


def s32(text: str) -> bytes:
    b = text.encode()
    return struct.pack('>I', len(b)) + b


def vlq(n: int) -> bytes:
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append(0x80 | (n & 0x7F))
        n >>= 7
    return bytes(reversed(out))


def notes_rec(notes, lanes=()) -> bytes:
    body = struct.pack('>I', len(notes))
    prev = 0
    for pos, pitch, vel, length in notes:
        body += vlq(pos - prev) + bytes([pitch, vel]) + vlq(length) + b'\0'
        prev = pos
    body += struct.pack('>I', len(lanes))
    for lane_id, lo, hi, points in lanes:
        body += bytes([0, lane_id, 0]) + struct.pack('>iiI', lo, hi, len(points))
        prev = 0
        for pos, value in points:
            body += vlq(pos - prev) + struct.pack('>i', value) + bytes(10)
            prev = pos
    return rec(2, body)


def clip_rec(start, length, name='', muted=False) -> bytes:
    return rec(5, struct.pack('>II', start, length) + bytes(8) + s32(name) + bytes([muted]) + bytes(11))


def song_stream(*, generation=b'RS1300', notes=((15360, 60, 100, 15360),), clip=(0, 61440, 'Riff', False),
                lane_muted=False, track_muted=False, version='14.1.0') -> bytes:
    meta = group(b'CAT ', b'WWWI', group(b'FORM', b'WWWI',
                 chunk(b'WWID', rec(1, b'\0' + s32('PROGRAMVERSION'))), chunk(b'BODY', s32(version))))
    devl = group(b'CAT ', b'DEVL', group(b'FORM', b'DEVI', chunk(b'DESC', rec(3, b'\xff' + struct.pack('>I', 7) + s32('Lead')))))
    track = group(b'FORM', b'TRFM',
                  chunk(b'TRDC', rec(5, bytes(6) + struct.pack('>H', 7) + bytes([track_muted]) + bytes(4) + b'\x0a' + bytes(8))),
                  group(b'CAT ', b'LNCT', group(b'FORM', b'LANF',
                        chunk(b'LANC', rec(3, b'\x59' + s32('Lane 1') + bytes([lane_muted]))),
                        group(b'CAT ', b'LCCT', group(b'FORM', b'LCFM', chunk(b'LCAI', b'\0'),
                              group(b'CAT ', b'SNCT', group(b'FORM', b'SNIF', chunk(b'SNIC', clip_rec(*clip)),
                                    chunk(b'SNTE', notes_rec(notes)))))))))
    seq = group(b'CAT ', b'SQCT', group(b'CAT ', b'TSCT', track))
    body = generation + b'\x1a' + bytes(121)
    body += group(b'CAT ', b'RS10', devl, seq) if generation == b'RS1300' else os.urandom(64)
    form = group(b'FORM', b'X15S', meta, chunk(b'BODY', body))
    return form + chunk(b'Hash', rec(1, hashlib.sha256(form).digest()))


def container(copies: dict[int, bytes], pages: int, hint: int = 0) -> bytes:
    """copies: {index page: song stream}; each stream goes on the pages just before its index."""
    out = [b'\xfe' * PAGE for _ in range(pages)]
    for idx, stream in copies.items():
        n = -(-len(stream) // PAGE)
        spages = list(range(idx - n, idx))
        for i, pg in enumerate(spages):
            part = stream[i * PAGE:(i + 1) * PAGE]
            out[pg] = part + b'\xfe' * (PAGE - len(part))
        entry = struct.pack('>IQQ', 1, len(stream), n) + struct.pack(f'>{n}Q', *spages) + struct.pack('>I', rf.ENTRY_END)
        page = rf.INDEX_MARK + struct.pack('>I', 1) + entry + struct.pack('>I', 0xB0BAFE77)
        out[idx] = page + b'\xfe' * (PAGE - len(page))
    head = rf.MAGIC + struct.pack('>IIQQ', PAGE, 0x24, 2, hint) + bytes(20)
    return head + b''.join(out)


# ---------------------------------------------------------------- synthetic

def test_varint_and_records_round_trip():
    assert rf.varint(bytes.fromhex('81f000'), 0) == (30720, 3)
    assert rf.varint(bytes.fromhex('f800'), 0) == (15360, 2)
    notes, lanes, tail = rf.decode_notes(notes_rec([(0, 60, 100, 15360), (61440, 64, 90, 7680)],
                                                   [(0xFF, -8192, 8191, [(0, -5977), (19200, 2878)])]))
    assert [(n.pos, n.pitch, n.velocity, n.length) for n in notes] == [(0, 60, 100, 15360), (61440, 64, 90, 7680)]
    assert lanes[0].lane_id == 0xFF and (lanes[0].lo, lanes[0].hi) == (-8192, 8191)
    assert [(p.pos, p.value) for p in lanes[0].points] == [(0, -5977), (19200, 2878)] and tail == b''
    c = rf.decode_clip(clip_rec(261120, 103680, 'Riff', True))
    assert (c.start, c.length, c.name, c.muted) == (261120, 103680, 'Riff', True)
    lane = rf.decode_lane(rec(3, b'\x59' + s32('Lane 2') + b'\x01'))
    assert (lane.kind, lane.name, lane.muted) == (0x59, 'Lane 2', True)


def test_song_decodes_tracks_lanes_clips_and_metadata():
    data = container({4: song_stream(clip=(245760, 61440, 'Riff', True), lane_muted=True, track_muted=True)}, 5)
    song, notes = rf.open_song(data)
    assert notes == [] and song.generation == 'RS1300' and song.metadata['PROGRAMVERSION'] == '14.1.0'
    (t,) = rf.tracks(song)
    assert (t.name, t.info.device, t.info.muted, t.info.kind) == ('Lead', 7, True, 0x0A)
    (lane,) = t.lanes
    assert lane.info.muted and lane.info.name == 'Lane 1'
    (c,) = lane.clips
    assert (c.kind, c.block, c.info.start, c.info.name, c.info.muted) == ('notes', 0, 245760, 'Riff', True)
    assert [(n.pos, n.pitch) for n in c.notes] == [(15360, 60)]


def test_newest_copy_is_highest_verified_index_page_and_bad_hash_is_ignored():
    old = song_stream(notes=((0, 60, 100, 15360),))
    new = song_stream(notes=((0, 62, 100, 15360),))
    for hint in (4, 9):                       # the header hint does not decide it
        song, notes = rf.open_song(container({4: old, 9: new}, 10, hint))
        assert rf.tracks(song)[0].lanes[0].clips[0].notes[0].pitch == 62 and 'page 9' in notes[0]
    broken = bytearray(new)
    broken[200] ^= 0xFF                        # corrupt the newer copy: its hash fails
    song, notes = rf.open_song(container({4: old, 9: bytes(broken)}, 10))
    assert rf.tracks(song)[0].lanes[0].clips[0].notes[0].pitch == 60 and notes == []


def test_encrypted_generation_reads_metadata_only():
    song, _ = rf.open_song(container({4: song_stream(generation=b'RS1200', version='12.2.7')}, 5))
    assert song.generation == 'RS1200' and song.body == [] and rf.tracks(song) == []
    assert rf.generation_version('RS1200') == '12' and rf.generation_version('RSN999') == '9.5'


@pytest.mark.parametrize('data', [b'RIFF' + bytes(100), rf.MAGIC + bytes(44), container({}, 2)])
def test_unreadable_files_raise(data):
    with pytest.raises(rf.ReasonFormatError):
        rf.open_song(data)


# ---------------------------------------------------------------- r-series against Reason's exports

def rendered(song):
    """Note-ons Reason would export: unmuted clips on unmuted lanes inside clip
    bounds, plus Block clips at each Block placement. Muted tracks still export."""
    out = {}
    ts = rf.tracks(song)
    places = [c for t in ts for ln in t.lanes if not ln.info.muted for c in ln.clips if c.kind == 'block' and not c.info.muted]
    for t in ts:
        for ln in t.lanes:
            for c in ln.clips:
                if c.kind != 'notes' or c.info.muted or ln.info.muted:
                    continue
                starts = [(p.info.start, p.info.length) for p in places] if c.block else [(0, None)]
                for base, limit in starts:
                    for n in c.notes:
                        if n.pos < c.info.length and (limit is None or c.info.start + n.pos < limit):
                            out.setdefault(t.name, []).append((base + c.info.start + n.pos, n.pitch, n.velocity, n.length))
    return {k: sorted(v) for k, v in out.items()}


def exported(path):
    out = {}
    m = mido.MidiFile(path)
    assert m.ticks_per_beat == rf.PPQ
    for tr in m.tracks:
        t, on = 0, {}
        for msg in tr:
            t += msg.time
            if msg.type == 'note_on' and msg.velocity:
                on[msg.note] = (t, msg.velocity)
            elif msg.type in ('note_on', 'note_off') and msg.note in on:
                s, v = on.pop(msg.note)
                out.setdefault(tr.name, []).append((s, msg.note, v, t - s))
    return {k: sorted(v) for k, v in out.items()}


R_EXPORTS = sorted(glob.glob(os.path.join(PROBE, 'r*.mid')))


@pytest.mark.skipif(not R_EXPORTS, reason='local Reason probe fixtures not present')
@pytest.mark.parametrize('mid', R_EXPORTS, ids=os.path.basename)
def test_r_series_matches_reason_midi_export(mid):
    with open(mid[:-4] + '.reason', 'rb') as f:
        song, _ = rf.open_song(f.read())
    assert rendered(song) == exported(mid)


@pytest.mark.skipif(not R_EXPORTS, reason='local Reason probe fixtures not present')
def test_r_series_transport_tempo_and_signature_clips():
    with open(os.path.join(PROBE, 'r20.reason'), 'rb') as f:
        song, _ = rf.open_song(f.read())
    auto = [c for c in rf.tracks(song)[0].lanes[0].clips + rf.tracks(song)[0].lanes[1].clips if c.automation]
    tempo, sig = auto[0], auto[1]
    assert (tempo.info.start, tempo.info.length) == (8 * rf.PPQ, 64 * rf.PPQ)
    assert [(p.pos, p.value) for p in tempo.automation.points] == [(0, 120000), (8 * rf.PPQ, 90000)]
    assert (sig.info.start, sig.info.start + sig.info.length) == (16 * rf.PPQ, 73 * rf.PPQ)
    assert sig.automation.kind == 2 and sig.automation.points[0].value == 0x0403      # 3/4
