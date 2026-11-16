"""Shared reader output; unpackable as (source, tracks) for placement previews."""
from dataclasses import dataclass

from .document import Source, Track


@dataclass
class ImportResult:
    source: Source
    tracks: list[Track]
    # MIDI clip imports join the workspace solo group. Project arrangements can
    # instead preserve their explicit saved mute/solo flags on new tracks.
    preserve_track_state: bool = False

    def __iter__(self):
        yield self.source
        yield self.tracks
