"""Clip assembly: drop placement, moving clips between tracks, clip tools, New."""
from fractions import Fraction as F

import pytest

from helpers import conductor, load, note, notes_of, reparse, smf, track, track_by_name

from midi_interchange.core.document import Workspace
from midi_interchange.core.export_smf import ExportMode, ExportOptions, build_exports
from midi_interchange.core.import_smf import import_smf_bytes
from midi_interchange.core.placement import Placement, names_match, place_imports


def part(name: str, pitch: int = 60, beats: int = 4, ppq: int = 480, ch: int = 0) -> bytes:
    """A DAW-style dragged part: one named track, notes from time zero."""
    ev = []
    for b in range(beats):
        ev += note(ch, pitch + b, b * ppq, ppq // 2)
    return smf([conductor(ppq), track(ev, name=name)], ppq=ppq)


def parse(*parts: tuple[bytes, str]):
    return [import_smf_bytes(data, fname) for data, fname in parts]


def export_whole(ws):
    return reparse(build_exports(ws, ExportOptions(mode=ExportMode.WHOLE))[0].midi)


# -- placement --------------------------------------------------------------------
def test_drop_on_empty_area_makes_new_track_at_time():
    ws = Workspace()
    place_imports(ws, parse((part("Bass"), "a.mid")), Placement(F(16)))
    assert [t.name for t in ws.tracks] == ["Bass"]
    assert ws.tracks[0].clips[0].start == 16


def test_drop_on_matching_track_adds_clip_there():
    ws = load(part("Bass"), "a.mid")
    target = ws.tracks[0]
    _, stats = place_imports(ws, parse((part("  bass ", pitch=40), "b.mid")), Placement(F(32), target.id))
    assert len(ws.tracks) == 1 and stats["new_tracks"] == 0 and stats["onto_existing"] == 1
    assert [c.start for c in target.clips] == [0, 32]
    # both sources survive and export covers both clips on one track
    assert len(ws.sources) == 2
    out = export_whole(ws)
    starts = [n[0] for n in notes_of(track_by_name(out, "Bass"), out.ticks_per_beat)]
    assert starts[:1] == [0] and 32 in starts


def test_drop_on_other_named_track_makes_new_track():
    ws = load(part("Bass"), "a.mid")
    place_imports(ws, parse((part("Keys"), "k.mid")), Placement(F(8), ws.tracks[0].id))
    assert [t.name for t in ws.tracks] == ["Bass", "Keys"]
    assert ws.tracks[1].clips[0].start == 8


def multi(*names_pitches, ppq=480) -> bytes:
    """A multi-track file (e.g. a Staccato round trip): one named track per entry."""
    trs = [conductor(ppq)]
    for name, pitch in names_pitches:
        trs.append(track([*note(0, pitch, 0, ppq)], name=name))
    return smf(trs, ppq=ppq)


def test_multi_track_drop_on_matching_track_matches_every_track_by_name():
    ws = load(multi(("Bass", 40), ("Keys", 60), ("Drums", 36)), "song.mid")
    bass, keys, drums = ws.tracks
    # round trip: same tracks plus one new one, dropped on the Keys lane at beat 16
    _, stats = place_imports(ws, parse((multi(("drums", 36), ("Bass", 41), ("Keys", 61), ("Pad", 72)), "rt.mid")),
                             Placement(F(16), keys.id))
    assert [t.name for t in ws.tracks] == ["Bass", "Keys", "Drums", "Pad"]
    assert [c.start for c in bass.clips] == [0, 16]
    assert [c.start for c in keys.clips] == [0, 16]
    assert [c.start for c in drums.clips] == [0, 16]
    assert ws.tracks[3].clips[0].start == 16
    assert stats["onto_existing"] == 3 and stats["new_tracks"] == 1
    assert stats["onto_names"] == ["Drums", "Bass", "Keys"]


def test_exact_overlap_replaces_existing_clip():
    ws = load(multi(("Bass", 40), ("Keys", 60)), "song.mid")
    bass, keys = ws.tracks
    old_source = ws.sources[0].id
    rt = multi(("Bass", 41), ("Keys", 61))
    _, stats = place_imports(ws, parse((rt, "rt.mid")), Placement(F(0), bass.id))
    assert stats["replaced"] == 2
    assert len(bass.clips) == 1 and len(keys.clips) == 1
    assert bass.clips[0].source_id != old_source
    # the old source lost its last clip; kept only because it is the tempo source
    assert {s.id for s in ws.sources} >= {bass.clips[0].source_id}
    assert all(any(c.source_id == s.id for t in ws.tracks for c in t.clips) or s.id == ws.tempo_source_id
               for s in ws.sources)


def test_replaced_clip_source_is_pruned():
    ws = load(multi(("Keys", 60)), "song.mid")             # tempo source
    keys = ws.tracks[0]
    place_imports(ws, parse((part("Bass", 40), "b1.mid")), Placement(F(8)))
    first_bass_src = ws.sources[1].id
    bass = ws.tracks[1]
    place_imports(ws, parse((part("Bass", 41), "b2.mid")), Placement(F(8), bass.id))
    assert len(bass.clips) == 1 and bass.clips[0].source_id != first_bass_src
    assert first_bass_src not in {s.id for s in ws.sources} and len(ws.sources) == 2
    assert len(keys.clips) == 1


def test_partial_overlap_is_kept():
    ws = load(multi(("Bass", 40)), "song.mid")
    bass = ws.tracks[0]
    _, stats = place_imports(ws, parse((multi(("Bass", 41)), "rt.mid")), Placement(F(1, 2), bass.id))
    assert stats["replaced"] == 0 and len(bass.clips) == 2 and bass.overlaps()


def test_clips_from_the_same_drop_are_not_replaced():
    ws = load(multi(("Bass", 40)), "song.mid")
    bass = ws.tracks[0]
    place_imports(ws, parse((multi(("Bass", 41)), "a.mid"), (multi(("Bass", 42)), "b.mid")),
                  Placement(F(8), bass.id))
    assert [c.start for c in bass.clips] == [0, 8, 8]


def test_drop_on_unmatched_track_matches_nothing():
    ws = load(multi(("Bass", 40), ("Keys", 60), ("Strings", 70)), "song.mid")
    strings = ws.tracks[2]
    place_imports(ws, parse((multi(("Bass", 41), ("Keys", 61)), "rt.mid")), Placement(F(8), strings.id))
    assert [t.name for t in ws.tracks] == ["Bass", "Keys", "Strings", "Bass", "Keys"]
    assert all(len(t.clips) == 1 for t in ws.tracks)


def test_drop_on_empty_area_never_matches():
    ws = load(multi(("Bass", 40), ("Keys", 60)), "song.mid")
    place_imports(ws, parse((multi(("Bass", 41), ("Keys", 61)), "rt.mid")), Placement(F(8)))
    assert [t.name for t in ws.tracks] == ["Bass", "Keys", "Bass", "Keys"]


def test_target_wins_over_other_same_named_tracks():
    ws = load(multi(("Bass", 40), ("Bass", 45)), "song.mid")
    first, second = ws.tracks
    place_imports(ws, parse((part("Bass"), "b.mid")), Placement(F(8), second.id))
    assert len(first.clips) == 1 and len(second.clips) == 2


def test_all_at_cursor_does_not_match_tracks_made_by_the_same_drop():
    ws = load(multi(("Keys", 60), ("Bass", 40)), "song.mid")
    keys = ws.tracks[0]
    place_imports(ws, parse((multi(("Keys", 61), ("Pad", 72)), "1.mid"), (part("Pad"), "2.mid")),
                  Placement(F(4), keys.id))
    assert [t.name for t in ws.tracks] == ["Keys", "Bass", "Pad", "Pad"]


def test_match_uses_original_name_after_rename():
    ws = load(part("Bass"), "a.mid")
    ws.tracks[0].name = "Bass line (verse)"
    assert names_match(ws.tracks[0], "BASS")


def test_end_to_end_lays_files_in_sequence_and_joins_same_names():
    ws = Workspace()
    parsed = parse((part("Bass", beats=4), "1.mid"), (part("Bass", beats=8), "2.mid"),
                   (part("Keys", beats=4), "3.mid"))
    place_imports(ws, parsed, Placement(F(4), end_to_end=True))
    assert [t.name for t in ws.tracks] == ["Bass", "Keys"]
    bass, keys = ws.tracks
    assert [c.start for c in bass.clips] == [4, 4 + bass.clips[0].length]
    assert keys.clips[0].start == bass.clips[1].end


def test_all_at_cursor_keeps_files_on_separate_tracks():
    ws = Workspace()
    place_imports(ws, parse((part("Bass"), "1.mid"), (part("Bass"), "2.mid")), Placement(F(4)))
    assert len(ws.tracks) == 2 and all(t.clips[0].start == 4 for t in ws.tracks)


# -- clip moves -------------------------------------------------------------------
@pytest.fixture
def two():
    ws = Workspace()
    place_imports(ws, parse((part("Bass", pitch=40), "b.mid"), (part("Keys", pitch=70, ch=1), "k.mid")),
                  Placement())
    return ws


def test_move_clip_to_other_track_then_empty_track_removed(two):
    bass, keys = two.tracks
    cid = keys.clips[0].id
    two.move_clip_to_track(cid, bass.id, F(16))
    assert keys.clips == [] and len(bass.clips) == 2
    assert bass.channels == (0, 1)   # mixed channels are kept, not rewritten (see INTEROP_FINDINGS)
    two.remove_empty_tracks()
    assert [t.name for t in two.tracks] == ["Bass"]
    assert len(two.sources) == 2     # the moved clip still references its own source


def test_overlap_detection(two):
    bass, keys = two.tracks
    two.move_clip_to_track(keys.clips[0].id, bass.id, F(2))
    assert bass.overlaps() == [(F(2), bass.clips[0].end)]


def test_new_track_for_clip_and_duplicate_and_delete(two):
    bass = two.tracks[0]
    dup = two.duplicate_clip(bass.clips[0].id)
    assert dup.start == bass.clips[0].end and len(bass.clips) == 2
    t = two.new_track_for_clip(dup.id)
    assert t.name == "Bass" and t.clips == [dup] and len(two.tracks) == 3
    two.delete_clip(dup.id)
    assert len(two.tracks) == 2


def test_butt_against_previous(two):
    bass = two.tracks[0]
    dup = two.duplicate_clip(bass.clips[0].id, offset=F(20))
    assert two.snap_clip_to_previous(dup.id)
    assert dup.start == bass.clips[0].end
    assert not two.snap_clip_to_previous(bass.clips[0].id)


def test_merge_tracks(two):
    bass, keys = two.tracks
    two.merge_tracks(keys.id, bass.id)
    assert [t.name for t in two.tracks] == ["Bass"] and len(bass.clips) == 2


def test_export_ppq_covers_moved_clip_sources():
    ws = Workspace()
    place_imports(ws, parse((part("A", ppq=96), "a.mid"), (part("B", ppq=120), "b.mid")), Placement())
    a, b = ws.tracks
    ws.move_clip_to_track(b.clips[0].id, a.id, F(8))
    ws.remove_empty_tracks()
    out = export_whole(ws)
    assert out.ticks_per_beat % 96 == 0 and out.ticks_per_beat % 120 == 0


def test_clear():
    ws = load(part("Bass"))
    ws.clear()
    assert not (ws.tracks or ws.sources or ws.ranges) and ws.tempo_source_id is None
