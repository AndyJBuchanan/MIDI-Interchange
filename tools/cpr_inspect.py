#!/usr/bin/env python3
"""Read-only research inspector for Cubase .cpr project files.

Not part of the app. Used to reverse-engineer the native format from project
files we saved ourselves (see docs/plans/cubase-import.md). It never writes to
the input files.

Usage:
    cpr_inspect.py roots FILE                 list ROOT/ARCH records
    cpr_inspect.py tree FILE [--archive NAME] [--depth N] [--offsets]
    cpr_inspect.py classes FILE [--archive NAME]
    cpr_inspect.py notes FILE                 tracks, parts (mute, trims, shared) and events
    cpr_inspect.py timeline FILE              tempo, signatures, display offset, markers
    cpr_inspect.py diff FILE_A FILE_B [--archive NAME]
    cpr_inspect.py hex FILE START END [--archive NAME]

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

import argparse
import re
import struct
import sys
from dataclasses import dataclass, field

NAME_RE = re.compile(rb'[A-Za-z_][A-Za-z0-9_:]{0,95}\0')


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
    ROOT names end '\\0' only. Both are stripped."""
    n = int.from_bytes(b[pos:pos + 4], 'big')
    raw = b[pos + 4:pos + 4 + n]
    if raw.endswith(b'\0\xef\xbb\xbf'):
        raw = raw[:-4]
    s = raw.rstrip(b'\0').decode('utf-8', 'replace')
    return s, pos + 4 + n


def read_container(path: str) -> Container:
    with open(path, 'rb') as fh:
        d = fh.read()
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

    def walk(self, start: int, end: int, depth: int = 0, max_depth: int = 64) -> list[Obj]:
        out: list[Obj] = []
        i = start
        while i + self.w <= end:
            o = self.try_object(i, end)
            if o is None:
                i += 1
                continue
            if depth < max_depth:
                o.children = self.walk(o.body_at, o.end, depth + 1, max_depth)
            self.objects[o.tag_at] = o
            self.by_identity[o.body_at - self.w] = o
            out.append(o)
            i = o.end
        return out


def walk_archive(c: Container, name: str) -> tuple[Walker, list[Obj]]:
    a = c.archive(name)
    wk = Walker(a.data, c.width)
    return wk, wk.walk(0, len(a.data))


# --------------------------------------------------------------- MIDI parts

EVENT_STATUS = {0x90: 'note', 0xA0: 'polypressure', 0xD0: 'aftertouch',
                0xC0: 'program', 0xB0: 'controller', 0xE0: 'pitchbend', 0xF0: 'sysex'}
CLASS_STATUS = {'MMidiNote': 0x90, 'MMidiPolyPressure': 0xA0, 'MMidiAfterTouch': 0xD0,
                'MMidiProgramChange': 0xC0, 'MMidiController': 0xB0,
                'MMidiPitchBend': 0xE0, 'MMidiSysex': 0xF0}
# Bytes between the f64 position and the u32 that precedes the property
# count: channel then two MIDI data bytes. Confirmed: note (pitch, velocity),
# controller (number, value), pitch bend (LSB, MSB; tier 3 c24), program
# change (program, 0; c25). Poly and channel pressure assumed, no fixture yet.
# Sysex is variable-length and not decoded.
DATA_BYTES = {0x90: 3, 0xB0: 3, 0xE0: 3, 0xC0: 3, 0xA0: 3, 0xD0: 3}


@dataclass
class Event:
    status: int
    position: float      # ticks (480 PPQ), relative to the part's content start
    channel: int
    data: bytes          # status-specific data bytes after the channel
    props: dict[str, object]
    length: float | None = None   # notes only, ticks
    tail: bytes = b''             # notes only: 17 bytes after the length
    framed: bool = False          # written as a full object (00 + tag)

    @property
    def kind(self) -> str:
        return EVENT_STATUS.get(self.status, f'0x{self.status:02x}')


def _props(wk: Walker, q: int, limit: int) -> tuple[dict[str, object], int]:
    """u16 count | count x (FourCC reversed | u16 type | value).
    Types: 1 = i64, 4 = f64, 2 = embedded object (NEW or REF, e.g. a
    controller curve shape MParamEventCurveRationalBezier)."""
    d = wk.d
    n = int.from_bytes(d[q:q + 2], 'big')
    q += 2
    props: dict[str, object] = {}
    for _ in range(n):
        key = d[q:q + 4][::-1].decode('latin-1')
        typ = int.from_bytes(d[q + 4:q + 6], 'big')
        q += 6
        if typ == 1:
            props[key] = int.from_bytes(d[q:q + 8], 'big', signed=True); q += 8
        elif typ == 4:
            props[key] = struct.unpack('>d', d[q:q + 8])[0]; q += 8
        elif typ == 2:
            o = wk.try_object(q, limit)
            if o is None:
                raise ValueError(f'unparsed object property {key!r} at {q}')
            props[key] = o; q = o.end
        else:
            raise ValueError(f'unknown property type {typ} for {key!r} at {q - 6}')
    return props, q


def parse_event_body(wk: Walker, p: int, status: int, limit: int) -> tuple[Event, int]:
    d = wk.d
    if status not in DATA_BYTES:
        raise ValueError(f'event status 0x{status:02x} not decoded')
    pos = struct.unpack('>d', d[p:p + 8])[0]
    nd = DATA_BYTES[status]
    chan = d[p + 8]
    data = d[p + 9:p + 8 + nd]
    q = p + 8 + nd + 4                         # u32 unknown (zero so far)
    props, q = _props(wk, q, limit)
    ev = Event(status, pos, chan, data, props)
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


def decode_part_events(wk: Walker, part: Obj) -> tuple[list[Event], list[str], dict]:
    """Decode an MMidiPart body.

    Layout: string name | uW, u32, uW (unknown) | u32 eventCount | u8 classCount
    | classCount x (NEW/REF class tag + uW length 0) | eventCount events.
    The u8 classCount is absent when eventCount is 0.
    Each event: u8 status, then a compact body; status 0 means a NEW/REF
    object header precedes the body and the class gives the status.
    """
    d, w = wk.d, wk.w
    events: list[Event] = []
    problems: list[str] = []
    name, p = _pstring(d, part.body_at)
    hdr = [int.from_bytes(d[p:p + w], 'big'), int.from_bytes(d[p + w:p + w + 4], 'big'),
           int.from_bytes(d[p + w + 4:p + 2 * w + 4], 'big')]
    p += 2 * w + 4
    count = int.from_bytes(d[p:p + 4], 'big')
    p += 4
    nclasses = 0
    if count:                                  # absent in an empty part
        nclasses = d[p]
        p += 1
    info = {'name': name, 'header': hdr, 'count': count}
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
                    raise ValueError(f'framed {o.cls.name} not decoded')
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
    instead (tier 3 c26) and is not decoded yet.
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


TRACK_EVENTS = ('MInstrumentTrackEvent', 'MMidiTrackEvent')


def track_name(wk: Walker, track_event: Obj) -> str:
    """The track's name starts its MListNode child."""
    node = next((ch for ch in track_event.children if ch.cls.name == 'MListNode'), None)
    return _pstring(wk.d, node.body_at)[0] if node else '?'


TRACK_SOLO = 0x1
TRACK_MUTE = 0x4


def track_state_flags(wk: Walker, track_event: Obj) -> int | None:
    """Channel state flags: bit 0 = solo, bit 2 = mute (tier 2 c14, c17s,
    c17m; GA's two muted tracks).

    The u32 follows the track's MIDI input port, stored as the same
    length-prefixed name twice; it is the first u32 after the second copy in
    MInstrumentTrack and the second in MMidiTrack. Located here by the default
    input name 'All MIDI Inputs', which every fixture uses. A track set to a
    specific input stores another name, so the reader needs a structural parse
    of this header (phase 3).
    """
    ch = next((c for c in track_event.children if c.cls.name in ('MInstrumentTrack', 'MMidiTrack')), None)
    if ch is None:
        return None
    body = wk.d[ch.body_at:ch.end]
    name = b'All MIDI Inputs\x00'
    k = body.find(name)
    k = body.find(name, k + 1) if k >= 0 else -1
    if k < 0:
        return None
    at = k + len(name) + (4 if ch.cls.name == 'MMidiTrack' else 0)
    return int.from_bytes(body[at:at + 4], 'big')


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


SYSTEM_FOLDER = 'Input/Output Channels'


def folder_path(wk: Walker, track_event: Obj) -> list[str]:
    """Names of the MFolderTrack ancestors of a track, outermost first.

    A folder holds its own MTrackList, whose body starts with the folder's
    name. Every project has a built-in 'Input/Output Channels' folder holding
    the device, tempo and signature tracks; it is omitted here. An
    instrument stack (Cubase 16) is also an MFolderTrack (tier 2 c18is).
    Folder state flags: folder_state_flags().
    """
    names = []
    for f in sorted((o for o in wk.objects.values() if o.cls.name == 'MFolderTrack'
                     and o.body_at <= track_event.tag_at < o.end), key=lambda o: o.tag_at):
        lst = next((ch for ch in f.children if ch.cls.name == 'MTrackList'), None)
        name = _pstring(wk.d, lst.body_at)[0] if lst else '?'
        if name != SYSTEM_FOLDER:
            names.append(name)
    return names


def folder_state_flags(wk: Walker, folder: Obj) -> int | None:
    """MFolderTrack state flags (bit 0 solo, bit 2 mute, as for tracks): the
    u32 immediately before the folder's MTrackList child (tier 2 c18fm).
    Muting a folder also sets the mute flag on every track inside it, so the
    saved track flags already carry the inherited state."""
    lst = next((ch for ch in folder.children if ch.cls.name == 'MTrackList'), None)
    if lst is None:
        return None
    return int.from_bytes(wk.d[lst.tag_at - 4:lst.tag_at], 'big')


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


# --------------------------------------------------------------- reporting

def _fmt_obj(o: Obj, offsets: bool) -> str:
    bases = ' : ' + ' : '.join(f'{n} v{v}' for n, v in o.cls.bases) if o.kind == 'NEW' and o.cls.bases else ''
    at = f'@{o.tag_at} body {o.body_at}+{o.length} ' if offsets else ''
    return f'{at}{o.cls.name} v{o.cls.version} [{o.kind}] len {o.length}{bases}'


def print_tree(objs: list[Obj], depth: int, offsets: bool, indent: int = 0) -> None:
    for o in objs:
        print('  ' * indent + _fmt_obj(o, offsets))
        if indent + 1 < depth:
            print_tree(o.children, depth, offsets, indent + 1)


def coverage(objs: list[Obj], start: int, end: int) -> int:
    """Bytes in [start, end) not inside any top-level object."""
    covered = sum(o.end - o.tag_at for o in objs)
    return (end - start) - covered


def hexdump(b: bytes, base: int = 0) -> None:
    for i in range(0, len(b), 16):
        c = b[i:i + 16]
        print(f'{base + i:8d}  {c.hex(" "):<48}  ' + ''.join(chr(x) if 32 <= x < 127 else '.' for x in c))


def cmd_roots(a) -> None:
    c = read_container(a.file)
    print(f'{c.path}: {c.magic}, tag width {c.width}')
    for arc in c.archives:
        print(f'  {arc.name:<16} {arc.root_class:<24} {len(arc.data):>9} bytes @ {arc.offset}')


def cmd_tree(a) -> None:
    c = read_container(a.file)
    wk, objs = walk_archive(c, a.archive)
    print_tree(objs, a.depth, a.offsets)
    print(f'-- top-level bytes outside objects: {coverage(objs, 0, len(wk.d))}')


def cmd_classes(a) -> None:
    c = read_container(a.file)
    wk, _ = walk_archive(c, a.archive)
    seen = {}
    for off, cd in sorted(wk.classes.items()):
        seen.setdefault(id(cd), cd)
    counts: dict[int, int] = {}
    for o in wk.objects.values():
        counts[id(o.cls)] = counts.get(id(o.cls), 0) + 1
    for cd in seen.values():
        print(f'{cd.offset:8d}  {cd.name:<36} v{cd.version:<3} objects {counts.get(id(cd), 0):>5}'
              + ('  bases: ' + ', '.join(f'{n} v{v}' for n, v in cd.bases) if cd.bases else ''))


def cmd_notes(a) -> None:
    c = read_container(a.file)
    wk, objs = walk_archive(c, 'Arrangement1')
    for te in sorted((o for o in wk.objects.values() if o.cls.name in TRACK_EVENTS), key=lambda o: o.tag_at):
        flags = track_state_flags(wk, te)
        state = [] if flags is None else [n for bit, n in ((TRACK_MUTE, 'muted'), (TRACK_SOLO, 'soloed')) if flags & bit]
        path = ' / '.join(folder_path(wk, te) + [track_name(wk, te)])
        print(f'track {path!r} [{te.cls.name}] flags {flags}'
              + (f"  ({', '.join(state)})" if state else ''))
        for pe_obj in sorted((o for o in wk.objects.values() if o.cls.name == 'MMidiPartEvent'
                              and te.body_at <= o.tag_at < te.end), key=lambda o: o.tag_at):
            pe = part_event_info(wk, pe_obj)
            if pe.part is None:
                print(f'  part event @{pe_obj.tag_at}: contents not found (linear time base?)')
                continue
            events, problems, info = decode_part_events(wk, pe.part)
            kinds: dict[str, int] = {}
            for e in events:
                kinds[e.kind] = kinds.get(e.kind, 0) + 1
            print(f"  part {info.get('name', '?')!r}: start {pe.start:g} length {pe.length:g} offset {pe.offset:g}"
                  f" flags 0x{pe.flags:04x}{' MUTED' if pe.muted else ''}{' SHARED' if pe.shared else ''}"
                  f" | {len(events)}/{info.get('count')} events {kinds}")
            if pe.shared:
                continue
            for e in events:
                if e.status == 0x90:
                    rel = e.props.get('OffV')
                    relv = round(1 + 126 * rel) if isinstance(rel, float) else None
                    print(f'    note pos {e.position:g}  pitch {e.data[0]}  vel {e.data[1]}  len {e.length:g}'
                          f'  chan {e.channel}  release {relv}  framed {e.framed}')
                else:
                    print(f'    {e.kind} pos {e.position:g}  chan {e.channel}  data {e.data.hex(" ")}'
                          f'  framed {e.framed}')
            for pr in problems:
                print('    !', pr)


def cmd_timeline(a) -> None:
    c = read_container(a.file)
    wk, _ = walk_archive(c, 'Arrangement1')
    for o in sorted(wk.objects.values(), key=lambda o: o.tag_at):
        if o.cls.name == 'MTempoTrackEvent':
            pts, fixed = tempo_points(wk, o)
            print(f'tempo track: {len(pts)} points, trailing tempo {fixed:g}')
            for t in pts:
                print(f'  tick {t.ticks:g} ({t.ticks / 480:g} beats)  {t.bpm:.3f} BPM  at {t.seconds:.6f} s'
                      + ('  ramp' if t.ramp else ''))
        elif o.cls.name == 'MSignatureTrackEvent':
            for ticks, num, den in signature_points(wk, o):
                print(f'signature {num}/{den} at tick {ticks} ({ticks / 480:g} beats)')
    print(f'display bar offset: {display_bar_offset(wk)}')
    for m in markers(wk):
        kind = 'range ' if m.is_range else ''
        end = f' to {(m.start + m.length) / 480:g}' if m.is_range else ''
        print(f'{kind}marker {m.ident} {m.name!r} at {m.start / 480:g} beats{end}')


def cmd_diff(a) -> None:
    A = read_container(a.file_a)
    B = read_container(a.file_b)
    x, y = A.archive(a.archive).data, B.archive(a.archive).data
    if len(x) != len(y):
        print(f'sizes differ: {len(x)} vs {len(y)}; showing first divergence')
        i = next((k for k in range(min(len(x), len(y))) if x[k] != y[k]), min(len(x), len(y)))
        hexdump(x[max(0, i - 32):i + 64], max(0, i - 32))
        print('--')
        hexdump(y[max(0, i - 32):i + 64], max(0, i - 32))
        return
    diffs = [k for k in range(len(x)) if x[k] != y[k]]
    groups: list[list[int]] = []
    for k in diffs:
        if groups and k - groups[-1][1] <= 8:
            groups[-1][1] = k
        else:
            groups.append([k, k])
    wk, _ = walk_archive(A, a.archive)
    for s, e in groups:
        owner = min((o for o in wk.objects.values() if o.body_at <= s < o.end),
                    key=lambda o: o.length, default=None)
        where = f'{owner.cls.name} body+{s - owner.body_at}' if owner else 'top level'
        print(f'{s:8d}  [{where}]\n    {x[max(0, s - 4):e + 5].hex(" ")}\n    {y[max(0, s - 4):e + 5].hex(" ")}')


def cmd_hex(a) -> None:
    c = read_container(a.file)
    d = c.archive(a.archive).data
    hexdump(d[a.start:a.end], a.start)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('roots'); p.add_argument('file'); p.set_defaults(fn=cmd_roots)
    p = sub.add_parser('tree'); p.add_argument('file'); p.add_argument('--archive', default='Arrangement1')
    p.add_argument('--depth', type=int, default=6); p.add_argument('--offsets', action='store_true')
    p.set_defaults(fn=cmd_tree)
    p = sub.add_parser('classes'); p.add_argument('file'); p.add_argument('--archive', default='Arrangement1')
    p.set_defaults(fn=cmd_classes)
    p = sub.add_parser('notes'); p.add_argument('file'); p.set_defaults(fn=cmd_notes)
    p = sub.add_parser('timeline'); p.add_argument('file'); p.set_defaults(fn=cmd_timeline)
    p = sub.add_parser('diff'); p.add_argument('file_a'); p.add_argument('file_b')
    p.add_argument('--archive', default='Arrangement1'); p.set_defaults(fn=cmd_diff)
    p = sub.add_parser('hex'); p.add_argument('file'); p.add_argument('start', type=int); p.add_argument('end', type=int)
    p.add_argument('--archive', default='Arrangement1'); p.set_defaults(fn=cmd_hex)
    a = ap.parse_args(argv)
    a.fn(a)
    return 0


if __name__ == '__main__':
    sys.exit(main())
