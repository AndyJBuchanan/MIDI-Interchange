"""Decode Cubase .cpr project files (Cubase 15 and 16; RIFF and RIF2).

Pure format decoding, no workspace model: import_cubase maps it onto the
model, and tools/cpr_inspect.py is the research CLI. Findings and evidence:
docs/plans/cubase-import.md. Input files are only read.

Format notes (phase 1 findings; details in the plan):

Container: big-endian. 'RIFF' + u32 size + 'NUND', or 'RIF2' + u64 size +
'NUND'. Then ROOT/ARCH chunk pairs (4-byte id, u32/u64 size). A ROOT body is
two length-prefixed strings: the archive name and its root class.

Archive: an object stream. The tag width W is 4 (RIFF) or 8 (RIF2).
  BASE   = 0xFF..FE (W bytes) | u32 nameLen | name\\0 | u16 version
           Declares a base class of the next NEW class (immediate parent
           first). No body.
  NEW    = 0xFF..FF (W bytes) | u32 nameLen | name\\0 | u16 version
           | uW length | body
  REF    = 0x80.. | offset    (W bytes) | uW length | body
           An object of a class already declared; 'offset' is the archive
           byte offset of that class's declaration tag (NEW or BASE).
Bodies hold class-specific fields with child objects embedded among them.
Without class knowledge the walker finds children by validated tags whose
lengths nest exactly inside the parent.

MIDI part events (inside MMidiPart, after its event-class table): each event
is one byte followed by a body. A MIDI status byte (0x90 note, ...) means a
compact body whose class is implied; 0x00 means a NEW/REF object header
precedes the body.
"""

from __future__ import annotations

import re
import math
import struct
from dataclasses import dataclass, field

NAME_RE = re.compile(rb'[A-Za-z_][A-Za-z0-9_:]{0,95}\0')
# Every tag starts 0xFF (NEW/BASE) or has the top bit set (REF: 0x80000000 |
# declaration offset). A REF to a class declared past 16 MB starts 0x81 or
# higher (BBCSO: markers declared at 23 MB, 7 of its 8 markers were missed).
TAG_START = re.compile(rb'[\x80-\xff]')


# ---------------------------------------------------------------- container

@dataclass
class Archive:
    name: str
    root_class: str
    offset: int          # file offset of the archive body
    data: bytes


@dataclass
class Container:
    path: str
    magic: str
    width: int           # 4 for RIFF, 8 for RIF2
    archives: list[Archive]

    def archive(self, name: str) -> Archive:
        for a in self.archives:
            if a.name == name:
                return a
        raise KeyError(f'no archive {name!r}; have {[a.name for a in self.archives]}')


def _pstring(b: bytes, pos: int) -> tuple[str, int]:
    """u32 length | bytes. Archive strings end '\\0' + UTF-8 BOM (EF BB BF);
    ROOT names have no terminator at all. Both forms are stripped."""
    n = int.from_bytes(b[pos:pos + 4], 'big')
    raw = b[pos + 4:pos + 4 + n]
    if raw.endswith(b'\0\xef\xbb\xbf'):
        raw = raw[:-4]
    s = raw.rstrip(b'\0').decode('utf-8', 'replace')
    return s, pos + 4 + n


def is_cubase_project(head: bytes) -> bool:
    """Magic check: 'RIFF' u32 'NUND' or 'RIF2' u64 'NUND'."""
    return (head[:4] == b'RIFF' and head[8:12] == b'NUND') or (head[:4] == b'RIF2' and head[12:16] == b'NUND')


def read_container(path: str | None = None, data: bytes | None = None) -> Container:
    if data is None:
        with open(path, 'rb') as fh:
            data = fh.read()
    d = data
    path = path or ''
    magic = d[:4]
    if magic == b'RIFF':
        w, form_at = 4, 8
    elif magic == b'RIF2':
        w, form_at = 8, 12
    else:
        raise ValueError(f'{path}: not a Cubase project (magic {magic!r})')
    if d[form_at:form_at + 4] != b'NUND':
        raise ValueError(f'{path}: unexpected form {d[form_at:form_at + 4]!r}')
    off = form_at + 4
    archives: list[Archive] = []
    pending: tuple[str, str] | None = None
    while off + 4 + w <= len(d):
        cid = d[off:off + 4]
        n = int.from_bytes(d[off + 4:off + 4 + w], 'big')
        body_at = off + 4 + w
        body = d[body_at:body_at + n]
        if cid == b'ROOT':
            name, p = _pstring(body, 0)
            cls, _ = _pstring(body, p)
            pending = (name, cls)
        elif cid == b'ARCH':
            name, cls = pending or ('?', '?')
            archives.append(Archive(name, cls, body_at, body))
            pending = None
        else:
            raise ValueError(f'{path}: unexpected chunk {cid!r} at {off}')
        off = body_at + n
    return Container(path, magic.decode(), w, archives)


# ------------------------------------------------------------------ objects

@dataclass
class ClassDef:
    offset: int
    name: str
    version: int
    bases: list[tuple[str, int]]


@dataclass
class Obj:
    tag_at: int
    kind: str            # 'NEW' or 'REF'
    cls: ClassDef
    body_at: int
    length: int
    children: list['Obj'] = field(default_factory=list)

    @property
    def end(self) -> int:
        return self.body_at + self.length


class Walker:
    """Finds objects in an archive by validated tags."""

    def __init__(self, data: bytes, width: int):
        self.d = data
        self.w = width
        self.new_tag = b'\xff' * width
        self.base_tag = b'\xff' * (width - 1) + b'\xfe'
        self.ref_bit = 1 << (8 * width - 1)
        self.classes: dict[int, ClassDef] = {}   # keyed by tag offsets
        self.objects: dict[int, Obj] = {}        # keyed by tag offsets
        # Object back-references (W bytes, high bit clear) give the offset of
        # the object's length field, just after its class tag/declaration.
        self.by_identity: dict[int, Obj] = {}

    def _name_at(self, p: int) -> tuple[str, int, int] | None:
        d = self.d
        n = int.from_bytes(d[p:p + 4], 'big')
        if not 2 <= n <= 96:
            return None
        raw = d[p + 4:p + 4 + n]
        if not NAME_RE.fullmatch(raw):
            return None
        q = p + 4 + n
        ver = int.from_bytes(d[q:q + 2], 'big')
        return raw[:-1].decode('ascii'), ver, q + 2

    def _length_at(self, p: int, limit: int) -> int | None:
        n = int.from_bytes(self.d[p:p + self.w], 'big')
        if p + self.w + n > limit:
            return None
        return n

    def try_object(self, i: int, limit: int) -> Obj | None:
        """Parse a NEW (with any preceding BASE run) or REF object at i."""
        d, w = self.d, self.w
        tag = d[i:i + w]
        if tag == self.base_tag or tag == self.new_tag:
            start = i
            run: list[tuple[int, str, int]] = []      # (tag offset, name, version)
            p = i
            while d[p:p + w] == self.base_tag:
                got = self._name_at(p + w)
                if not got:
                    return None
                name, ver, nxt = got
                run.append((p, name, ver))
                p = nxt
            if d[p:p + w] != self.new_tag:
                return None
            got = self._name_at(p + w)
            if not got:
                return None
            name, ver, q = got
            n = self._length_at(q, limit)
            if n is None:
                return None
            # Each tag declares its own class, referable by that tag's offset.
            # A BASE run lists the parents of the NEW class, nearest first.
            for k, (off, bname, bver) in enumerate(run):
                self.classes[off] = ClassDef(off, bname, bver, [(b, v) for _, b, v in run[k + 1:]])
            cdef = ClassDef(p, name, ver, [(b, v) for _, b, v in run])
            self.classes[p] = cdef
            return Obj(start, 'NEW', cdef, q + w, n)
        v = int.from_bytes(tag, 'big')
        if v & self.ref_bit:
            target = v & ~self.ref_bit
            cdef = self.classes.get(target) if target else None
            if cdef is None:
                return None
            n = self._length_at(i + w, limit)
            if n is None:
                return None
            return Obj(i, 'REF', cdef, i + 2 * w, n)
        return None

    def declare_all(self) -> None:
        """Register every class declaration in the archive (a fast regex
        pre-pass), so a walk that skips some objects' bodies still resolves
        later references to classes declared inside them."""
        d, w = self.d, self.w
        for m in re.finditer(re.escape(self.base_tag[:-1]) + rb'[\xfe\xff]', d):
            i = m.start()
            got = self._name_at(i + w)
            if got and i not in self.classes:
                name, ver, _ = got
                self.classes[i] = ClassDef(i, name, ver, [])

    def walk(self, start: int, end: int, depth: int = 0, max_depth: int = 64,
             skip: frozenset[str] = frozenset()) -> list[Obj]:
        out: list[Obj] = []
        i = start
        d = self.d
        while i + self.w <= end:
            m = TAG_START.search(d, i, end - self.w + 1)
            if m is None:
                break
            i = m.start()
            o = self.try_object(i, end)
            if o is None:
                i += 1
                continue
            if depth < max_depth and o.cls.name not in skip:
                o.children = self.walk(o.body_at, o.end, depth + 1, max_depth, skip)
            self.objects[o.tag_at] = o
            self.by_identity[o.body_at - self.w] = o
            out.append(o)
            i = o.end
        return out


# Mixer channel objects hold plug-in states (172 MB in one verify project) and
# are read as raw bytes (track_state_flags), never through child objects.
READER_SKIP = frozenset({'MInstrumentTrack', 'MMidiTrack', 'MAudioTrack'})


def walk_archive(c: Container, name: str, skip: frozenset[str] = frozenset()) -> tuple[Walker, list[Obj]]:
    """Walk an archive. With ``skip``, bodies of those classes are not
    searched for children; every class declaration is registered first so
    references into them still resolve."""
    a = c.archive(name)
    wk = Walker(a.data, c.width)
    if skip:
        wk.declare_all()
    return wk, wk.walk(0, len(a.data), skip=skip)


# --------------------------------------------------------------- MIDI parts

EVENT_STATUS = {0x90: 'note', 0xA0: 'polypressure', 0xD0: 'aftertouch',
                0xC0: 'program', 0xB0: 'controller', 0xE0: 'pitchbend', 0xF0: 'sysex'}
CLASS_STATUS = {'MMidiNote': 0x90, 'MMidiPolyPressure': 0xA0, 'MMidiAfterTouch': 0xD0,
                'MMidiProgramChange': 0xC0, 'MMidiController': 0xB0,
                'MMidiPitchBend': 0xE0, 'MMidiSysex': 0xF0}
# Bytes between the f64 position and the u32 that precedes the property
# count: channel then two MIDI data bytes. Confirmed: note (pitch, velocity),
# controller (number, value), pitch bend (LSB, MSB; tier 3 c24), program
# change (program, 0; c25). Channel pressure is decoded in the orchestral project
# (1,853 events). Poly pressure is assumed, no fixture yet.
# Sysex is variable-length and not decoded.
DATA_BYTES = {0x90: 3, 0xB0: 3, 0xE0: 3, 0xC0: 3, 0xA0: 3, 0xD0: 3}


EVENT_MUTED = 0x20000     # a note muted in the editors (GA's kit: 2,399 notes Cubase doesn't export)


@dataclass
class CprEvent:
    status: int
    position: float      # ticks (480 PPQ), relative to the part's content start
    channel: int
    data: bytes          # status-specific data bytes after the channel
    props: dict[str, object]
    length: float | None = None   # notes only, ticks
    tail: bytes = b''             # notes only: 17 bytes after the length
    framed: bool = False          # written as a full object (00 + tag)
    flags: int = 0                # u32 after the data bytes: EVENT_MUTED

    @property
    def muted(self) -> bool:
        return bool(self.flags & EVENT_MUTED)

    @property
    def kind(self) -> str:
        return EVENT_STATUS.get(self.status, f'0x{self.status:02x}')


def _props(wk: Walker, q: int, limit: int) -> tuple[dict[str, object], int]:
    """u16 count | count x (key | u16 type | value).

    Keys are FourCCs stored reversed (some are hashes, not text). The type's
    low byte is the kind, higher bits look like flags: 1 = i64, 4 = f64;
    other kinds hold an embedded NEW/REF object (2: e.g. a controller curve
    shape MParamEventCurveRationalBezier; 0x22: tempo-track 'TVCi', note
    'ScAr' (reader key 'rAcS') holding Omnivocal lyric attributes; 0x0408: a string object), or for
    kind 8 possibly a plain string.
    """
    d = wk.d
    n = int.from_bytes(d[q:q + 2], 'big')
    q += 2
    props: dict[str, object] = {}
    for _ in range(n):
        key = d[q:q + 4][::-1].decode('latin-1')
        typ = int.from_bytes(d[q + 4:q + 6], 'big')
        kind = typ & 0xFF
        q += 6
        if kind == 1:
            props[key] = int.from_bytes(d[q:q + 8], 'big', signed=True); q += 8
        elif kind == 4:
            props[key] = struct.unpack('>d', d[q:q + 8])[0]; q += 8
        else:
            o = wk.try_object(q, limit)
            if o is not None:
                props[key] = o; q = o.end
            elif kind == 8 and _bomstring_at(d, q, limit) is not None:
                end = _bomstring_at(d, q, limit)
                props[key] = _pstring(d, q)[0]; q = end
            else:
                raise ValueError(f'unknown property type 0x{typ:04x} for {key!r} at {q - 6}')
    return props, q


def parse_event_body(wk: Walker, p: int, status: int, limit: int) -> tuple[CprEvent, int]:
    d = wk.d
    if status not in DATA_BYTES:
        raise ValueError(f'event status 0x{status:02x} not decoded')
    pos = struct.unpack('>d', d[p:p + 8])[0]
    nd = DATA_BYTES[status]
    chan = d[p + 8]
    data = d[p + 9:p + 8 + nd]
    flags = int.from_bytes(d[p + 8 + nd:p + 12 + nd], 'big')
    q = p + 8 + nd + 4
    props, q = _props(wk, q, limit)
    ev = CprEvent(status, pos, chan, data, props, flags=flags)
    if status == 0x90:
        ev.length = struct.unpack('>d', d[q:q + 8])[0]
        ev.tail = d[q + 8:q + 25]
        q += 25
    return ev, q


def iter_midi_parts(wk: Walker, objs: list[Obj]):
    stack = list(objs)
    while stack:
        o = stack.pop(0)
        if o.cls.name == 'MMidiPart':
            yield o
        stack[0:0] = o.children


def decode_part_events(wk: Walker, part: Obj) -> tuple[list[CprEvent], list[str], dict]:
    """Decode an MMidiPart body.

    Layout: string name | u32 time base, then musical: 2 x W-byte tempo and
    signature references, or linear (1): f64 1.0 (12 bytes instead of 4 + 2W;
    event positions and note lengths are then seconds) | u32 eventCount | u8 classCount
    | classCount x (NEW/REF class tag + uW length 0) | eventCount events.
    The u8 classCount is absent when eventCount is 0.
    Each event: u8 status, then a compact body; status 0 means a NEW/REF
    object header precedes the body and the class gives the status.
    """
    d, w = wk.d, wk.w
    events: list[CprEvent] = []
    problems: list[str] = []
    name, p = _pstring(d, part.body_at)
    linear = int.from_bytes(d[p:p + 4], 'big') == 1
    if linear:
        hdr = [1, struct.unpack('>d', d[p + 4:p + 12])[0]]
        p += 12
    else:
        hdr = [int.from_bytes(d[p:p + 4], 'big'), int.from_bytes(d[p + 4:p + 4 + w], 'big'),
               int.from_bytes(d[p + 4 + w:p + 4 + 2 * w], 'big')]
        p += 4 + 2 * w
    count = int.from_bytes(d[p:p + 4], 'big')
    p += 4
    nclasses = 0
    if count:                                  # absent in an empty part
        nclasses = d[p]
        p += 1
    info = {'name': name, 'header': hdr, 'count': count, 'linear': linear}
    for _ in range(nclasses):
        o = wk.try_object(p, part.end)
        if o is None or o.length != 0:
            problems.append(f'bad event-class entry at {p}')
            return events, problems, info
        p = o.end
    for k in range(count):
        flag = d[p]
        try:
            if flag == 0x00:
                o = wk.try_object(p + 1, part.end)
                if o is None:
                    raise ValueError('unparsed framed event')
                status = CLASS_STATUS.get(o.cls.name)
                if status is None:
                    # A full object of another class (e.g. MScoreEvent: Score
                    # Editor symbols, BBCSO verify file). Its length is
                    # explicit, so step over it and keep decoding.
                    skipped = info.setdefault('skipped', {})
                    skipped[o.cls.name] = skipped.get(o.cls.name, 0) + 1
                    p = o.end
                    continue
                ev, q = parse_event_body(wk, o.body_at, status, o.end)
                ev.framed = True
                if q != o.end:
                    raise ValueError(f'{ev.kind} body ends {q}, object ends {o.end}')
                p = o.end
            else:
                ev, p = parse_event_body(wk, p + 1, flag, part.end)
        except (ValueError, struct.error, UnicodeDecodeError) as exc:
            problems.append(f'event {k}: {exc} at {p}')
            break
        events.append(ev)
    else:
        if p != part.end:
            problems.append(f'{count} events end at {p}, part ends at {part.end} ({part.end - p} bytes left)')
    return events, problems, info


PART_MUTED = 0x0002


@dataclass
class PartEvent:
    """MMidiPartEvent: a part placed on a track.

    Body: u16 flags (bit 1 = muted) | f64 start | f64 length | f64 content
    offset | the part contents: a NEW/REF MMidiPart object, or for a shared
    copy a W-byte back-reference to an existing one. Musical time base: all
    in ticks (480 PPQ) from the project's absolute zero; a note's absolute
    time is start - offset + note position. Linear time base stores seconds
    instead (tier 3 c26, d8 baseline).
    """
    obj: Obj
    flags: int
    start: float
    length: float
    offset: float
    part: Obj | None
    shared: bool

    @property
    def muted(self) -> bool:
        return bool(self.flags & PART_MUTED)


def part_event_info(wk: Walker, pe: Obj) -> PartEvent:
    d, p, w = wk.d, pe.body_at, wk.w
    flags = int.from_bytes(d[p:p + 2], 'big')
    start, length, offset = struct.unpack('>ddd', d[p + 2:p + 26])
    q = p + 26
    part = next((ch for ch in pe.children if ch.cls.name == 'MMidiPart' and ch.tag_at == q), None)
    shared = False
    if part is None:
        target = wk.by_identity.get(int.from_bytes(d[q:q + w], 'big'))
        if target is not None and target.cls.name == 'MMidiPart':
            part, shared = target, True
    return PartEvent(pe, flags, start, length, offset, part, shared)


def part_event_window(wk: Walker, part_event: Obj) -> tuple[float, float]:
    info = part_event_info(wk, part_event)
    return info.start, info.length


# ------------------------------------------------------------ tracks/timing

@dataclass
class TempoPoint:
    seconds_per_beat: float
    seconds: float
    ticks: float
    ramp: bool           # tempo ramps (linearly in beats) from the previous point

    @property
    def bpm(self) -> float:
        return 60.0 / self.seconds_per_beat


def tempo_points(wk: Walker, ev: Obj) -> tuple[list[TempoPoint], float]:
    """MTempoTrackEvent: u32 n | n x (f32 s/beat | f64 seconds | f64 ticks |
    u16 type, 1 = ramp into this point) | f32 tempo (BPM; fixed tempo?)."""
    d, p = wk.d, ev.body_at
    n = int.from_bytes(d[p:p + 4], 'big')
    p += 4
    pts = []
    for _ in range(n):
        spb, = struct.unpack('>f', d[p:p + 4])
        secs, ticks = struct.unpack('>dd', d[p + 4:p + 20])
        typ = int.from_bytes(d[p + 20:p + 22], 'big')
        pts.append(TempoPoint(spb, secs, ticks, typ == 1))
        p += 22
    fixed, = struct.unpack('>f', d[p:p + 4])
    return pts, fixed


def part_is_linear(wk: Walker, part: Obj) -> bool:
    """The part's own time base: the u32 after its name (1 = linear, seconds)."""
    _, p = _pstring(wk.d, part.body_at)
    return int.from_bytes(wk.d[p:p + 4], 'big') == 1


def seconds_to_ticks(points: list[TempoPoint], seconds: float) -> float:
    """Convert a time in seconds to f64 ticks (480 PPQ) through the tempo
    points. Constant tempo between points; into a ramp point the tempo is
    linear in beats, so with B beats from bpm0 to bpm1, t(x) = 60 B / (bpm1 -
    bpm0) * ln(bpm(x) / bpm0), inverted here. Before the first point and after
    the last, the nearest point's tempo continues."""
    if not points:
        return seconds / 0.5 * 480          # no tempo track: 120 BPM
    i = 0
    for k, pt in enumerate(points):
        if pt.seconds <= seconds:
            i = k
    a = points[i]
    b = points[i + 1] if i + 1 < len(points) else None
    t = seconds - a.seconds
    if b is not None and b.ramp and b.ticks > a.ticks:
        bpm0, bpm1 = a.bpm, b.bpm
        beats = (b.ticks - a.ticks) / 480
        if abs(bpm1 - bpm0) < 1e-9:
            return a.ticks + t / a.seconds_per_beat * 480
        bpm = bpm0 * math.exp(t * (bpm1 - bpm0) / (60 * beats))
        return a.ticks + beats * (bpm - bpm0) / (bpm1 - bpm0) * 480
    return a.ticks + t / a.seconds_per_beat * 480


def signature_points(wk: Walker, ev: Obj) -> list[tuple[int, int, int]]:
    """MSignatureTrackEvent: u32 n | n x (u32 ticks | u16 num | u16 den |
    8 bytes unknown). Returns (ticks, numerator, denominator)."""
    d, p = wk.d, ev.body_at
    n = int.from_bytes(d[p:p + 4], 'big')
    p += 4
    out = []
    for _ in range(n):
        out.append((int.from_bytes(d[p:p + 4], 'big'), int.from_bytes(d[p + 4:p + 6], 'big'),
                    int.from_bytes(d[p + 6:p + 8], 'big')))
        p += 16
    return out


# MDrumTrackEvent (Cubase's Drum Track) derives from MInstrumentTrackEvent and
# has the same MInstrumentTrack mixer object (verify file vocalfun001, 16.0.5).
TRACK_EVENTS = ('MInstrumentTrackEvent', 'MMidiTrackEvent', 'MDrumTrackEvent')


def track_time_base_linear(wk: Walker, track_event: Obj) -> bool:
    """The u32 after the name in the track's MListNode: 0 = musical time base
    (ticks), 1 = linear (seconds; an f64 follows). Only tier 3 c26's Lead
    track is 1 among all fixture tracks."""
    node = next((ch for ch in track_event.children if ch.cls.name == 'MListNode'), None)
    if node is None:
        return False
    _, p = _pstring(wk.d, node.body_at)
    return int.from_bytes(wk.d[p:p + 4], 'big') == 1


def app_version(c: Container) -> tuple[str, str]:
    """('Cubase', '16.0.5') from the Version archive (PAppVersion): the
    application name, then 'Version x.y.z', as length-prefixed strings."""
    d = c.archive('Version').data
    found = re.findall(rb'([A-Za-z][\x20-\x7e]{2,})\x00', d)
    names = [x.decode() for x in found]
    app = next((n for n in names if n not in ('CmObject', 'PAppVersion')), '')
    ver = next((n[8:] for n in names if n.startswith('Version ')), '')
    return app, ver


def track_name(wk: Walker, track_event: Obj) -> str:
    """The track's name starts its MListNode child."""
    node = next((ch for ch in track_event.children if ch.cls.name == 'MListNode'), None)
    return _pstring(wk.d, node.body_at)[0] if node else '?'


TRACK_SOLO = 0x1
TRACK_MUTE = 0x4


def _cstring_at(b: bytes, p: int, limit: int) -> int | None:
    """u32 length (including the NUL) | bytes | NUL, with no NUL inside.
    Returns the end offset, or None. Port names may be any UTF-8."""
    if p + 4 > limit:
        return None
    n = int.from_bytes(b[p:p + 4], 'big')
    end = p + 4 + n
    if not 1 <= n <= 512 or end > limit or b[end - 1] != 0 or 0 in b[p + 4:end - 1]:
        return None
    return end


def port_record_end(b: bytes, p: int, limit: int) -> int | None:
    """A MIDI port record: u16 3 | string id | u16 0 | string name. Returns
    its end, or None. The input port of a track is stored this way (for the
    default input both strings are 'All MIDI Inputs')."""
    if b[p:p + 2] != b'\x00\x03':
        return None
    q = _cstring_at(b, p + 2, limit)
    if q is None or b[q:q + 2] != b'\x00\x00':
        return None
    return _cstring_at(b, q + 2, limit)


FLAGS_SENTINEL = b'\xff' * 8


def _bomstring_at(b: bytes, p: int, limit: int) -> int | None:
    """u32 length | UTF-8 | NUL | EF BB BF (the archive's usual string)."""
    if p + 4 > limit:
        return None
    n = int.from_bytes(b[p:p + 4], 'big')
    end = p + 4 + n
    if not 4 <= n <= 1024 or end > limit or b[end - 4:end] != b'\x00\xef\xbb\xbf':
        return None
    return end


def state_flags_offset(b: bytes, cls: str) -> int | None:
    """Offset of the channel state flags u32 in a track's mixer object body.

    Found by structure, independent of the port names:
    - MInstrumentTrack (v10, v11): the flags follow the **last** input port
      record in the body's final 512 bytes. What follows varies (usually a
      u16 count, optional name string, padding and FF x 8; BBCSO 15.0.10 has a
      u32 count and the track's own name; Beat003vs ends FF FF FF FF 00 00 00
      00), so only the flags value itself is checked (state bits only).
    - MMidiTrack (v7 and v8, the same layout): the body starts with the output port (u16 3, id, 4
      bytes, name), then the input port record, a u32 (1 in the fixtures, a
      track on channel 2: possibly the channel), then the flags.
    """
    def plausible(at: int) -> bool:
        return at + 4 <= len(b) and int.from_bytes(b[at:at + 4], 'big') <= 0xFF
    if cls == 'MInstrumentTrack':
        lo = max(0, len(b) - 512)
        for p in range(len(b) - 2, lo - 1, -1):
            end = port_record_end(b, p, len(b))
            if end is not None:
                return end if plausible(end) else None
        return None
    if cls == 'MMidiTrack':
        for p in range(0, min(len(b), 512)):
            end = port_record_end(b, p, len(b))
            if end is not None:
                return end + 4 if plausible(end + 4) else None
        return None
    return None


MODIFIER_PARAMS = ('Transpose', 'Velocity Shift', 'Delay')


def _param_value(blob: bytes, name: str) -> int | None:
    """An integer parameter in a MIDI Modifiers block: u32 name length (with
    its NUL) | name | 00 (the NUL) | u16 2 (container) | u16 6 (sub-kind) | u32 3 (count) |
    u32 6 'Value' 00 | u16 1 | i64."""
    key = len(name.encode()) + 1
    pat = (struct.pack('>I', key) + name.encode() + b'\x00\x00\x02\x00\x06\x00\x00\x00\x03'
           + b'\x00\x00\x00\x06Value\x00\x00\x01')
    i = blob.find(pat)
    if i < 0 or i + len(pat) + 8 > len(blob):
        return None
    return int.from_bytes(blob[i + len(pat):i + len(pat) + 8], 'big', signed=True)


def track_midi_modifiers(wk: Walker, track_event: Obj) -> list[dict[str, int]]:
    """The track's MIDI Modifiers effects, in slot order: {parameter: value}
    for MODIFIER_PARAMS. Each is a 'TrackParaEffect' named 'MIDI Modifiers'
    inside the track body, holding a 'PDuplicator' parameter tree. Every GA
    track has one (slot 0); Prologue 01 has a second (slot 1) with Transpose
    24, and Cubase's MIDI export plays Prologue 24 semitones up, so the
    slots chain (their transposes add)."""
    d = wk.d
    body = d[track_event.body_at:track_event.end]
    starts = [m.start() for m in re.finditer(b'TrackParaEffect', body)]
    out = []
    for n, m in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(body)
        blob = body[m:end]
        if b'MIDI Modifiers' not in blob[:80]:
            continue
        values = {p: _param_value(blob, p) for p in MODIFIER_PARAMS}
        out.append({p: v for p, v in values.items() if v is not None})
    return out


def track_transpose(wk: Walker, track_event: Obj) -> int:
    """Semitones the track's MIDI Modifiers add (sum over chained slots)."""
    return sum(m.get('Transpose', 0) for m in track_midi_modifiers(wk, track_event))


def track_state_flags(wk: Walker, track_event: Obj) -> int | None:
    """Channel state flags: bit 0 = solo, bit 2 = mute (tier 2 c14, c17s,
    c17m, c18fm; GA's two muted tracks). See state_flags_offset()."""
    ch = next((c for c in track_event.children if c.cls.name in ('MInstrumentTrack', 'MMidiTrack')), None)
    if ch is None:
        return None
    body = wk.d[ch.body_at:ch.end]
    at = state_flags_offset(body, ch.cls.name)
    return None if at is None else int.from_bytes(body[at:at + 4], 'big')


def _own_bytes(wk: Walker, ev: Obj) -> bytes:
    """The event's body with its direct children's byte ranges removed."""
    out, at = [], ev.body_at
    for ch in sorted(ev.children, key=lambda c: c.tag_at):
        if ch.tag_at >= at:
            out.append(wk.d[at:ch.tag_at])
            at = max(at, ch.end)
    out.append(wk.d[at:ev.end])
    return b''.join(out)


def track_disabled_hidden(wk: Walker, track_event: Obj) -> tuple[bool, bool]:
    """(disabled, hidden) from the track event's property list (section 4.3).

    The list sits straight after the MListNode child (2 bytes, then the
    properties) and ends exactly where the mixer object starts. Disabled is
    'noit' (reader key 'tion') EQUAL TO 1: a track that was disabled and
    re-enabled keeps it at 0, one never toggled has none. Hidden is 'dihT'
    (reader key 'Thid') equal to 1. If the list does not parse, the same
    markers are searched for in the event's own bytes (never inside a child).
    """
    node = next((ch for ch in track_event.children if ch.cls.name == 'MListNode'), None)
    if node is not None:
        try:
            props, end = _props(wk, node.end + 2, track_event.end)
            mixer = next((ch for ch in sorted(track_event.children, key=lambda c: c.tag_at)
                          if ch.tag_at >= end and ch.cls.name in ('MInstrumentTrack', 'MMidiTrack', 'MAudioTrack')), None)
            if mixer is None or mixer.tag_at == end:
                return props.get('tion') == 1, props.get('Thid') == 1
        except (ValueError, IndexError, struct.error):
            pass
    own = _own_bytes(wk, track_event)
    return b'noit\x00\x01' + bytes(7) + b'\x01' in own, b'dihT\x00\x01' + bytes(7) + b'\x01' in own


def track_solo_flag(wk: Walker, track_event: Obj) -> int | None:
    """Mixer channel record 'SoloFlag' (i64), present with value 1 when an
    instrument track is muted (alongside a 'Solo' record when soloed). The
    channel state flags (track_state_flags) are the primary source."""
    ch = next((c for c in track_event.children if c.cls.name in ('MInstrumentTrack', 'MMidiTrack')), None)
    if ch is None:
        return None
    body = wk.d[ch.body_at:ch.end]
    k = body.find(b'\x00\x00\x00\x09SoloFlag\x00\x00\x01')
    if k < 0:
        return None
    return int.from_bytes(body[k + 15:k + 23], 'big', signed=True)   # 4 + 'SoloFlag\\0' + u16 type


def folder_path(wk: Walker, track_event: Obj) -> list[str]:
    """Names of the MFolderTrack ancestors of a track, outermost first.

    No folder is special-cased. A folder holds its own MTrackList, whose body
    starts with the folder's name. Cubase's I/O folder ('Input/Output' or
    'Input/Output Channels') holds in/out channel (device) tracks, and rack
    instrument folders hold device tracks too; neither normally holds MIDI
    parts, so they only appear here if the user put a MIDI track inside.
    Tempo, signature, marker and chord tracks are loose by default and can be
    moved anywhere, including into folders. Where one sits in the file says
    nothing about where the user put it: it is written inline at the first
    node that references it (GA: the chord track node; the other fixtures:
    'Stereo Out' in the I/O folder). They are found by class wherever they are. An instrument stack (Cubase 16) is also an
    MFolderTrack (tier 2 c18is). Folder state flags: folder_state_flags().
    """
    return [folder_name(wk, f) for f in sorted(
        (o for o in wk.objects.values() if o.cls.name == 'MFolderTrack' and o.body_at <= track_event.tag_at < o.end),
        key=lambda o: o.tag_at)]


def folder_name(wk: Walker, folder: Obj) -> str:
    lst = next((ch for ch in folder.children if ch.cls.name == 'MTrackList'), None)
    return _pstring(wk.d, lst.body_at)[0] if lst else '?'


def folder_state_flags(wk: Walker, folder: Obj) -> int:
    """MFolderTrack state flags (bit 0 solo, bit 2 mute, as for tracks).

    Stored as a tagged property 'Solo' (FourCC reversed, type 1, i64) among
    the folder's own fields after its MTrackList, before its MTrack child
    (tier 2 c18fm: 4 when muted, 0 otherwise). Absent in some folders (Ditty,
    15.0.21), meaning 0. Muting a folder also sets the mute flag on every
    track inside it, so the saved track flags carry the inherited state.
    """
    lst = next((ch for ch in folder.children if ch.cls.name == 'MTrackList'), None)
    trk = next((ch for ch in folder.children if ch.cls.name == 'MTrack'), None)
    lo = lst.end if lst is not None else folder.body_at
    hi = trk.tag_at if trk is not None else folder.end
    k = wk.d.find(b'oloS\x00\x01', lo, hi)
    if k < 0:
        return 0
    return int.from_bytes(wk.d[k + 6:k + 14], 'big', signed=True)


@dataclass
class Marker:
    name: str
    ident: int
    start: float         # ticks
    length: float        # ticks; 0 for a plain marker
    is_range: bool       # cycle (range) marker


def markers(wk: Walker) -> list[Marker]:
    """MMarkerEvent / MRangeMarkerEvent in the marker track's list.

    Body: string name | u32 id | u16 (0) | f64 start | f64 length (ticks).
    A range marker ends at start + length (indy's contiguous sections confirm
    length, not end).
    """
    out = []
    for o in sorted(wk.objects.values(), key=lambda o: o.tag_at):
        if o.cls.name in ('MMarkerEvent', 'MRangeMarkerEvent'):
            name, p = _pstring(wk.d, o.body_at)
            ident = int.from_bytes(wk.d[p:p + 4], 'big')
            start, length = struct.unpack('>dd', wk.d[p + 6:p + 22])
            out.append(Marker(name, ident, start, length, o.cls.name == 'MRangeMarkerEvent'))
    return out


def display_bar_offset(wk: Walker) -> int | None:
    """PArrangeSetup: i32 at body offset 84 (v8 and v9, RIFF and RIF2).

    0 normally; -1 when the project shows a blank bar before bar 1 (tier 1
    c02-1), so displayed bar 1 is at absolute tick 1920 in 4/4. Ditty is -3,
    indy -1, GA 0. The absolute timeline is unaffected.
    """
    o = next((o for o in wk.objects.values() if o.cls.name == 'PArrangeSetup'), None)
    if o is None or o.length < 88:
        return None
    return int.from_bytes(wk.d[o.body_at + 84:o.body_at + 88], "big", signed=True)
