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
CHECK = os.path.join(os.path.dirname(__file__), '..', 'samples', 'reason-check')    # songs found in user checks
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


def lane_song(clips):
    """A one-track, one-lane song; clips: [(start, length, notes, muted, loop, loop_offset, note_flags)]."""
    lcfms = []
    for start, length, notes, muted, loop, offset, flags in clips:
        body = struct.pack('>I', len(notes))
        prev = 0
        for i, (pos, pitch, length_) in enumerate(notes):
            body += vlq((pos - prev) & 0xFFFFFFFF) + bytes([pitch, 100]) + vlq(length_) + bytes([flags[i] if flags else 0])
            prev = pos
        body += struct.pack('>I', 0)
        snic = rec(5, struct.pack('>II', start, length) + bytes(8) + s32('') + bytes([muted]) + b'\x0a\x01\x07'
                   + struct.pack('>Ii', loop, offset))
        lcfms.append(group(b'FORM', b'LCFM', chunk(b'LCAI', b'\0'), group(b'CAT ', b'SNCT', group(b'FORM', b'SNIF',
                     chunk(b'SNIC', snic), chunk(b'SNTE', rec(2, body))))))
    track = group(b'FORM', b'TRFM', chunk(b'TRDC', rec(5, bytes(6) + struct.pack('>H', 7) + bytes(14))),
                  group(b'CAT ', b'LNCT', group(b'FORM', b'LANF', chunk(b'LANC', rec(3, b'\x59' + s32('L') + b'\0')),
                        group(b'CAT ', b'LCCT', *lcfms))))
    devl = group(b'CAT ', b'DEVL', group(b'FORM', b'DEVI', chunk(b'DESC', rec(3, b'\xff' + struct.pack('>I', 7) + s32('T')))))
    body = b'RS1300' + b'\x1a' + bytes(121) + group(b'CAT ', b'RS10', devl, group(b'CAT ', b'SQCT', group(b'CAT ', b'TSCT', track)))
    form = group(b'FORM', b'X15S', chunk(b'BODY', body))
    stream = form + chunk(b'Hash', rec(1, hashlib.sha256(form).digest()))
    song, _ = rf.open_song(container({4: stream}, 5))
    return rf.played_notes(song)[0][1]


B = rf.PPQ


def test_overlapping_clips_later_start_wins_and_cuts_sounding_notes():
    played = lane_song([(0, 6 * B, [(0, 60, 6 * B), (3 * B, 61, B), (4 * B, 63, B)], False, 0, 0, None),
                        (2 * B, 2 * B, [(0, 62, B)], False, 0, 0, None)])
    # 60 is cut where the later clip starts; 61 lies under the cover; 63 after it plays
    assert played == [(0, 60, 100, 2 * B), (2 * B, 62, 100, B), (4 * B, 63, 100, B)]


def test_clip_end_does_not_cut_and_hidden_or_muted_notes_are_silent():
    played = lane_song([(4 * B, 2 * B, [(-B, 59, B), (0, 60, 4 * B), (B, 61, B), (3 * B, 62, B)], False, 0, 0,
                         [0, 0, 1, 0])])
    assert played == [(4 * B, 60, 100, 4 * B)]     # -1 beat hidden, 61 muted, 62 past the clip end


def test_a_restruck_pitch_ends_the_note_still_sounding():
    # Aug01: a 4-beat clip's 8-beat note ends where the next clip strikes the
    # same pitch; a note of another pitch rings on into the next clip.
    played = lane_song([(0, 4 * B, [(0, 60, 8 * B), (3 * B, 64, 3 * B)], False, 0, 0, None),
                        (4 * B, 4 * B, [(0, 60, B)], False, 0, 0, None)])
    assert played == [(0, 60, 100, 4 * B), (3 * B, 64, 100, 3 * B), (4 * B, 60, 100, B)]


def test_looping_clip_repeats_from_its_loop_offset():
    played = lane_song([(B, 7 * B, [(0, 60, B // 2), (B, 62, B // 2)], False, 2 * B, -B, None)])
    # passes start at 0, 2, 4, 6 beats; the note at pass start 0 falls before the clip
    assert [p for p, *_ in played] == [B, 2 * B, 3 * B, 4 * B, 5 * B, 6 * B, 7 * B]



def test_curvature_is_an_80_bit_float_and_curves_split_into_twelve_pieces():
    ext = lambda h: bytes.fromhex(h) + bytes(10 - len(bytes.fromhex(h)))
    # r26: slight up, full up, slight down, full down, full-curve fall
    assert [rf.curvature(ext(h)) for h in ('3ffe80', '4002c0', 'bfff80', 'c002c0')] == [0.5, 12.0, -1.0, -12.0]
    assert abs(rf.curvature(ext('4002bccccd')) - 11.8) < 1e-6 and rf.curvature(bytes(10)) == 0.0
    pts = rf.curved([(0, 0, 2.0), (12 * B, 120, 0.0)])
    assert len(pts) == 13 and pts[0][:3] == (0, 0, True) and pts[-1][:3] == (12 * B, 120, True)
    # join j sits where the slope 3(1 - x)^2 has fallen j/12 of the way to 0
    x1 = 1 - (11 / 12) ** 0.5
    assert pts[1][:3] == (round(x1 * 12 * B), round(120 * (1 - (1 - x1) ** 3)), True)
    # slow-first: a repeated join value still shapes the steps but is not sent
    flat = rf.curved([(0, 0, -12.0), (4 * B, 2, 0.0)])
    assert any(not p[2] for p in flat)
    steps = rf.stepped(flat)
    assert steps[0] == (0, 0) and steps[-1] == (4 * B, 2)
    assert [v for _, v in steps] == sorted(v for _, v in steps)


def block_song(placements, mutes, blocks_on=True):
    """Transport track with Block placements [(start, length)] (all Block 1,
    offset 0), and one instrument track whose Block 1 clip holds notes at 0
    and 2 beats. mutes: [(track, note lane, placement record)] for SMGC."""
    def snif(snic, extra):
        return group(b'FORM', b'SNIF', chunk(b'SNIC', snic), extra)

    def trfm(device, kind, lcai, snifs):
        return group(b'FORM', b'TRFM', chunk(b'TRDC', rec(5, bytes(6) + struct.pack('>H', device) + bytes(14))),
                     group(b'CAT ', b'LNCT', group(b'FORM', b'LANF', chunk(b'LANC', rec(3, kind + s32('') + b'\0')),
                           group(b'CAT ', b'LCCT', group(b'FORM', b'LCFM', chunk(b'LCAI', lcai),
                                 group(b'CAT ', b'SNCT', *snifs))))))
    transport = trfm(1, b'\x5d', b'\0', [snif(clip_rec(s, n), chunk(b'SBLK', rec(1, struct.pack('>Hi', 0, 0))))
                                          for s, n in placements])
    inst = trfm(7, b'\x59', b'\x01', [snif(clip_rec(0, 4 * B), chunk(b'SNTE', notes_rec([(0, 60, 100, B),
                                                                                          (2 * B, 62, 100, B)])))])
    smgc = group(b'CAT ', b'SMGC', *(group(b'FORM', b'MGDF',
                 chunk(b'RLRF', rec(1, struct.pack('>IBi', t, 0x59, ln))),
                 chunk(b'RSRF', rec(1, struct.pack('>I', r)))) for t, ln, r in mutes))
    seq = group(b'CAT ', b'SQCT', chunk(b'TRDC', rec(5, bytes(4) + bytes([blocks_on, 0, 0]))),
                group(b'CAT ', b'TSCT', transport, inst), smgc)
    devl = group(b'CAT ', b'DEVL', *(group(b'FORM', b'DEVI', chunk(b'DESC', rec(3, b'\xff' + struct.pack('>I', d) + s32(n))))
                                    for d, n in ((1, 'Transport'), (7, 'Keys'))))
    body = b'RS1300' + b'\x1a' + bytes(121) + group(b'CAT ', b'RS10', devl, seq)
    form = group(b'FORM', b'X15S', chunk(b'BODY', body))
    song, _ = rf.open_song(container({4: form + chunk(b'Hash', rec(1, hashlib.sha256(form).digest()))}, 5))
    return [p for p, *_ in rf.played_notes(song)[1][1]]


def test_block_placements_play_their_block_and_per_placement_mutes_silence_a_lane():
    places = [(0, 4 * B), (4 * B, 4 * B), (4 * B, 4 * B), (8 * B, 4 * B), (8 * B, 4 * B), (12 * B, 4 * B)]
    assert block_song(places, []) == [0, 2 * B, 4 * B, 6 * B, 8 * B, 10 * B, 12 * B, 14 * B]   # twins play once
    # record 0 muted; the later twin of beat 4 muted (silent); the earlier twin of beat 8 muted (later covers: plays)
    assert block_song(places, [(1, 0, 0), (1, 0, 2), (1, 0, 3)]) == [8 * B, 10 * B, 12 * B, 14 * B]
    assert block_song(places, [(1, 1, 0), (2, 0, 0)]) == block_song(places, [])     # other lanes and tracks
    assert block_song(places, [], blocks_on=False) == []

# ---------------------------------------------------------------- r-series against Reason's exports

def rendered(song):
    return {t.name: notes for t, notes in rf.played_notes(song) if notes}


def exported(path):
    out = {}
    m = mido.MidiFile(path)
    assert m.ticks_per_beat == rf.PPQ
    for tr in m.tracks:
        t, on = 0, {}
        for msg in tr:
            t += msg.time
            if msg.type == 'note_on' and msg.velocity:
                on.setdefault(msg.note, []).append((t, msg.velocity))
            elif msg.type in ('note_on', 'note_off') and on.get(msg.note):
                s, v = on[msg.note].pop(0)
                out.setdefault(tr.name, []).append((s, msg.note, v, t - s))
    return {k: sorted(v) for k, v in out.items()}


KNOWN_GAPS: dict[str, str] = {}
R_EXPORTS = sorted(m for root in (PROBE, CHECK) for m in glob.glob(os.path.join(root, '**', '*.mid'), recursive=True)
                   if os.path.exists(m[:-4] + '.reason'))


@pytest.mark.skipif(not R_EXPORTS, reason='local Reason probe fixtures not present')
@pytest.mark.parametrize('mid', R_EXPORTS, ids=lambda m: os.path.relpath(m, PROBE))
def test_r_series_matches_reason_midi_export(mid):
    gap = KNOWN_GAPS.get(os.path.basename(mid))
    if gap:
        pytest.xfail(gap)
    with open(mid[:-4] + '.reason', 'rb') as f:
        song, _ = rf.open_song(f.read())
    assert same_notes(rendered(song), exported(mid))


def same_notes(a, b):
    """Equal per track, allowing notes that share start and pitch to pair
    their velocities and lengths either way (a MIDI file can't tell)."""
    def key(d):
        return {k: (sorted(n[:3] for n in v), sorted((n[0], n[1], n[3]) for n in v)) for k, v in d.items() if v}
    return key(a) == key(b)


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


def test_controller_resting_values_from_trsc():
    # mute-tests' OVERLAY WITH MUTE: sustain rests at 79; r16: mod wheel and pitch bend at 0
    assert rf.controller_rest(bytes.fromhex('00000001 0040 0000004f 01 00000000 0000007f')) == {0x40: 79}
    assert rf.controller_rest(bytes.fromhex('00000002 0001 00000000 00 00000000 0000007f'
                                            '00ff 00000000 00 ffffe000 00001fff')) == {0x01: 0, 0xFF: 0}
    assert rf.controller_rest(b'\0\0\0\0') == {} and rf.controller_rest(b'') == {}
