#!/usr/bin/env python3
"""Read-only research inspector for Cubase .cpr project files.

Not part of the app. Used to reverse-engineer the native format from project
files we saved ourselves (see docs/plans/0.4.0/cubase-import.md). It never writes to
the input files.

Usage:
    cpr_inspect.py roots FILE                 list ROOT/ARCH records
    cpr_inspect.py tree FILE [--archive NAME] [--depth N] [--offsets]
    cpr_inspect.py classes FILE [--archive NAME]
    cpr_inspect.py notes FILE                 tracks, parts (mute, trims, shared) and events
    cpr_inspect.py timeline FILE              tempo, signatures, display offset, markers
    cpr_inspect.py diff FILE_A FILE_B [--archive NAME]
    cpr_inspect.py hex FILE START END [--archive NAME]

The format decoding lives in midi_interchange/core/cpr_format.py (shared with
the app's reader). Format notes (details in the plan):

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
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from midi_interchange.core.cpr_format import *  # noqa: E402,F401,F403
from midi_interchange.core.cpr_format import _pstring  # noqa: E402,F401


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
