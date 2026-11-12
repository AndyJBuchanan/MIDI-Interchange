# Plan: About box

Status: **agreed** (2026-11-12). Not built. Branch, when built: `feature/about-box` from `main`.

An **About** button on the app's toolbar opens a small dialog. The dialog shows the app icon, the program name, the copyright and author, a link to the GitHub page, a short description of what the app does, and an **OK** button.

## Behaviour

- **Opening it:** an **About** button at the far right of the toolbar, against the window's right edge. It's the same on macOS and Windows; nothing goes in the system menus.
- **The dialog:** modal, fixed size, and centred on the main window. Top to bottom, it shows:
  - **Icon:** about 96 px.
  - **Name:** "MIDI Interchange", in bold and larger than the body text.
  - **Version:** for example "Version 0.2.0" (agreed).
  - **Description:** "A MIDI palette for moving MIDI between apps: drag in or import MIDI from one or more apps, pick the tracks and ranges you want, and drag them out or export to another." (Agreed wording.)
  - **Copyright:** "© 2026 Andy Buchanan" (agreed).
  - **Link:** "github.com/AndyJBuchanan/MIDI-Interchange". Clicking it opens `https://github.com/AndyJBuchanan/MIDI-Interchange` in the default browser. The repository is public.
  - **OK:** the default button, so Return, Enter and Esc all close the dialog.
- **Colours:** none new. The dialog uses the app's standard dialog style.

## Decisions (agreed 2026-11-12)

1. **Show the version:** yes.
   - At the moment, only the builds know the version: it sits in `midi_interchange.spec` and isn't available while the app runs.
   - Move the single source to `midi_interchange/__init__.py` (`__version__ = "0.2.0"`), together with its digits-only check.
   - The spec reads it from there. `build_windows.ps1` reads it with its existing regex, pointed at the new file. `build_macos.sh` already reads the version back from Info.plist, so it doesn't change.
   - RELEASING.md is updated to name the new place.
2. **Copyright:** "© 2026 Andy Buchanan". The repo has no licence file; adding one is a separate decision.
3. **Description:** the agreed wording above.

## Code

- **Icon (`ui/app_icon.py`):**
  - `icon_path()` returns nothing in the packaged Mac app, because the Dock takes its icon from the bundle.
  - Add an `about_icon()` beside it. It returns the macOS-grid PNG on macOS and the full PNG elsewhere, whether run from source or packaged. Both PNGs are already bundled by the spec.
  - Icon choice stays in this one file.
- **Dialog:** a new `ui/about_dialog.py`, a `QDialog` with a `QDialogButtonBox` OK button. The link is a `QLabel` with `setOpenExternalLinks(True)`.
- **Text and link:** the name, description, copyright and repository URL live as constants in one place: `ui/about_dialog.py`, except the version, which comes from the package `__init__`. The README is left as it is.
- **Toolbar (`ui/main_window.py`, `_build_toolbar`):** after the last item, add a spacer widget with an expanding size policy, then the About action. This puts the button at the window's right edge. No menu entry and no `AboutRole`.

## Tests (headless)

- The About button is the last item on the toolbar, after an expanding spacer, and clicking it opens the dialog.
- The dialog shows the name, the version (matching `__version__`), the copyright, and the link with the right URL.
- `about_icon()` returns a non-empty image when run from source, and when packaged (simulated by setting `sys.frozen`).
- The spec and the Windows build script read the same version as the package.

## Checklist

On macOS:
- Click **About** at the right end of the toolbar.
- Check the icon, text and link (it opens the GitHub page in the browser).
- Check that OK, Return and Esc each close the dialog.
- Resize the window and check the button stays at the right edge.
- Repeat in the packaged app.

On Windows, at release, check the same button.

## Rules for the build session

- Build only this plan, and only when the user says so.
- If the code doesn't fit the plan, stop and ask rather than designing around it.
- Work on the feature branch named above. Don't switch branches, and don't push.
