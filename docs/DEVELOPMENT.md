# Development Guide

How to set up, run, test and build MIDI Interchange on a new machine, from the terminal or from Visual Studio Code.

For what the app is and why it's built this way, see [DESIGN_BRIEF.md](DESIGN_BRIEF.md) (the original spec) and [DESIGN_NOTES.md](DESIGN_NOTES.md) (decisions, status and gaps).

## Prerequisites

| Tool | macOS | Windows |
|---|---|---|
| Git | `xcode-select --install` or Homebrew `brew install git` | [git-scm.com](https://git-scm.com/download/win) |
| Python **3.12 or newer**, 64-bit | `brew install python@3.12` or the python.org installer | python.org installer. Tick "Add python.exe to PATH" and keep the `py` launcher. Or `winget install Python.Python.3.12` |
| VS Code (optional) | [code.visualstudio.com](https://code.visualstudio.com) | same |

Nothing else needs a system-wide install. PySide6 (Qt), mido, pytest and PyInstaller all go into a project-local virtual environment from `requirements*.txt`. There are no C/C++ build tools to install.

Development so far has been on macOS (Apple silicon) with Python 3.12 and PySide6 6.12. Windows is a target, but **the app hasn't been run on Windows yet**. Linux will probably work for development, but nobody has tried it.

## Get the code

The repository has no remote yet. To move it to another machine, either push it to a Git host first:

```bash
git remote add origin <your-repo-url>
```
```bash
git push -u origin main
```

and clone it on the other machine:

```bash
git clone <your-repo-url> MID-Xfr-App
```

or make a single-file bundle and copy it across:

```bash
git bundle create midi-interchange.bundle --all
```
```bash
git clone midi-interchange.bundle MID-Xfr-App
```

Don't copy `.venv/`. Virtual environments contain absolute paths and platform-specific binaries, so recreate it on each machine.

## Terminal workflow

### macOS / Linux

```bash
cd MID-Xfr-App
```
```bash
python3.12 -m venv .venv
```
```bash
.venv/bin/python -m pip install -U pip
```
```bash
.venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt
```
```bash
.venv/bin/python -m pytest -q
```
```bash
.venv/bin/python main.py samples/*.mid
```

### Windows (PowerShell)

```powershell
cd MID-Xfr-App
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -U pip
.venv\Scripts\python -m pip install -r requirements.txt -r requirements-dev.txt
.venv\Scripts\python -m pytest -q
.venv\Scripts\python main.py samples\piano_96bpm.mid samples\bass_96ppq.mid samples\vocal_lyrics.mid samples\drums_format0.mid
```

PowerShell doesn't expand `*.mid` for the program, so either list the files or start with no arguments and drop files onto the window.

### Everyday commands

| Task | Command (swap `.venv/bin/python` for `.venv\Scripts\python` on Windows) |
|---|---|
| Run the app | `.venv/bin/python main.py [files…]` |
| Run all tests | `.venv/bin/python -m pytest -q` |
| Run one test | `.venv/bin/python -m pytest -q tests/test_export.py::test_concatenate_in_user_order` |
| Regenerate `samples/` | `.venv/bin/python tools/make_demo_midi.py` |
| Build a standalone macOS app | `scripts/build_macos.sh` → `dist/MIDI Interchange.app` |
| Build a standalone Windows app | `powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1` → `dist\MIDI Interchange\MIDI Interchange.exe` |

The tests need no display. `tests/conftest.py` sets `QT_QPA_PLATFORM=offscreen`, so the GUI tests also run over SSH and in CI. `samples/` is committed because `tests/test_ui.py` loads those files.

## Visual Studio Code

The repository includes ready-made VS Code configuration in `.vscode/`.

### Extensions

When you open the folder, VS Code suggests these (from `.vscode/extensions.json`):

| Extension | ID | Why |
|---|---|---|
| Python | `ms-python.python` | Interpreter selection, venv activation, Test Explorer (pytest) |
| Pylance | `ms-python.vscode-pylance` | Language server: completion, type checking, go-to-definition into PySide6 and mido |
| Python Debugger | `ms-python.debugpy` | The `debugpy` launch configurations (breakpoints in app code and tests) |

Accept the "install recommended extensions" prompt, or install them from the command line:

```bash
code --install-extension ms-python.python --install-extension ms-python.vscode-pylance --install-extension ms-python.debugpy
```

Optional extras: GitLens or Git Graph for history, and markdownlint for the docs. No Qt-specific extension is needed. The UI is built in code, with no `.ui` or QML files.

### First-time setup in VS Code

1. **File ▸ Open Folder…** and choose the repository root.
2. Create the environment: **Terminal ▸ Run Task… ▸ Setup: create .venv and install deps**. Alternatively, use **Python: Create Environment** (⇧⌘P / Ctrl+Shift+P), choose **Venv**, then Python 3.12, and tick both `requirements.txt` and `requirements-dev.txt`.
3. **Python: Select Interpreter** and choose `./.venv/bin/python` (macOS) or `.\.venv\Scripts\python.exe` (Windows). The workspace setting points at the macOS/Linux path; Windows needs this one-time choice.
4. Open the **Testing** panel (the flask icon). The tests are discovered automatically from `tests/`.

### Running and debugging (Run and Debug panel, F5)

Launch configurations from `.vscode/launch.json`:

| Configuration | What it does |
|---|---|
| **MIDI Interchange** | Starts `main.py` under the debugger with an empty workspace |
| **MIDI Interchange (demo samples)** | Starts with the four files in `samples/` already loaded |
| **pytest: all** | Runs the whole suite under the debugger (breakpoints work in tests and library code) |
| **pytest: current file** | Runs only the test file open in the editor |

Breakpoints work in Qt slots, paint code and event handlers. The app pauses while it's stopped at a breakpoint, which is normal. You can also run or debug a single test from the gutter icon next to it.

### Tasks (Terminal ▸ Run Task…)

From `.vscode/tasks.json`. Each one picks the macOS/Linux or Windows command automatically.

| Task | Shortcut |
|---|---|
| Setup: create .venv and install deps | |
| Generate demo samples | |
| Run tests | default **test** task |
| Run app | |
| Build standalone app | default **build** task, ⇧⌘B / Ctrl+Shift+B |

## Building standalone apps

`scripts/build_macos.sh` and `scripts/build_windows.ps1` create a separate `.venv-build/`, install the requirements, and run PyInstaller with `midi_interchange.spec`. The spec leaves out unused Qt modules (WebEngine, QML/Quick, Multimedia and so on). On macOS it also produces a `.app` bundle that registers `.mid`, `.midi` and `.smf` document types.

- Build on the platform you're targeting. PyInstaller doesn't cross-compile, so build the Windows exe on Windows and the macOS app on a Mac.
- A macOS build runs on the CPU architecture it was built on (arm64 on Apple silicon). The bundle isn't code-signed or notarised. On another Mac, Gatekeeper blocks it until you right-click ▸ Open, or until signing is added.
- **These builds haven't been run yet**, so expect some first-run fixes (hidden imports, the icon, signing).

## Project layout and conventions

```
main.py                        entry point; macOS FileOpen handling; CLI paths
midi_interchange/core/         pure Python model, timing, SMF import/export (no Qt imports)
midi_interchange/interchange/  drag-in payload extraction, drag-out temp files
midi_interchange/ui/           PySide6 controller, timeline, track panel, export panel, theme
tests/                         pytest suite (helpers.py builds synthetic SMFs)
tools/make_demo_midi.py        regenerates samples/
scripts/                       PyInstaller build scripts
docs/                          brief, design notes, this guide
```

- Keep `midi_interchange/core` free of Qt so it can be tested without a GUI.
- Widgets change the workspace only through `ui/controller.py`. Call `checkpoint()` before a change you want to be undoable.
- Add a regression test for any change to import or export behaviour. Round-trip and boundary tests are in `tests/test_roundtrip.py` and `tests/test_export.py`.
- Record decisions or changes of direction in `docs/DESIGN_NOTES.md`. Don't edit `docs/DESIGN_BRIEF.md`.
- Record DAW interop results in the README checklist. Only tick a box once that drag has actually been tested.

## Troubleshooting

- **`python3.12: command not found`.** Use any Python 3.12 or newer (`python3.13 -m venv .venv`), or install 3.12 as shown above. On Windows use `py -0` to list the installed versions.
- **PowerShell won't run scripts.** Use `powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1`, or call `.venv\Scripts\python` directly rather than activating the venv.
- **Qt "could not load the platform plugin".** Recreate `.venv` on that machine; it was probably copied from another one. On Linux you may also need the system XCB/EGL libraries (`libxcb-cursor0` etc.).
- **VS Code doesn't find the tests.** Check the selected interpreter is the project `.venv`, then run **Python: Configure Tests ▸ pytest ▸ tests**. Look in the Output panel under **Python Test Log**.
