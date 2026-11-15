"""Decode Reason song files (.reason saved by Reason 13 and 14).

Pure format decoding, no workspace model. tools/reason_inspect.py is the
research CLI; findings and evidence are in docs/plans/reason-import.md.
Input files are only read.

Container ("X15_FILE"): a small paged store. Big-endian throughout.
  header  'X15_FILE' | u32 page size (0x40000) | u32 0x24 | u64 a
          | u64 index hint | 5 x u32 (not decoded)
  pages   start at byte 52; unused page bytes are 0xFE.
  index   a page starting with 8 x 0xFF | u32 count | count entries of
          (u32 stream id | u64 byte size | u64 page count | u64 pages...
          | u32 0xC0CAC01A) | u32 0xB0BAFE77
Stream 1 is the song: an IFF 'FORM' 'X15S' chunk followed by a 'Hash' chunk
whose last 32 bytes are the SHA-256 of the whole FORM chunk. Other streams
hold embedded samples.

A save writes a new song stream and a new index to free pages; the old ones
stay until their pages are reused, so a file can hold two complete,
hash-verified songs. The newest is taken to be the one indexed on the highest
page (see current_song). The header's u64 at offset 24 names one of the
index pages, but not reliably the newest.

Song FORM: CAT WWWI (metadata) | CAT ApVC | FORM REMB | BODY | ...
BODY: a 128-byte header whose first six bytes name the format generation,
then IFF. Only 'RS1300' (Reason 13 and 14) is plain; earlier generations
(RSN600 .. RS1250) are encrypted and are not read.

Record chunks inside the song mostly start 0xBC | version | 3 bytes; the
fields below are offsets into the chunk body. Times are ticks at 15360 PPQ.
Note positions and lengths use MSB-first 7-bit varints (as in MIDI files).
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field

MAGIC = b'X15_FILE'
HEADER_SIZE = 52
INDEX_MARK = b'\xff' * 8
ENTRY_END = 0xC0CAC01A
SONG_STREAM = 1
PLAIN_GENERATION = b'RS1300'
PPQ = 15360
GROUPS = (b'FORM', b'CAT ', b'LIST')


class ReasonFormatError(ValueError):
    pass


# ---------------------------------------------------------------- container

@dataclass
class Header:
    page_size: int
    a: int
    index_hint: int      # u64 at offset 24; an index page, not reliably the newest


def read_header(data: bytes) -> Header:
    if data[:8] != MAGIC or len(data) < HEADER_SIZE:
        raise ReasonFormatError('not a Reason song file (no X15_FILE header)')
    page_size, _, a, hint = struct.unpack('>IIQQ', data[8:32])
    if page_size <= 0 or page_size & (page_size - 1):
        raise ReasonFormatError(f'unexpected page size {page_size}')
    return Header(page_size, a, hint)


def page_count(data: bytes, h: Header) -> int:
    return (len(data) - HEADER_SIZE) // h.page_size


def page(data: bytes, h: Header, n: int) -> bytes:
    o = HEADER_SIZE + n * h.page_size
    return data[o:o + h.page_size]


def read_index(data: bytes, h: Header, n: int) -> dict[int, tuple[int, list[int]]]:
    """{stream id: (byte size, [pages])} from index page n."""
    pg = page(data, h, n)
    if pg[:8] != INDEX_MARK:
        raise ReasonFormatError(f'page {n} is not an index')
    p = 8
    (count,) = struct.unpack_from('>I', pg, p)
    p += 4
    out = {}
    npages = page_count(data, h)
    for _ in range(count):
        sid, size, np_ = struct.unpack_from('>IQQ', pg, p)
        p += 20
        if np_ * 8 + p + 4 > len(pg) or size > np_ * h.page_size:
            raise ReasonFormatError(f'bad index entry on page {n}')
        pages = list(struct.unpack_from(f'>{np_}Q', pg, p))
        p += 8 * np_
        (end,) = struct.unpack_from('>I', pg, p)
        p += 4
        if end != ENTRY_END or any(x >= npages for x in pages):
            raise ReasonFormatError(f'bad index entry on page {n}')
        out[sid] = (size, pages)
    return out


def read_stream(data: bytes, h: Header, size: int, pages: list[int]) -> bytes:
    return b''.join(page(data, h, n) for n in pages)[:size]


def song_hash_ok(stream: bytes) -> bool:
    if stream[:4] != b'FORM' or stream[8:12] != b'X15S':
        return False
    (n,) = struct.unpack_from('>I', stream, 4)
    tail = stream[8 + n:8 + n + 45]
    return tail[:4] == b'Hash' and len(tail) == 45 and hashlib.sha256(stream[:8 + n]).digest() == tail[13:]


@dataclass
class SongCopy:
    index_page: int
    pages: list[int]
    stream: bytes


def verified_songs(data: bytes, h: Header | None = None) -> list[SongCopy]:
    h = h or read_header(data)
    out = []
    for n in range(page_count(data, h)):
        if page(data, h, n)[:8] != INDEX_MARK:
            continue
        try:
            idx = read_index(data, h, n)
        except (ReasonFormatError, struct.error):
            continue
        if SONG_STREAM not in idx:
            continue
        size, pages = idx[SONG_STREAM]
        s = read_stream(data, h, size, pages)
        if song_hash_ok(s):
            out.append(SongCopy(n, pages, s))
    return out


def current_song(data: bytes) -> tuple[SongCopy, list[str]]:
    """The current save's song stream, and notes about how it was chosen.

    Rule (provisional): of the hash-verified copies, the one whose index is
    on the highest page. It holds for every two-copy file whose newer save is
    known (the r-series against their MIDI exports, a folders/no-folders pair,
    files mixing an older Reason's copy with a 13/14 copy). The header's index
    pointer does not decide it: it names the older copy in some files and the
    newer in others."""
    h = read_header(data)
    copies = verified_songs(data, h)
    if not copies:
        raise ReasonFormatError('no intact song found in this file')
    pick = max(copies, key=lambda c: c.index_page)
    notes = [] if len(copies) == 1 else [f'{len(copies)} saved copies; using the one indexed on page {pick.index_page}']
    return pick, notes


# ---------------------------------------------------------------- IFF

@dataclass
class Chunk:
    id: str
    pos: int                 # offset of the chunk header in its stream
    size: int
    sub: str | None = None   # FORM/CAT/LIST type
    kids: list['Chunk'] = field(default_factory=list)

    @property
    def start(self) -> int:  # body start (after a group's type field)
        return self.pos + (12 if self.sub is not None else 8)

    @property
    def end(self) -> int:
        return self.pos + 8 + self.size

    @property
    def name(self) -> str:
        return f'{self.id.strip()}:{self.sub.strip()}' if self.sub is not None else self.id.strip()

    def find(self, *path: str) -> 'Chunk | None':
        """First descendant along names like 'CAT:SQCT', 'TRDC'."""
        node = self
        for step in path:
            node = next((k for k in node.kids if k.name == step), None)
            if node is None:
                return None
        return node

    def all(self, name: str) -> list['Chunk']:
        return [k for k in self.kids if k.name == name]


def parse_chunks(data: bytes, start: int, end: int) -> list[Chunk]:
    out = []
    p = start
    while p + 8 <= end:
        cid = data[p:p + 4]
        (n,) = struct.unpack_from('>I', data, p + 4)
        if not all(32 <= b < 127 for b in cid) or p + 8 + n > end:
            raise ReasonFormatError(f'bad chunk at {p}')
        c = Chunk(cid.decode('ascii'), p, n)
        if cid in GROUPS and n >= 4:
            c.sub = data[p + 8:p + 12].decode('latin-1')
            try:
                c.kids = parse_chunks(data, p + 12, p + 8 + n)
            except ReasonFormatError:
                c.kids = []          # a group whose body isn't IFF (e.g. REMB)
        out.append(c)
        p += 8 + n + (n & 1)
    return out


@dataclass
class Song:
    stream: bytes
    top: list[Chunk]
    metadata: dict[str, str]
    generation: str
    body: list[Chunk]        # children of CAT RS10 (empty unless plain)

    def bytes_of(self, c: Chunk) -> bytes:
        return self.stream[c.start:c.end]

    def rs10(self, *path: str) -> Chunk | None:
        root = Chunk('CAT ', 0, 0, 'RS10', self.body)
        return root.find(*path)


def _metadata(stream: bytes, cat: Chunk) -> dict[str, str]:
    out = {}
    for form in cat.kids:
        wid = next((k for k in form.kids if k.id == 'WWID'), None)
        val = next((k for k in form.kids if k.id == 'BODY'), None)
        if wid is None or val is None:
            continue
        w = stream[wid.start:wid.end]
        (kn,) = struct.unpack_from('>I', w, 6)
        key = w[10:10 + kn].decode('latin-1')
        v = stream[val.start:val.end]
        (vn,) = struct.unpack_from('>I', v, 0)
        out[key] = v[4:4 + vn].decode('utf-8', 'replace')
    return out


def read_song(stream: bytes) -> Song:
    (n,) = struct.unpack_from('>I', stream, 4)
    top = parse_chunks(stream, 12, 8 + n)
    cat = next((c for c in top if c.name == 'CAT:WWWI'), None)
    meta = _metadata(stream, cat) if cat else {}
    body = next((c for c in top if c.id == 'BODY'), None)
    if body is None:
        raise ReasonFormatError('song has no BODY')
    gen = stream[body.start:body.start + 6].decode('latin-1')
    kids = []
    if stream[body.start:body.start + 6] == PLAIN_GENERATION:
        rs = parse_chunks(stream, body.start + 128, body.end)
        root = next((c for c in rs if c.name == 'CAT:RS10'), None)
        kids = root.kids if root else []
    return Song(stream, top, meta, gen, kids)


def generation_version(gen: str) -> str:
    """'RS1200' -> '12', 'RSN900' -> '9', 'RS1250' -> '12.5' (best effort)."""
    digits = ''.join(ch for ch in gen if ch.isdigit())
    if len(digits) == 4:
        major, minor = int(digits[:2]), int(digits[2])
    elif len(digits) == 3:
        major, minor = int(digits[0]), int(digits[1])
    else:
        return gen
    if major == 99 or (major == 9 and minor == 9):
        return '9.5'
    return f'{major}.{minor}' if minor else str(major)


# ---------------------------------------------------------------- records

def varint(b: bytes, p: int) -> tuple[int, int]:
    v = 0
    while True:
        x = b[p]
        p += 1
        v = (v << 7) | (x & 0x7F)
        if not x & 0x80:
            return v, p


def wrap32(v: int) -> int:
    """Running positions are 32-bit two's complement: a note before its clip's
    start (left by a split or trim) has a negative offset."""
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


def _str32(b: bytes, p: int) -> tuple[str, int]:
    (n,) = struct.unpack_from('>I', b, p)
    return b[p + 4:p + 4 + n].decode('utf-8', 'replace'), p + 4 + n


@dataclass
class Note:
    pos: int        # ticks from the clip start; negative = before it (hidden)
    pitch: int
    velocity: int
    length: int
    extra: int      # flags after the length: bit 0 = muted note


@dataclass
class Point:
    pos: int        # ticks from the clip start
    value: int
    rest: bytes     # 10 bytes after the value (zero so far: linear)


@dataclass
class ControllerLane:
    lane_id: int    # 0x01 mod wheel, 0xFF pitch bend (others to confirm)
    head: bytes     # the bytes around the id, kept for research
    lo: int
    hi: int
    points: list[Point]


def _points(b: bytes, p: int, count: int) -> tuple[list[Point], int]:
    out = []
    pos = 0
    for _ in range(count):
        d, p = varint(b, p)
        pos = wrap32(pos + d)
        (v,) = struct.unpack_from('>i', b, p)
        out.append(Point(pos, v, b[p + 4:p + 14]))
        p += 14
    return out, p


def decode_notes(b: bytes) -> tuple[list[Note], list[ControllerLane], bytes]:
    """SNTE: u32 note count at 5, notes, then u32 controller lane count, lanes
    (3-byte head with the lane id in the middle, i32 min, i32 max, u32 count,
    points).
    Returns (notes, controller lanes, unparsed tail)."""
    (count,) = struct.unpack_from('>I', b, 5)
    p = 9
    notes = []
    pos = 0
    for _ in range(count):
        d, p = varint(b, p)
        pos = wrap32(pos + d)
        pitch, vel = b[p], b[p + 1]
        length, p = varint(b, p + 2)
        notes.append(Note(pos, pitch, vel, length, b[p]))
        p += 1
    lanes = []
    if p + 4 <= len(b):
        (nl,) = struct.unpack_from('>I', b, p)
        p += 4
        for _ in range(nl):
            head = b[p:p + 3]
            lo, hi, npts = struct.unpack_from('>iiI', b, p + 3)
            pts, p = _points(b, p + 15, npts)
            lanes.append(ControllerLane(head[1], head, lo, hi, pts))
    return notes, lanes, b[p:]


@dataclass
class Automation:
    kind: int       # 0 tempo, 2 time signature (others to confirm)
    lo: int
    hi: int
    points: list[Point]


def decode_automation(b: bytes) -> Automation:
    """SAUT: u8 kind at 5, i32 min, i32 max, u32 count, points."""
    kind = b[5]
    lo, hi, n = struct.unpack_from('>iiI', b, 6)
    pts, _ = _points(b, 18, n)
    return Automation(kind, lo, hi, pts)


@dataclass
class ClipInfo:
    start: int      # ticks, song position (block-relative inside a Block)
    length: int
    name: str
    muted: bool
    loop: int = 0   # loop length in ticks; 0 = the content plays once
    loop_offset: int = 0  # where the first loop pass starts, from the clip start (<= 0 after a start trim)


def decode_clip(b: bytes) -> ClipInfo:
    """SNIC: u32 start at 5, u32 length at 9, 8 bytes, str32 name at 21, u8 mute,
    3 bytes, u32 loop length (0 = no loop), i32 loop offset."""
    start, length = struct.unpack_from('>II', b, 5)
    name, p = _str32(b, 21)
    loop, offset = struct.unpack_from('>Ii', b, p + 4) if p + 12 <= len(b) else (0, 0)
    return ClipInfo(start, length, name, bool(b[p]), loop, offset)


LANE_NOTES = 0x59


@dataclass
class LaneInfo:
    kind: int       # 0x59 note lane, 0x5A pattern lane, 0x5B/0x5D automation
    name: str
    muted: bool


def decode_lane(b: bytes) -> LaneInfo:
    """LANC: u8 kind at 5, str32 name at 6, u8 mute."""
    name, p = _str32(b, 6)
    return LaneInfo(b[5], name, bool(b[p]) if p < len(b) else False)


@dataclass
class TrackInfo:
    device: int     # id of the rack device the track plays (0 for none)
    muted: bool
    kind: int       # 0x0A instrument, 0x0B pattern device (to confirm)


def decode_track(b: bytes) -> TrackInfo:
    """Track TRDC: u16 device id at 11, u8 mute at 13, u8 kind at 18."""
    (dev,) = struct.unpack_from('>H', b, 11)
    return TrackInfo(dev, bool(b[13]), b[18])


def device_names(song: Song) -> dict[int, str]:
    """{device id: device (track) name} from the rack's DEVI/DESC records."""
    out = {}
    devl = song.rs10('CAT:DEVL')
    for dev in (devl.kids if devl else []):
        desc = next((k for k in dev.kids if k.id == 'DESC'), None)
        if desc is None:
            continue
        b = song.bytes_of(desc)
        try:
            (did,) = struct.unpack_from('>I', b, 6)
            name, _ = _str32(b, 10)
        except struct.error:
            continue
        out[did] = name
    return out


@dataclass
class Clip:
    info: ClipInfo
    block: int                      # LCAI: 0 = song, n = Block n
    kind: str                       # 'notes', 'automation', 'pattern', 'block', '?'
    notes: list[Note] = field(default_factory=list)
    controllers: list[ControllerLane] = field(default_factory=list)
    automation: Automation | None = None
    placed_block: int = 0           # Block placement (SBLK): which Block, 1-based
    placed_offset: int = 0          # where in the Block it starts playing (<= 0)


@dataclass
class Lane:
    info: LaneInfo
    clips: list[Clip]


@dataclass
class Track:
    index: int
    info: TrackInfo
    name: str
    lanes: list[Lane]
    folder: tuple[str, ...] = ()    # enclosing folder names (Reason 14), outermost first


def _clip(song: Song, lcfm: Chunk) -> list[Clip]:
    lcai = next((k for k in lcfm.kids if k.id == 'LCAI'), None)
    block = song.bytes_of(lcai)[0] if lcai is not None and lcai.size else 0
    snct = lcfm.find('CAT:SNCT')
    out = []
    for snif in (snct.kids if snct else []):
        rec = {k.id: song.bytes_of(k) for k in snif.kids}
        if 'SNIC' not in rec:
            continue
        c = Clip(decode_clip(rec['SNIC']), block, '?')
        if 'SNTE' in rec:
            c.kind = 'notes'
            c.notes, c.controllers, _ = decode_notes(rec['SNTE'])
        elif 'SAUT' in rec:
            c.kind, c.automation = 'automation', decode_automation(rec['SAUT'])
        elif 'SPTN' in rec:
            c.kind = 'pattern'
        elif 'SBLK' in rec:
            c.kind = 'block'
            b = rec['SBLK']
            (c.placed_block,) = struct.unpack_from('>H', b, 5)
            c.placed_block += 1                     # stored 0-based; LCAI counts from 1
            (c.placed_offset,) = struct.unpack_from('>i', b, 7)
        out.append(c)
    return out


def _track(song: Song, trfm: Chunk, index: int, names: dict[int, str], folder: tuple[str, ...]) -> Track:
    trdc = next((k for k in trfm.kids if k.id == 'TRDC'), None)
    info = decode_track(song.bytes_of(trdc)) if trdc is not None else TrackInfo(0, False, 0)
    lanes = []
    lnct = trfm.find('CAT:LNCT')
    for lanf in (lnct.kids if lnct else []):
        lanc = next((k for k in lanf.kids if k.id == 'LANC'), None)
        linfo = decode_lane(song.bytes_of(lanc)) if lanc is not None else LaneInfo(0, '', False)
        lcct = lanf.find('CAT:LCCT')
        clips = [c for lcfm in (lcct.kids if lcct else []) for c in _clip(song, lcfm)]
        lanes.append(Lane(linfo, clips))
    return Track(index, info, names.get(info.device, ''), lanes, folder)


def folder_name(b: bytes) -> str:
    """TFDC: str32 folder name at 5."""
    return _str32(b, 5)[0]


def tracks(song: Song) -> list[Track]:
    """Sequencer tracks in order. Reason 14 nests them in folders
    (TTCT > TFFM 'Root' > TFCT > TRFM or TFFM ...); Reason 13 lists them in TSCT."""
    names = device_names(song)
    out: list[Track] = []

    def walk(container: Chunk | None, folder: tuple[str, ...]) -> None:
        for k in (container.kids if container else []):
            if k.name == 'FORM:TRFM':
                out.append(_track(song, k, len(out), names, folder))
            elif k.name == 'FORM:TFFM':
                tfdc = next((x for x in k.kids if x.id == 'TFDC'), None)
                name = folder_name(song.bytes_of(tfdc)) if tfdc is not None else ''
                walk(k.find('CAT:TFCT'), folder + (name,) if folder or name != 'Root' else folder)

    sq = song.rs10('CAT:SQCT')
    if sq is not None and sq.find('CAT:TTCT') is not None:
        walk(sq.find('CAT:TTCT'), ())
    elif sq is not None:
        walk(sq.find('CAT:TSCT'), ())
    return out


# ---------------------------------------------------------------- playback rules

def _cut(segs, s2, e2):
    """Remove [s2, e2) from segments [(start, end, cuts_notes)]. An end made by
    a covering clip cuts sounding notes; a clip's own end does not."""
    out = []
    for a, b, hard in segs:
        if a < min(b, s2):
            out.append((a, min(b, s2), True if s2 < b else hard))
        if max(a, e2) < b:
            out.append((max(a, e2), b, hard))
    return out


def _visible(windows):
    """Overlapping clips on one lane: a later start wins (ties: later in the
    lane). Returns each window's visible segments."""
    out = []
    for i, (s, e) in enumerate(windows):
        segs = [(s, e, False)]
        for j, (s2, e2) in enumerate(windows):
            if j != i and (s2 > s or (s2 == s and j > i)):
                segs = _cut(segs, s2, e2)
        out.append(segs)
    return out


PlayedNote = tuple[int, int, int, int]      # (song tick, pitch, velocity, length)


def played_notes(song: Song) -> list[tuple[Track, list[PlayedNote]]]:
    """The notes each track plays, as Reason's own MIDI export renders them.

    Rules (each checked against Reason's exports; see the plan):
    - muted clips, muted lanes and muted notes (flag bit 0) are silent; track
      mute and solo are not applied (Reason's export ignores them);
    - a note sounds if its start lies in the visible part of its clip: inside
      the clip, not covered by a later-starting clip on the same lane, and not
      before the clip start (offsets left negative by splits and trims);
    - a covering clip cuts notes still sounding where it starts; a clip's own
      end does not cut them;
    - looping clips repeat their first `loop` ticks from start + loop_offset;
    - when the Blocks switch is on, each unmuted Block placement on the
      Transport track plays its Block's clips from the placement's offset into
      the Block, within the placement; song clips on the same lane cover them
      (user: empty clips are used to silence a Block locally);
    - a note lane's Block content can be muted at single placements (SMGC,
      see block_mutes); identical duplicate placements play once, and as with
      overlapping clips the later copy covers the earlier, so its mute counts.
    """
    ts = tracks(song)
    places: dict[tuple, list[int]] = {}         # placement -> its record numbers
    first: dict[tuple, Clip] = {}
    if blocks_enabled(song):
        n = -1
        for t in ts:
            for ln in t.lanes:
                for c in (c for c in ln.clips if c.kind == 'block'):
                    n += 1                              # record number, as SMGC counts them
                    if ln.info.muted:
                        continue
                    key = (c.info.start, c.info.length, c.placed_block, c.placed_offset)
                    first.setdefault(key, c)
                    places.setdefault(key, []).append(-1 if c.info.muted else n)   # -1: muted
    mutes = block_mutes(song)
    result = []
    for t in ts:
        out: list[PlayedNote] = []
        note_lane = -1
        for ln in t.lanes:
            if ln.info.kind == LANE_NOTES:
                note_lane += 1
            if ln.info.muted:
                continue
            songs, blocks = [], []
            for c in ln.clips:
                if c.kind != 'notes' or c.info.muted:
                    continue
                if not c.block:
                    songs.append((c.info.start, c.info.start + c.info.length, c, 0))
                    continue
                for key, recs in places.items():
                    p = first[key]
                    if p.placed_block != c.block:
                        continue
                    if recs[-1] < 0 or (t.index, note_lane, recs[-1]) in mutes:   # a later twin covers
                        continue
                    base = p.info.start + p.placed_offset      # where the Block's beat 0 falls
                    s = max(base + c.info.start, p.info.start)
                    e = min(base + c.info.start + c.info.length, p.info.start + p.info.length)
                    if s < e:
                        blocks.append((s, e, c, base))
            seg_song = _visible([(a, b) for a, b, _, _ in songs])
            seg_block = []
            for a, b, _, _ in blocks:
                segs = [(a, b, False)]
                for s2, e2, _, _ in songs:
                    segs = _cut(segs, s2, e2)
                seg_block.append(segs)
            for (_, _, c, base), segs in list(zip(songs, seg_song)) + list(zip(blocks, seg_block)):
                origin = base + c.info.start
                loop = c.info.loop
                shift = c.info.loop_offset if loop else 0
                reps = range(-(-(c.info.length - shift) // loop)) if loop else (0,)
                for u, v, hard in segs:
                    for n in c.notes:
                        if n.extra & 1 or (loop and not 0 <= n.pos < loop):
                            continue
                        for k in reps:
                            at = origin + shift + n.pos + k * loop
                            if u <= at < v:
                                out.append((at, n.pitch, n.velocity, min(n.length, v - at) if hard else n.length))
        result.append((t, sorted(out)))
    return result


def block_mutes(song: Song) -> set[tuple[int, int, int]]:
    """Block content muted at single placements: (track index, note-lane
    index, placement record number). CAT:SMGC holds one FORM MGDF per muted
    spot: RLRF has the track at u32 5, the lane kind at 9 and the lane's index
    among the track's note lanes at u32 10 (-1 for pattern lanes); RSRF has
    the placement's record number on the Transport lane at u32 5, duplicates
    counted. Verified on dec2024-27-02 against Reason's export."""
    out: set[tuple[int, int, int]] = set()

    def find(chunks):
        for c in chunks:
            if c.name == 'CAT:SMGC':
                return c
            r = find(c.kids)
            if r is not None:
                return r
        return None

    smgc = find(song.body)
    for mgdf in (smgc.kids if smgc is not None else []):
        rec = {k.id: song.bytes_of(k) for k in mgdf.kids}
        lr, sr = rec.get('RLRF', b''), rec.get('RSRF', b'')
        if len(lr) < 14 or len(sr) < 9 or lr[9] != LANE_NOTES:
            continue
        (track,) = struct.unpack_from('>I', lr, 5)
        (lane,) = struct.unpack_from('>i', lr, 10)
        (place,) = struct.unpack_from('>I', sr, 5)
        out.add((track, lane, place))
    return out


def blocks_enabled(song: Song) -> bool:
    """The Blocks switch: third byte from the end of the sequencer's TRDC
    (1 in songs whose export plays Blocks, 0 in one whose export doesn't)."""
    trdc = song.rs10('CAT:SQCT', 'TRDC')
    b = song.bytes_of(trdc) if trdc is not None else b''
    return len(b) >= 3 and bool(b[-3])


def open_song(data: bytes) -> tuple[Song, list[str]]:
    copy, notes = current_song(data)
    return read_song(copy.stream), notes
