"""Decode Reason song files (.reason saved by Reason 13 and 14).

Pure format decoding, no workspace model. tools/reason_inspect.py is the
research CLI; findings and evidence are in docs/plans/0.4.0/reason-import.md.
Input files are only read.

Container ("X15_FILE"): a small paged store. Big-endian throughout.
  header  'X15_FILE' | u32 page size (0x40000) | u32 0x24
          | two 18-byte slots (offsets 16 and 34), each: u64 generation
            | u64 index page | u16 CRC-16/XMODEM of those 16 bytes
  pages   start at byte 52; unused page bytes are 0xFE.
  index   a page starting with 8 x 0xFF | u32 count | count entries of
          (u32 stream id | u64 byte size | u64 page count | u64 pages...
          | u32 0xC0CAC01A) | u32 0xB0BAFE77
Stream 1 is the song: an IFF 'FORM' 'X15S' chunk followed by a 'Hash' chunk
whose last 32 bytes are the SHA-256 of the whole FORM chunk. Other streams
hold embedded samples.

A save writes a new song stream and a new index to free pages (lowest free
pages first, so successive saves alternate between two page sets); the old ones
stay until their pages are reused, so a file can hold two complete,
hash-verified songs. Each save also writes the next generation number into the
header slot it is not using: the slot with the higher generation names the
current save's index page (see current_song and
docs/investigation/formats/REASON_FILE_FORMAT.md).

Song FORM: CAT WWWI (metadata) | CAT ApVC | FORM REMB | BODY | ...
BODY: a 128-byte header whose first six bytes name the format generation,
then IFF. Only 'RS1300' (Reason 13 and 14) is plain; earlier generations
(RSN600 .. RS1250) are encrypted and are not read.

Record chunks inside the song mostly start 0xBC | version | 3 bytes; the
fields below are offsets into the chunk body. Times are ticks at 15360 PPQ.
Note positions and lengths use MSB-first 7-bit varints (as in MIDI files).
"""

from __future__ import annotations

import bisect
import hashlib
import math
import struct
from dataclasses import dataclass, field
from fractions import Fraction

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

SLOT_OFFSETS = (16, 34)


def crc16_xmodem(b: bytes) -> int:
    crc = 0
    for x in b:
        crc ^= x << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


@dataclass
class Slot:
    generation: int
    index_page: int
    valid: bool          # the slot's CRC-16 matches its 16 bytes


@dataclass
class Header:
    page_size: int
    slots: tuple[Slot, ...]

    @property
    def a(self) -> int:              # slot 0's generation (the u64 at offset 16)
        return self.slots[0].generation

    @property
    def index_hint(self) -> int:     # slot 0's index page (the u64 at offset 24): NOT the current save
        return self.slots[0].index_page


def read_header(data: bytes) -> Header:
    if data[:8] != MAGIC or len(data) < HEADER_SIZE:
        raise ReasonFormatError('not a Reason song file (no X15_FILE header)')
    page_size, _ = struct.unpack('>II', data[8:16])
    if page_size <= 0 or page_size & (page_size - 1):
        raise ReasonFormatError(f'unexpected page size {page_size}')
    slots = []
    for off in SLOT_OFFSETS:
        generation, index_page, check = struct.unpack('>QQH', data[off:off + 18])
        slots.append(Slot(generation, index_page, crc16_xmodem(data[off:off + 16]) == check))
    return Header(page_size, tuple(slots))


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

    The header's two slots each hold a generation and an index page with a
    CRC-16; each save writes the next generation into the slot it is not
    using, so the valid slot with the highest generation names the current
    save. If that slot names no hash-verified copy (a damaged or unfinished
    save), the next-highest slot is tried, then, failing that, the verified
    copy whose index is on the highest page. A file with one verified copy
    just uses it.

    Evidence: docs/investigation/formats/REASON_FILE_FORMAT.md. Not yet confirmed: that
    Reason itself picks this way, and what it does when the newer slot is damaged."""
    h = read_header(data)
    copies = verified_songs(data, h)
    if not copies:
        raise ReasonFormatError('no intact song found in this file')
    if len(copies) == 1:
        return copies[0], []
    by_page = {c.index_page: c for c in copies}
    ranked = sorted((sl for sl in h.slots if sl.valid), key=lambda sl: sl.generation, reverse=True)
    for rank, sl in enumerate(ranked):
        if sl.index_page in by_page:
            note = (f'{len(copies)} saved copies; using the one the header names as current '
                    f'(generation {sl.generation}, index page {sl.index_page})')
            if rank:
                note += '; the newest header slot names no intact copy'
            return by_page[sl.index_page], [note]
    pick = max(copies, key=lambda c: c.index_page)
    return pick, [f'{len(copies)} saved copies; the header names none of them, so using the one indexed on '
                  f'page {pick.index_page}']


def unverified_song(data: bytes) -> Song | None:
    """The song stream of a file with no hash-verified copy, read for its
    generation and metadata only (Reason 10 and earlier saves have no Hash
    chunk). None if no index names a song stream starting FORM X15S."""
    h = read_header(data)
    for n in range(page_count(data, h) - 1, -1, -1):
        if page(data, h, n)[:8] != INDEX_MARK:
            continue
        try:
            idx = read_index(data, h, n)
            if SONG_STREAM in idx:
                s = read_stream(data, h, *idx[SONG_STREAM])
                if s[:4] == b'FORM' and s[8:12] == b'X15S':
                    return read_song(s)
        except (ReasonFormatError, struct.error, IndexError):
            continue
    return None


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
    rest: bytes     # 10 bytes after the value: the curve (see curvature)

    @property
    def curve(self) -> float:
        return curvature(self.rest)


def curvature(b: bytes) -> float:
    """A point's curve toward the next point: an 80-bit extended float
    (sign and 15-bit exponent, then a 64-bit mantissa with explicit integer
    bit). 0 = straight; positive bends fast-first, negative slow-first. Reason's
    curve handle spans about -12..12 (r26: slight up 0.5, full up 12, slight
    down -1, full down -12)."""
    if len(b) < 10:
        return 0.0
    se, m = struct.unpack_from('>HQ', b, 0)
    if se & 0x7FFF == 0 or m == 0:
        return 0.0
    try:
        v = m / 2.0 ** 63 * 2.0 ** ((se & 0x7FFF) - 16383)
    except OverflowError:
        return 0.0
    return -v if se & 0x8000 else v


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
    kind: int       # 0x59 notes, 0x5A pattern, 0x5B automation, 0x5C audio, 0x5D Blocks
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
    kind: int       # byte 18; varies 0..0x0E across songs, probably the track colour


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
    kind: str                       # 'notes', 'automation', 'pattern', 'audio', 'block', '?'
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
    rest: dict[int, int] = field(default_factory=dict)   # controller lane id -> resting value (TRSC)


def _clip(song: Song, lcfm: Chunk) -> list[Clip]:
    lcai = next((k for k in lcfm.kids if k.id == 'LCAI'), None)
    block = song.bytes_of(lcai)[0] if lcai is not None and lcai.size else 0
    snct = lcfm.find('CAT:SNCT')
    out = []
    for snif in (snct.kids if snct else []):
        rec = {k.id: song.bytes_of(k) for k in snif.kids if not k.kids}
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
        elif any(k.name == 'FORM:SASF' for k in snif.kids):
            c.kind = 'audio'
        elif 'SBLK' in rec:
            c.kind = 'block'
            b = rec['SBLK']
            (c.placed_block,) = struct.unpack_from('>H', b, 5)
            c.placed_block += 1                     # stored 0-based; LCAI counts from 1
            (c.placed_offset,) = struct.unpack_from('>i', b, 7)
        out.append(c)
    return out


def controller_rest(b: bytes) -> dict[int, int]:
    """A note track's TRSC: u32 count, then per performance controller u16
    lane id, i32 resting value, u8 flag, i32 min, i32 max (15 bytes). The value
    is where the controller sits outside clips: mute-tests' sustain rests at
    79 and Reason's export returns it there after each clip; r16's mod wheel
    and pitch bend rest at 0. (The Transport track's TRSC is laid out
    differently: see _transport_statics.)"""
    out: dict[int, int] = {}
    if len(b) < 4:
        return out
    (n,) = struct.unpack_from('>I', b, 0)
    for k in range(min(n, 64)):
        p = 4 + 15 * k
        if p + 15 > len(b):
            break
        lane_id, value = struct.unpack_from('>Hi', b, p)
        out[lane_id] = value
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
    trsc = next((k for k in trfm.kids if k.id == 'TRSC'), None)
    rest = controller_rest(song.bytes_of(trsc)) if trsc is not None and index > 0 else {}
    return Track(index, info, names.get(info.device, ''), lanes, folder, rest)


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


def _visible(windows, covers=None):
    """Overlapping clips on one lane: a later start wins (ties: later in the
    lane). Returns each window's visible segments. covers[j] False: window j
    is cut by others but cuts nothing (a muted clip)."""
    out = []
    for i, (s, e) in enumerate(windows):
        segs = [(s, e, False)]
        for j, (s2, e2) in enumerate(windows):
            if j != i and (covers is None or covers[j]) and (s2 > s or (s2 == s and j > i)):
                segs = _cut(segs, s2, e2)
        out.append(segs)
    return out


PlayedNote = tuple[int, int, int, int]      # (song tick, pitch, velocity, length)
Control = tuple[int, int, int]              # (song tick, controller lane id, value)
STEP = PPQ // 32                            # Reason renders lines as 1/32-beat steps
CONTROL_DEFAULT = 0                         # resting value when the track's TRSC doesn't list the controller
PITCH_BEND = 0xFF
RAMPED = {0x01, 0xFF}                       # mod wheel, pitch bend; sustain jumps (Day 15)


CURVE_PIECES = 12


def _shape(x: float, k: float) -> float:
    return 1 - (1 - x) ** (1 + k) if k > 0 else x ** (1 - k)


def curved(points: list[tuple[int, int, float]]) -> list[tuple]:
    """(tick, value, curve) points as the straight-line points Reason's
    export draws them with. A curved segment from (t0, v0) to (t1, v1)
    follows v0 + (v1 - v0) * s(x), x = 0..1 across it, with
    s(x) = 1 - (1 - x)^(1 + k) for k > 0 and x^(1 - k) for k < 0. Reason
    splits it into 12 straight pieces, joined where the slope crosses equal
    steps between its start and end slopes. Returns (tick, value, sent,
    exact): a join is the curve's value rounded half up, and the
    steps run between rounded joins (exact is kept for research). A join
    inside a flat run (the same rounded value before and after) still shapes
    the steps but is not sent (Day 15's Swell, r26, r27: every exported value
    reproduced)."""
    out: list[tuple] = []
    for i, (t, v, k) in enumerate(points):
        out.append((t, v, True, v))
        if i + 1 < len(points) and k and points[i + 1][0] > t:
            t1, v1, _ = points[i + 1]
            joins = []
            for j in range(1, CURVE_PIECES):
                f = j / CURVE_PIECES
                x = 1 - (1 - f) ** (1 / k) if k > 0 else f ** (1 / -k)
                exact = v + (v1 - v) * _shape(x, k)
                joins.append((round(t + x * (t1 - t)), math.floor(exact + 0.5), exact))
            values = [v] + [jv for _, jv, _ in joins] + [v1]
            out += [(jt, jv, not values[n] == jv == values[n + 2], ex) for n, (jt, jv, ex) in enumerate(joins)]
    return out


def stepped(points) -> list[tuple[int, int]]:
    """(tick, value) points joined by straight lines, as Reason's export
    renders them: every point, plus a step every 1/32 beat from each point
    (not on the song grid: Day 15's curve pieces) strictly before the next
    point of different value, at the line's value there truncated toward
    zero (r16, r18). Points are (tick, value) or curved()'s
    (tick, value, sent, exact)."""
    out = []
    for i, (t, v, *more) in enumerate(points):
        if not more or more[0]:
            out.append((t, v))
        if i + 1 < len(points):
            t1, v1, *more1 = points[i + 1]
            if v1 != v and t1 > t:
                a, b = Fraction(v), Fraction(v1)
                g = t + STEP
                while g < t1:
                    out.append((g, int(a + (b - a) * (g - t) / (t1 - t))))
                    g += STEP
    return out


@dataclass
class Piece:
    """One visible stretch of a note clip, as it plays: a song clip, or a
    Block clip at one placement. Muted pieces (clip, lane or placement mute)
    are rendered as if unmuted, so they can be kept and switched on later."""
    lane: Lane
    clip: Clip
    start: int                      # visible window, song ticks
    end: int
    muted: bool
    placement: Clip | None = None   # the Block placement, for Block content
    notes: list[PlayedNote] = field(default_factory=list)
    controls: list[Control] = field(default_factory=list)


def _render(piece: Piece, origin: int, hard: bool, rest: dict[int, int] | None = None) -> None:
    """Fill a piece's notes and controllers. origin: song tick of the clip's
    content zero; rest: the track's controller resting values."""
    c, u, v = piece.clip, piece.start, piece.end
    loop = c.info.loop
    shift = c.info.loop_offset if loop else 0
    reps = range(-(-(c.info.length - shift) // loop)) if loop else (0,)
    for n in c.notes:
        if n.extra & 1 or (loop and not 0 <= n.pos < loop):
            continue
        for k in reps:
            at = origin + shift + n.pos + k * loop
            if u <= at < v:
                piece.notes.append((at, n.pitch, n.velocity, min(n.length, v - at) if hard else n.length))
    for lane in c.controllers:
        pts = []
        for k in reps:
            pts += [(origin + shift + p.pos + k * loop, max(lane.lo, p.value), p.curve) for p in lane.points
                    if not loop or 0 <= p.pos < loop]
        if lane.lane_id == PITCH_BEND:                  # Reason bends -8191..8191: -8192 plays as -8191 (r27)
            pts = [(t, max(-8191, x), cv) for t, x, cv in pts]
        if lane.lane_id in RAMPED:
            pts = stepped(curved(pts))
        else:
            pts = [(t, x) for t, x, _ in pts]
        # the value at the start: the last point at or before it (hidden points
        # count, Oct08), else the first point's (Day01)
        held = [x for t, x in pts if t <= u] or [x for _, x in pts[:1]]
        sent = [(u, lane.lane_id, held[-1])] if held else []
        sent += [(t, lane.lane_id, x) for t, x in pts if u < t < v]
        if sent:
            back = (rest or {}).get(lane.lane_id, CONTROL_DEFAULT)
            piece.controls += sent + [(v, lane.lane_id, back)]   # back to rest at the end (r16, mute-tests)
    own = {lane.lane_id for lane in c.controllers}
    for lane_id, value in sorted((rest or {}).items()):
        if lane_id not in own and value != CONTROL_DEFAULT:
            # a clip without this controller plays it at the track's resting value
            piece.controls.append((u, lane_id, value))
    piece.notes.sort()
    piece.controls.sort(key=lambda x: x[0])


def pieces(song: Song) -> list[tuple[Track, list[Piece]]]:
    """Every track's note clips as they play, as Reason's own MIDI export
    renders them (unmuted pieces) plus muted ones.

    Rules (each checked against Reason's exports; see the plan):
    - muted clips, muted lanes and muted notes (flag bit 0) are silent; track
      mute and solo are not applied (Reason's export ignores them);
    - a note sounds if its start lies in the visible part of its clip: inside
      the clip, not covered by a later-starting clip on the same lane, and not
      before the clip start (offsets left negative by splits and trims);
    - a covering clip cuts notes still sounding where it starts; a clip's own
      end does not cut them; a muted clip covers nothing;
    - a note still sounding when its pitch starts again on the track ends
      there (see _end_at_retrigger);
    - looping clips repeat their first `loop` ticks from start + loop_offset;
    - when the Blocks switch is on, each unmuted Block placement on the
      Transport track plays its Block's clips from the placement's offset into
      the Block, within the placement, and the placement's end cuts notes
      still sounding; clips inside a Block overlap by the same rule as song
      clips (mute-tests); song clips on the same lane cover them
      (user: empty clips are used to silence a Block locally);
    - a note lane's Block content can be muted at single placements (SMGC,
      see block_mutes); identical duplicate placements play once, and as with
      overlapping clips the later copy covers the earlier, so its mute counts;
    - controllers: the value in force at a piece's start (points before it
      count, Oct08; else the first point's value, Day01), then its points; mod wheel and pitch bend are lines
      between points (see stepped), others jump. A controller returns to
      its resting value (Track.rest, else CONTROL_DEFAULT) at the end of a piece unless another piece on the track
      takes it over there. Reason's export also leaves out values equal to
      the current one; pieces keep them so each stands alone.
    """
    ts = tracks(song)
    places: dict[tuple, list[int]] = {}         # placement -> its record numbers (-1: muted)
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
                    places.setdefault(key, []).append(-1 if c.info.muted else n)
    mutes = block_mutes(song)
    result = []
    for t in ts:
        out: list[Piece] = []
        note_lane = -1
        for ln in t.lanes:
            if ln.info.kind == LANE_NOTES:
                note_lane += 1
            songs = [c for c in ln.clips if c.kind == 'notes' and not c.block]
            covers = [not c.info.muted for c in songs]
            windows = [(c.info.start, c.info.start + c.info.length) for c in songs]
            for c, segs in zip(songs, _visible(windows, covers)):
                for u, v, hard in segs:
                    p = Piece(ln, c, u, v, ln.info.muted or c.info.muted)
                    _render(p, c.info.start, hard, t.rest)
                    out.append(p)
            # Block clips overlap inside their Block by the same rule as song
            # clips (later start wins, ties: later in the lane; a muted clip
            # covers nothing): mute-tests, an empty clip silencing another.
            by_block: dict[int, list[Clip]] = {}
            for c in (c for c in ln.clips if c.kind == 'notes' and c.block):
                by_block.setdefault(c.block, []).append(c)
            for blk, cs in by_block.items():
                bwin = [(c.info.start, c.info.start + c.info.length) for c in cs]
                for c, bsegs in zip(cs, _visible(bwin, [not c.info.muted for c in cs])):
                    for key, recs in places.items():
                        pl = first[key]
                        if pl.placed_block != blk:
                            continue
                        base = pl.info.start + pl.placed_offset      # where the Block's beat 0 falls
                        pl_end = pl.info.start + pl.info.length
                        muted = (ln.info.muted or c.info.muted or recs[-1] < 0
                                 or (t.index, note_lane, recs[-1]) in mutes)   # a later twin covers
                        for bu, bv, bhard in bsegs:
                            s, e = max(base + bu, pl.info.start), min(base + bv, pl_end)
                            if s >= e:
                                continue
                            # a placement's end cuts its Block's notes (mute-tests), as a cover does
                            segs = [(s, e, bhard or e == pl_end)]
                            for (s2, e2), cov in zip(windows, covers):
                                if cov:
                                    segs = _cut(segs, s2, e2)
                            for u, v, hard in segs:
                                p = Piece(ln, c, u, v, muted, pl)
                                _render(p, base + c.info.start, hard, t.rest)
                                out.append(p)
        out.sort(key=lambda p: (p.start, p.end))
        starts = {(p.start, i) for p in out if not p.muted for a, i, _ in p.controls if a == p.start}
        for p in out:       # a piece's only control at its end is its reset
            p.controls = [x for x in p.controls if not (x[0] == p.end and (p.end, x[1]) in starts)]
        _end_at_retrigger(out)
        result.append((t, out))
    return result


def _end_at_retrigger(track_pieces: list[Piece]) -> None:
    """A note still sounding when the same pitch starts again on the track
    (any lane, any clip) ends there: a MIDI track can't sound one pitch twice
    (Aug01: a clip's 8-beat notes end at beat 4, where the next clip restrikes
    them; notes ringing into a clip without that pitch keep their length, Day 15,
    SelfDef000). Unmuted notes restrike everything; muted pieces' notes are
    also cut by their own restrikes, so unmuting them plays the same way."""
    live: dict[int, list[int]] = {}
    for p in track_pieces:
        if not p.muted:
            for at, pitch, _, _ in p.notes:
                live.setdefault(pitch, []).append(at)
    for starts in live.values():
        starts.sort()
    for p in track_pieces:
        own: dict[int, list[int]] = {}
        if p.muted:
            for at, pitch, _, _ in p.notes:
                own.setdefault(pitch, []).append(at)
        notes = []
        for at, pitch, vel, length in p.notes:
            for starts in (live.get(pitch, []), sorted(own.get(pitch, []))):
                i = bisect.bisect_right(starts, at)
                if i < len(starts) and starts[i] < at + length:
                    length = starts[i] - at
            notes.append((at, pitch, vel, length))
        p.notes = notes


def played_notes(song: Song) -> list[tuple[Track, list[PlayedNote]]]:
    """The notes each track plays in Reason's export (see pieces)."""
    return [(t, sorted(n for p in ps if not p.muted for n in p.notes)) for t, ps in pieces(song)]


def played_controls(song: Song) -> list[tuple[Track, list[Control]]]:
    """The controller values each track sends in Reason's export (see pieces)."""
    return [(t, sorted((c for p in ps if not p.muted for c in p.controls), key=lambda x: x[0]))
            for t, ps in pieces(song)]


TEMPO_PARAM, SIGNATURE_PARAM = 0x80, 0x81


def _transport_statics(song: Song) -> dict[int, int]:
    """{parameter: value outside clips} for the Transport's automated
    parameters: the Transport track's TRSC is u32 count, then per parameter
    u16 id (0x80 tempo, 0x81 signature), i32 value, and more not decoded
    (tempo: i32 min, i32 max; signature: 8 bytes). Day 15: tempo 104000
    here while the metadata says 109000, and the export uses 104000."""
    sq = song.rs10('CAT:SQCT')

    def first_trfm(c):
        for k in (c.kids if c else []):
            if k.name == 'FORM:TRFM':
                return k
            r = first_trfm(k)
            if r is not None:
                return r
        return None

    tr = first_trfm(sq)
    trsc = next((k for k in tr.kids if k.id == 'TRSC'), None) if tr is not None else None
    b = song.bytes_of(trsc) if trsc is not None else b''
    out: dict[int, int] = {}
    if len(b) < 4:
        return out
    (n,) = struct.unpack_from('>I', b, 0)
    p = 4
    for _ in range(min(n, 16)):
        if p + 6 > len(b):
            break
        pid, value = struct.unpack_from('>Hi', b, p)
        out[pid] = value
        p += 6 + (8 if pid in (TEMPO_PARAM, SIGNATURE_PARAM) else 0)
    return out


def global_tempo_and_signature(song: Song) -> tuple[int, tuple[int, int]]:
    """(milli-BPM, (numerator, denominator)) outside any Transport clip: the
    Transport's static values when tempo or signature is automated, else the
    sequencer TRDC (tempo u32 at 23; signature bytes 27, 28), else the
    metadata, else 120 BPM 4/4."""
    statics = _transport_statics(song)
    trdc = song.rs10('CAT:SQCT', 'TRDC')
    b = song.bytes_of(trdc) if trdc is not None else b''
    tempo = statics.get(TEMPO_PARAM)
    if tempo is None and len(b) >= 27:
        (tempo,) = struct.unpack_from('>I', b, 23)
    if tempo is None or not 1000 <= tempo <= 999999:
        try:
            tempo = int(song.metadata.get('SONGTEMPO', '120000'))
        except ValueError:
            tempo = 120000
    sig = statics.get(SIGNATURE_PARAM)
    if sig is not None:
        num, den = sig & 0xFF, sig >> 8 & 0xFF
    elif len(b) >= 29:
        num, den = b[27], b[28]
    else:
        num, den = 0, 0
    if not (1 <= num <= 64 and den in (1, 2, 4, 8, 16, 32)):
        try:
            num, den = (int(x) for x in song.metadata.get('SONGSIGNATURE', '4/4').split('/'))
        except ValueError:
            num, den = 4, 4
    return tempo, (num, den)


def tempo_and_signatures(song: Song) -> tuple[list[tuple[int, int]], list[tuple[int, int, int]], list[str]]:
    """([(tick, milli-BPM)], [(tick, numerator, denominator)], problems) from
    the Transport track's automation clips. Outside any clip the song's global
    tempo and signature apply (user, r17, r19; see global_tempo_and_signature); inside, the clip's points,
    joined by stepped lines (r18), the first value holding from the clip start
    and the last to its end."""
    g_tempo, (num, den) = global_tempo_and_signature(song)
    problems: list[str] = []
    ts = tracks(song)
    clips = {0: [], 2: []}
    for ln in (ts[0].lanes if ts else []):
        for c in ln.clips:
            if c.kind == 'automation' and c.automation and c.automation.kind in clips and not c.info.muted:
                if c.block:
                    problems.append('Tempo or time signature automation inside Blocks is not imported')
                    continue
                clips[c.automation.kind].append(c)

    def timeline(kind, default):
        cs = clips[kind]
        windows = [(c.info.start, c.info.start + c.info.length) for c in cs]
        out = [(0, default)]
        spans = []
        for c, segs in zip(cs, _visible(windows)):
            pts = [(c.info.start + p.pos, p.value) for p in c.automation.points]
            if kind == 0:
                pts = stepped(pts)
            for u, v, _ in segs:
                spans.append((u, v, pts))
        spans.sort(key=lambda x: x[0])
        for u, v, pts in spans:
            inside = [(t, x) for t, x in pts if u <= t < v]
            before = [x for t, x in pts if t < u]
            start_value = before[-1] if before else (pts[0][1] if pts else default)
            out.append((u, start_value))
            out.extend(inside)
            out.append((v, default))
        # later entries at the same tick win; a span end followed by a span start keeps the start
        merged: dict[int, int] = {}
        for t, x in sorted(out, key=lambda e: e[0]):
            merged[t] = x
        return sorted(merged.items())

    tempos = timeline(0, g_tempo)
    sigs = [(t, v & 0xFF, v >> 8) for t, v in timeline(2, den << 8 | num)]
    return tempos, sigs, problems


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
