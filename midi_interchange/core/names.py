"""Every naming rule, in one place (2026-11-10, after the drop preview and the
drop drifted apart): comparing track names, song titles, range labels and
file names. Nothing else should normalise, compare or clean names itself.
"""
from __future__ import annotations

SONG_SEP = " - "
FILE_CHARS = " -_()+"            # allowed in file names besides letters and digits


def norm_name(name: str) -> str:
    """A name as compared: whitespace collapsed, case folded."""
    return " ".join(name.split()).casefold()


def tidy(name: str) -> str:
    """A name as shown: whitespace collapsed, case kept."""
    return " ".join(name.split())


def song_title(conductor_name: str, track_names: list[str]) -> str:
    """The song a file's tracks belong to, when it can be known (2026-11-10).

    Staccato names every track "part - song" and puts the song in the first
    (conductor) track, and changes the song between generations, so name
    matching removes a known song title from both sides (see without_song).
    Known means either:
    * the conductor track's name, when some track name ends in " - <it>";
    * else an ending " - X" that every named track shares (at least two), as
      in a file that has been through an app that drops the conductor name.
    Ranges such as "Lead - Verse" / "Bass - Chorus" give no song: their
    endings differ. A single-track file never has one.
    """
    names = [norm_name(n) for n in track_names if n.strip()]
    c = tidy(conductor_name)
    if c and any(n.endswith(norm_name(SONG_SEP + c)) for n in names):
        return c
    if len(names) >= 2 and all(SONG_SEP in n for n in names):
        tails = {n.rpartition(SONG_SEP)[2] for n in names}
        if len(tails) == 1:
            return tidy(next(n for n in track_names if n.strip())).rpartition(SONG_SEP)[2]
    return ""


def without_song(name: str, songs) -> set[str]:
    """The compared name, plus the name with each known song title removed from its end."""
    n = norm_name(name)
    out = {n} if n else set()
    for song in songs:
        suffix = SONG_SEP + norm_name(song) if song.strip() else ""
        if suffix and n.endswith(suffix) and len(n) > len(suffix):
            out.add(n[:-len(suffix)])
    return out


def quoted(items, limit: int | None = 3) -> str:
    """Names for a message: “a”, “b”, “c” …"""
    items = list(items)
    shown = items if limit is None else items[:limit]
    return ", ".join(f"“{x}”" for x in shown) + (" …" if len(shown) < len(items) else "")


def range_label(name: str, index: int) -> str:
    """How a range is called in the UI and in file names: its name, else "Range n" (index from 0)."""
    return name or f"Range {index + 1}"


def safe_filename(label: str, fallback: str = "MIDI") -> str:
    """A label made safe for a file name: other characters become "_"."""
    return "".join(c if c.isalnum() or c in FILE_CHARS else "_" for c in label).strip() or fallback
