#!/usr/bin/env python3
"""Research CLI for Reason song files (.reason). Read-only.

  reason_inspect.py copies FILE          container: header, index pages, song copies
  reason_inspect.py tree FILE [DEPTH]    chunk tree of the current song's RS10 body
  reason_inspect.py tracks FILE          decoded tracks, lanes, clips, notes
  reason_inspect.py diff A B [FILTER]    leaf chunks that differ between two songs

Findings: docs/plans/0.4.0/reason-import.md. Decoding: midi_interchange/core/reason_format.py.
"""
from __future__ import annotations

import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from midi_interchange.core import reason_format as rf  # noqa: E402


def load(path: str) -> bytes:
    with open(path, 'rb') as f:
        return f.read()


def cmd_copies(path: str) -> None:
    data = load(path)
    h = rf.read_header(data)
    print(f'pages {rf.page_count(data, h)} x {h.page_size}')
    for i, sl in enumerate(h.slots):
        print(f'  header slot {i}: generation {sl.generation}, index page {sl.index_page}, crc {"ok" if sl.valid else "BAD"}')
    for n in range(rf.page_count(data, h)):
        if rf.page(data, h, n)[:8] != rf.INDEX_MARK:
            continue
        try:
            idx = rf.read_index(data, h, n)
        except rf.ReasonFormatError as e:
            print(f'  index page {n}: {e}')
            continue
        for sid, (size, pages) in sorted(idx.items()):
            tag = ''
            if sid == rf.SONG_STREAM:
                s = rf.read_stream(data, h, size, pages)
                tag = 'song, hash ok' if rf.song_hash_ok(s) else 'song, HASH FAILS'
                if rf.song_hash_ok(s):
                    song = rf.read_song(s)
                    tag += f", {song.generation}, Reason {song.metadata.get('PROGRAMVERSION', '?')}"
            print(f'  index page {n}: stream {sid} {size} bytes pages {pages[:8]}{"..." if len(pages) > 8 else ""} {tag}')
    copy, notes = rf.current_song(data)
    print(f'current: index page {copy.index_page}', *notes)


def _walk(song: rf.Song, chunks, depth: int, limit: int) -> None:
    for c in chunks:
        if c.kids:
            print(f"{'  ' * depth}{c.name} ({c.size})")
            if depth < limit:
                _walk(song, c.kids, depth + 1, limit)
        else:
            b = song.bytes_of(c)
            print(f"{'  ' * depth}{c.name} {c.size}  {b[:24].hex(' ')}{' ...' if len(b) > 24 else ''}")


def cmd_tree(path: str, depth: str = '99') -> None:
    song, _ = rf.open_song(load(path))
    print(f'{song.generation}  metadata {song.metadata}')
    _walk(song, song.body, 0, int(depth))


def beats(t: int) -> str:
    return f'{t / rf.PPQ:g}'


def cmd_tracks(path: str) -> None:
    song, notes = rf.open_song(load(path))
    print(f"{song.generation} Reason {song.metadata.get('PROGRAMVERSION', '?')}", *notes)
    for t in rf.tracks(song):
        print(f'track {t.index} {t.name!r} device={t.info.device:#x} kind={t.info.kind:#x}{" MUTED" if t.info.muted else ""}')
        for lane in t.lanes:
            print(f'  lane {lane.info.name!r} kind={lane.info.kind:#x}{" MUTED" if lane.info.muted else ""}')
            for c in lane.clips:
                i = c.info
                extra = f' block {c.block}' if c.block else ''
                print(f'    {c.kind} clip {i.name!r} at {beats(i.start)} len {beats(i.length)}{extra}{" MUTED" if i.muted else ""}')
                for n in c.notes:
                    print(f'      note {n.pitch} vel {n.velocity} at +{beats(n.pos)} len {beats(n.length)}')
                for cl in c.controllers:
                    print(f'      controller {cl.lane_id:#x} [{cl.lo}..{cl.hi}] {len(cl.points)} points')
                if c.automation:
                    a = c.automation
                    print(f'      automation kind {a.kind} [{a.lo}..{a.hi}] ' +
                          ', '.join(f'+{beats(p.pos)}={p.value}' for p in a.points))


def _leaves(song: rf.Song):
    cnt: dict = collections.defaultdict(collections.Counter)

    def rec(chunks, prefix):
        for c in chunks:
            cnt[prefix][c.name] += 1
            p = f'{prefix}/{c.name}[{cnt[prefix][c.name] - 1}]'
            if c.kids:
                yield from rec(c.kids, p)
            else:
                yield p, song.bytes_of(c)
    return dict(rec(song.body, ''))


def cmd_diff(a: str, b: str, filt: str = '') -> None:
    sa, _ = rf.open_song(load(a))
    sb, _ = rf.open_song(load(b))
    la, lb = _leaves(sa), _leaves(sb)
    for p in list(la) + [p for p in lb if p not in la]:
        if filt not in p:
            continue
        if p not in lb:
            print('-', p, len(la[p]), la[p][:48].hex())
        elif p not in la:
            print('+', p, len(lb[p]), lb[p][:48].hex())
        elif la[p] != lb[p]:
            print('~', p, len(la[p]), '->', len(lb[p]))
            if len(la[p]) < 200 and len(lb[p]) < 200:
                print('   A', la[p].hex())
                print('   B', lb[p].hex())


def main(argv: list[str]) -> int:
    cmds = {'copies': cmd_copies, 'tree': cmd_tree, 'tracks': cmd_tracks, 'diff': cmd_diff}
    if len(argv) < 3 or argv[1] not in cmds:
        print(__doc__)
        return 2
    cmds[argv[1]](*argv[2:])
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
