"""MIDI Interchange."""
import re as _re

# Single source of the app version. See docs/RELEASING.md before changing it.
# Shown in the About box. midi_interchange.spec reads it for the macOS Info.plist, the Windows exe
# version resource, the Windows installer and every artifact file name (build_macos.sh reads it back
# from Info.plist; build_windows.ps1 reads this line with a regex, so keep it a plain
# "MAJOR.MINOR.PATCH" literal).
# Numbers only: macOS and Windows both reject suffixes such as "-pre". Pre-release labels go on the
# git tag / GitHub release instead (e.g. __version__ "0.1.0" is released as tag v0.1.0-pre).
__version__ = "0.4.0"

if not _re.fullmatch(r"\d+\.\d+\.\d+", __version__):
    raise SystemExit(f'midi_interchange/__init__.py: __version__ must be MAJOR.MINOR.PATCH digits only, got "{__version__}". '
                     "Put labels like -pre on the git tag, not here (docs/RELEASING.md).")
