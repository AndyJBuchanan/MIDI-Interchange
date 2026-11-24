"""Controller data as a displayable line (docs/plans/0.5.0/controller-display.md).

Pure, no Qt, display only: nothing here changes a clip, an import or an export.
A controller is named by a short key: ``"pb"`` (pitch bend), ``"at"`` (channel
aftertouch) or ``"cc7"`` (a continuous controller). A clip's line follows the
edge rules export writes (``export_smf._extract_clips``): an untrimmed start has
nothing before its first event, a trimmed start begins at the value carried in
from before the trim, and nothing after a trimmed end is shown.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from functools import cached_property
from fractions import Fraction

from .document import Clip
from .events import MODE_CCS
from .export_smf import clip_window, visible_msgs
from .simplify import SEQUENCE_CCS
from .timing import ZERO

PITCH_BEND = "pb"
AFTERTOUCH = "at"

CC_NAMES = {
    1: "Mod Wheel", 2: "Breath", 4: "Foot Controller", 5: "Portamento Time", 7: "Volume",
    8: "Balance", 10: "Pan", 11: "Expression", 64: "Sustain", 65: "Portamento",
    66: "Sostenuto", 67: "Soft Pedal", 68: "Legato", 71: "Resonance", 72: "Release",
    73: "Attack", 74: "Brightness", 91: "Reverb", 93: "Chorus",
}

_CC_KEY = re.compile(r"cc(0|[1-9][0-9]{0,2})")


def cc_key(number: int) -> str:
    return f"cc{number}"


def is_listed_cc(number: int) -> bool:
    """CCs that are curves: not the sequence controllers (bank select, data entry,
    RPN/NRPN: the set Simplify never touches) and not channel mode messages."""
    return 0 <= number <= 127 and number not in SEQUENCE_CCS and number not in MODE_CCS


def parse_key(key) -> tuple[str, int | None] | None:
    """("pb", None), ("at", None) or ("cc", number) for a well-formed, listed key, else None."""
    if key == PITCH_BEND or key == AFTERTOUCH:
        return key, None
    if type(key) is str:
        m = _CC_KEY.fullmatch(key)
        if m and is_listed_cc(int(m.group(1))):
            return "cc", int(m.group(1))
    return None


def is_valid_key(key) -> bool:
    return parse_key(key) is not None


def sort_key(key: str) -> tuple[int, int]:
    """Picker order: Pitch Bend, Aftertouch, then CCs in number order."""
    kind, number = parse_key(key)
    return (0, 0) if kind == "pb" else (1, 0) if kind == "at" else (2, number)


def label(key: str) -> str:
    """The long label: "Pitch Bend", "Aftertouch", "7 Volume", or "CC 20" when unnamed."""
    kind, number = parse_key(key)
    if kind == "pb":
        return "Pitch Bend"
    if kind == "at":
        return "Aftertouch"
    name = CC_NAMES.get(number)
    return f"{number} {name}" if name else f"CC {number}"


def short_label(key: str) -> str:
    """The short form for a track's box: CC1, CC11, PB, AT."""
    kind, number = parse_key(key)
    return "PB" if kind == "pb" else "AT" if kind == "at" else f"CC{number}"


def _key_of(msg) -> str | None:
    """The key a message belongs to, if it is a listed controller."""
    t = msg.type
    if t == "control_change":
        return cc_key(msg.control) if is_listed_cc(msg.control) else None
    if t == "pitchwheel":
        return PITCH_BEND
    if t == "aftertouch":
        return AFTERTOUCH
    return None


def _audible(clip: Clip) -> Clip:
    """The clip as if not muted: the display counts muted clips, which export skips."""
    return replace(clip, muted=False) if clip.muted else clip


def clip_controllers(clip: Clip) -> list[str]:
    """The keys a clip shows, in picker order. From what the clip's trims leave
    (the same cutting as an export), so a controller only in a trimmed-away
    part is not listed."""
    found = {k for k in map(_key_of, visible_msgs(_audible(clip))) if k is not None}
    return sorted(found, key=sort_key)


def scale(msg) -> float:
    """A controller message's value as 0 (bottom) to 1 (top). Pitch bend has its
    centre (mido 0, i.e. 8192) at exactly 0.5."""
    if msg.type == "pitchwheel":
        return (msg.pitch + 8192) / 16384
    return msg.value / 127


@dataclass(frozen=True)
class ControllerLine:
    """One controller line of a clip. Times are quarter notes from the clip's start."""
    times: tuple[float, ...]        # events inside the visible span, sorted
    values: tuple[float, ...]       # 0..1, same length
    carried: float | None           # value carried into a trimmed start (None: untrimmed, or none before)
    start: float                    # where ``carried`` begins (the visible start)

    @cached_property
    def series(self) -> tuple[list[float], list[float]]:
        """Times and values as drawn: the carried value first, when there is one (built once)."""
        if self.carried is None:
            return list(self.times), list(self.values)
        return [self.start, *self.times], [self.carried, *self.values]


def controller_points(clip: Clip, key: str, channel: int | None) -> ControllerLine | None:
    """The line of one controller on one channel (0-15), or on every channel merged
    when ``channel`` is None (what a set export channel gives the receiving DAW).
    None when the clip shows no such data."""
    kind, number = parse_key(key)
    lo, hi = clip_window(clip, ZERO, None)
    off = clip.offset
    times: list[float] = []
    values: list[float] = []
    carry: tuple[Fraction, int, float] | None = None
    for ev in clip.events:
        m = ev.msg
        if _key_of(m) != key or (channel is not None and m.channel != channel):
            continue
        t = ev.time + off
        if t >= lo and (hi is None or t < hi):
            times.append(float(ev.time))
            values.append(scale(m))
        elif t < lo and (hi is None or t < hi):     # export's rule: nothing is carried past a trimmed end
            if carry is None or (ev.time, ev.seq) >= carry[:2]:
                carry = (ev.time, ev.seq, scale(m))
    if not times and carry is None:
        return None
    return ControllerLine(tuple(times), tuple(values), None if carry is None else carry[2], float(lo - off))


def controller_lines(clip: Clip, key: str, merged: bool) -> list[ControllerLine]:
    """A clip's lines for a key: one per channel, or one merged line."""
    if merged:
        line = controller_points(clip, key, None)
        return [] if line is None else [line]
    channels = sorted({ev.msg.channel for ev in clip.events if _key_of(ev.msg) == key})
    lines = (controller_points(clip, key, c) for c in channels)
    return [ln for ln in lines if ln is not None]
