from fractions import Fraction as F

import pytest

from midi_interchange.core.timing import TempoChange, TempoMap, TimeSigChange


def test_defaults():
    tm = TempoMap()
    assert tm.tempo_at(F(10)).bpm == pytest.approx(120)
    ts = tm.timesig_at(F(0))
    assert (ts.numerator, ts.denominator) == (4, 4)


def test_bbt_roundtrip_4_4():
    tm = TempoMap()
    assert tm.to_bbt(F(0)) == (1, 1, 0)
    assert tm.to_bbt(F(5)) == (2, 2, 0)
    assert tm.to_bbt(F(5) + F(1, 4)) == (2, 2, 120)
    assert tm.from_bbt(2, 2, 120) == F(21, 4)
    assert tm.parse_bbt("17") == F(64)
    assert tm.format_bbt(F(64)) == "17.1.000"


def test_timesig_changes():
    # 4/4 for 2 bars, then 3/4, then 6/8 from bar 5
    tm = TempoMap([], [TimeSigChange(F(0), 4, 4), TimeSigChange(F(8), 3, 4), TimeSigChange(F(14), 6, 8)])
    assert tm.bar_start(2) == F(8)
    assert tm.bar_start(3) == F(11)
    assert tm.bar_start(4) == F(14)
    assert tm.bar_start(5) == F(17)
    assert tm.to_bbt(F(12)) == (4, 2, 0)
    assert tm.to_bbt(F(14) + F(1, 2)) == (5, 2, 0)  # eighth-note beats in 6/8
    bars = list(tm.bars(F(0), F(20)))
    assert [b[1] for b in bars] == [0, 4, 8, 11, 14, 17]


def test_midbar_timesig_starts_new_bar():
    tm = TempoMap([], [TimeSigChange(F(0), 4, 4), TimeSigChange(F(6), 3, 4)])
    bars = list(tm.bars(F(0), F(12)))
    assert [(b[1], b[2]) for b in bars] == [(0, 4), (4, 6), (6, 9), (9, 12)]


def test_snap():
    tm = TempoMap()
    assert tm.snap(F(5) + F(1, 3), "beat") == F(5)
    assert tm.snap(F(5) + F(2, 3), "beat") == F(6)
    assert tm.snap(F(5), "bar") == F(4)
    assert tm.snap(F(7), "bar") == F(8)
    assert tm.snap(F(13, 10), F(1, 4)) == F(5, 4)
    assert tm.snap(F(13, 10), None) == F(13, 10)
    assert tm.snap(F(-3), "bar") == 0


def test_seconds_with_tempo_change():
    tm = TempoMap([TempoChange(F(0), 500000), TempoChange(F(4), 1000000)], [])
    assert tm.seconds_at(F(4)) == pytest.approx(2.0)
    assert tm.seconds_at(F(6)) == pytest.approx(4.0)


def test_equivalence_and_dedupe():
    a = TempoMap([TempoChange(F(0), 500000)], [])
    b = TempoMap([], [TimeSigChange(F(0))])
    assert a.equivalent(b)  # both equal the defaults
    c = TempoMap([TempoChange(F(0), 400000), TempoChange(F(0), 500000)], [])
    assert len(c.tempos) == 1 and c.tempos[0].us_per_beat == 500000
