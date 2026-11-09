# Development Guide

How to set up, run, test and build MIDI Interchange on a new machine, from the terminal or from Visual Studio Code.

For what the app is and why it's built this way, see [DESIGN_BRIEF.md](DESIGN_BRIEF.md) (the original spec) and [DESIGN_NOTES.md](DESIGN_NOTES.md) (decisions, status and gaps).

## Prerequisites

| Tool | macOS | Windows |
|---|---|---|
| Git | `xcode-select --install` or Homebrew `brew install git` | [git-scm.com](https://git-scm.com/download/win) |
| Python **3.12 or newer**, 64-bit | `brew install python@3.12` or the python.org installer | python.org installer. Tick "Add python.exe to PATH" and keep the `py` launcher. Or `winget install Python.Python.3.12 --scope user`. **The Microsoft Store Python isn't enough**: it doesn't install the `py` launcher, which the build script and VS Code tasks call. Open a new terminal after installing so `py` is on `PATH`. |
| Xcode Command Line Tools (macOS release builds) | `xcode-select --install`. Provides `codesign`, `xcrun notarytool` and `stapler`. A Developer ID Application certificate is also needed; see [signing](#macos-signing-and-notarisation) | n/a |
| VS Code (optional) | [code.visualstudio.com](https://code.visualstudio.com) | same |

Nothing else needs a system-wide install. PySide6 (Qt), mido, pytest and PyInstaller all go into a project-local virtual environment from `requirements*.txt`. There are no C/C++ build tools to install.

Development so far has been on macOS (Apple silicon) with Python 3.12 and PySide6 6.12. On 2026-11-09 the app was set up, tested and built on Windows 11 x64 with Python 3.12.10, PySide6 6.12 and PyInstaller 6.22; see [Windows build](#windows-build). Linux will probably work for development, but nobody has tried it.

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

If you copy a whole working tree (for example macOS → Windows) instead of cloning, check these too:

- Delete the copied `.venv/`. A macOS venv has `bin/` instead of `Scripts\` and points at a Homebrew Python, so nothing in it runs on Windows. Recreate it as shown below.
- `build/` and `dist/` hold the other platform's PyInstaller output. They're git-ignored and harmless. The Windows build cleans `build/` and replaces `dist\MIDI Interchange\`, but leaves the macOS `.app` and DMG alone.
- Windows doesn't keep the executable bit, so Git reports `old mode 100755 / new mode 100644` on `scripts/build_macos.sh`. Run `git config core.filemode false` in that working copy (local config only), and don't commit the mode change.
- `.gitattributes` keeps `*.sh` at LF and `*.ps1` at CRLF in every checkout, so a tree copied from Windows to a Mac still runs under bash.

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
| Build a standalone macOS app | `scripts/build_macos.sh` → `dist/MIDI Interchange.app` and `dist/MIDI-Interchange-<version>-macOS-<arch>.dmg`. Signed and notarised if `scripts/signing.local.env` exists (a few minutes, waits for Apple) |
| macOS build, signed but not notarised | `SKIP_NOTARIZE=1 scripts/build_macos.sh` |
| Build a standalone Windows app | `powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1` → `dist\MIDI Interchange\MIDI Interchange.exe` and `dist\MIDI-Interchange-<version>-Windows-x64.zip`, plus `...-Windows-x64-Setup.exe` if Inno Setup 6 is installed. Not code-signed |

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
3. **Python: Select Interpreter** and choose `./.venv/bin/python` (macOS) or `.\.venv\Scripts\python.exe` (Windows). The workspace setting points at the macOS/Linux path; Windows needs this one-time choice. Until you make it, the Python extension may say the default interpreter path is invalid; you can ignore that.
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
| Build standalone app | default **build** task, ⇧⌘B / Ctrl+Shift+B. On macOS this is a full release build, including notarisation if signing is set up |

## Building standalone apps

`scripts/build_macos.sh` and `scripts/build_windows.ps1` create a separate `.venv-build/`, install the requirements, and run PyInstaller with `midi_interchange.spec`. The spec's exclude list keeps out unused Qt modules such as WebEngine and Multimedia. Some Qt plugins still pull in QML/Quick, VirtualKeyboard and Pdf, which is why the app is about 100 MB. On macOS it also produces a `.app` bundle that registers `.mid`, `.midi` and `.smf` document types. The macOS script then packages that bundle into a compressed DMG with an Applications shortcut (drag to install) and prints the DMG's SHA-256. The version comes from the `VERSION = "x.y.z"` line at the top of `midi_interchange.spec`. It feeds the macOS `CFBundleShortVersionString`/`CFBundleVersion`, the Windows exe version resource and the Windows zip name. Set `PYTHON=python3.13` (macOS) or `$env:PY_VERSION="3.13"` (Windows) to build with a different interpreter. On macOS the script also signs and notarises; see [macOS signing and notarisation](#macos-signing-and-notarisation).

- Build on the platform you're targeting. PyInstaller doesn't cross-compile, so build the Windows exe on Windows and the macOS app on a Mac.
- A macOS build runs on the CPU architecture it was built on (arm64 on Apple silicon).
- A Windows build is x64 unless it's built on an ARM64 Python.

### Windows build

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
```

This takes about 1.5 minutes. It produces:

- `dist\MIDI Interchange\MIDI Interchange.exe` and its `_internal\` folder: a PyInstaller one-folder app (about 125 MB). It's a GUI exe with no console window. The VC++ runtime DLLs are bundled, so users don't need to install a redistributable.
- `dist\MIDI-Interchange-<version>-Windows-x64.zip` (about 50 MB). It contains the `MIDI Interchange\` folder. This is the portable option: users extract it anywhere and run the exe. The script prints the zip's SHA-256.
- `dist\MIDI-Interchange-<version>-Windows-x64-Setup.exe` (about 35 MB): **the one to give users.** It's built from `scripts\installer.iss` with [Inno Setup 6](https://jrsoftware.org/isinfo.php), and only if Inno Setup is installed. Otherwise the script warns and stops after the zip. Install Inno Setup once per build machine with `winget install JRSoftware.InnoSetup --scope user`. The script finds `ISCC.exe` in the standard install folders or on `PATH`, or you can set `$env:ISCC` to its path. To skip the installer, set `$env:SKIP_INSTALLER="1"`.

What the installer does:

- **Install location:** by default it installs for the current user only, with no UAC prompt, into `%LOCALAPPDATA%\Programs\MIDI Interchange`. The wizard also offers *Install for all users*, which goes into `C:\Program Files\MIDI Interchange` and needs admin rights.
- **Shortcuts and uninstaller:** it adds a Start-menu shortcut, an optional desktop shortcut, and an entry in *Settings ▸ Apps*. Uninstalling removes all of these, along with the files and registry keys.
- **"Open with" for MIDI files:** it adds the app to *Open with* for `.mid`, `.midi` and `.smf` (ProgID `MIDIInterchange.mid`, under `HKCU` or `HKLM`). It deliberately doesn't claim to be the default handler; since Windows 10, users choose that themselves.
- **Upgrades:** an upgrade installs over the old version and deletes the old `_internal\` first, so no stale DLLs are left behind. Windows recognises upgrades by the `AppId` GUID in `installer.iss`. **Never change it.** The version comes from `VERSION` in the spec.
- **Silent installs** (for testing or deployment): `Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /CURRENTUSER`, optionally with `/DIR="..."`. Uninstall silently with `unins000.exe /VERYSILENT` in the install folder.

How the script works:

- It requires the `py` launcher and fails early with an install hint if `py` is missing.
- It checks `$LASTEXITCODE` after every native command. Windows PowerShell 5.1 doesn't stop on a failing exe even with `$ErrorActionPreference = "Stop"`.
- The file is ASCII-only, because PowerShell 5.1 reads a BOM-less script as ANSI. Keep it that way.
- If you redirect the script's output to a file with `*>` or `2>&1`, PyInstaller's INFO log (written to stderr) shows up as `NativeCommandError` records. That's cosmetic; the exit code is what counts.

Not done yet on Windows:

- **No code signing.** Windows SmartScreen shows "Windows protected your PC" for a downloaded zip; users click **More info ▸ Run anyway**, or unblock the zip first (file Properties ▸ Unblock). Signing needs an Authenticode certificate (OV/EV, or Azure Trusted Signing) and `signtool sign /fd sha256 /tr <timestamp-url> /td sha256` on the exe before zipping.
- **Opening several files from Explorer opens several windows.** Selecting more than one file and using *Open with* starts one app instance per file, because there's no single-instance handoff yet. Command-line paths do load into one window (`"MIDI Interchange.exe" a.mid b.mid`), and so does dropping files onto the window.
- **The installer isn't signed either.** It needs the same certificate as the exe (sign the exe before running Inno Setup, then sign the Setup exe; Inno's `SignTool` directive can automate both).
- **No app icon** (same as macOS).
- Drag-in/drag-out against Windows DAWs hasn't been tested (see the README checklist).

**Windows build status (2026-11-09):** Windows 11 Pro x64, Python 3.12.10 (python.org, per-user), PySide6 6.12.0, PyInstaller 6.22.3. All 55 tests pass. The zip was extracted to a clean folder, and the exe started both empty and with the four `samples/` files on the command line. It rendered correctly at high DPI. PyInstaller's warnings file listed nothing relevant. The installer (Inno Setup 6.7.3) was tested with a silent per-user install. It created the files, the Start-menu shortcut, the *Open with* registry entries and the *Apps* entry. The app started through the registered open command with a sample file. A silent uninstall then removed the folder, shortcut and every registry key. The interactive wizard and the all-users install haven't been tested yet.

### macOS signing and notarisation

Release builds are signed with a **Developer ID Application** certificate, use the hardened runtime with a secure timestamp, and are notarised by Apple and stapled. Then Gatekeeper opens them on any Mac without warnings. The settings for each machine live in **`scripts/signing.local.env`**, which is git-ignored and never committed. `scripts/signing.env.example` is the checked-in template.

One-time setup on each build machine:

1. Install the Developer ID Application certificate and its private key in the login keychain, then confirm it appears:
   ```bash
   security find-identity -v -p codesigning
   ```
2. Create the local config from the template, and set `CODESIGN_IDENTITY` to the certificate's SHA-1 (or its full name) and `NOTARY_KEYCHAIN_PROFILE` to a profile name:
   ```bash
   cp scripts/signing.env.example scripts/signing.local.env
   ```
3. Create an **app-specific password**. Notarisation won't accept your normal account password.
   - Sign in at https://account.apple.com with the Apple Account that belongs to the Developer team. It may not be the account signed in to this Mac's iCloud. For example, a work Mac can use a personal developer account.
   - Go to **Sign-In and Security ▸ App-Specific Passwords**, click **+**, and enter any label (for example `notarytool`). The label only identifies the password on that page, for when you want to revoke it. Nothing in the build uses it.
   - Copy the generated password (`xxxx-xxxx-xxxx-xxxx`). Apple shows it only once.
4. Store the notary credentials in the keychain under the profile name from step 2. Run this in Terminal; it's interactive, so don't script it:
   ```bash
   xcrun notarytool store-credentials "MIDI-Interchange-Notary" --apple-id "<developer account sign-in email>" --team-id "<TEAMID>"
   ```
   - `--apple-id` is the **email address you sign in with** at developer.apple.com / account.apple.com for the Developer team.
   - `--team-id` is the 10-character Team ID, shown under Membership details at developer.apple.com/account. It's also the `(XXXXXXXXXX)` suffix on the certificate name.
   - At the `App-specific password for …:` prompt, paste the password from step 3. The tool validates it with Apple, then prints `Credentials validated` and `Credentials saved to Keychain`.
   - The profile name (`MIDI-Interchange-Notary`) must match `NOTARY_KEYCHAIN_PROFILE` in `scripts/signing.local.env`. That name is the only thing the build refers to. The Apple ID and password stay in the keychain, never in the repo.
5. Check the profile works. An empty list or past submissions means it's set up correctly; "No Keychain password item found" means step 4 didn't save:
   ```bash
   xcrun notarytool history --keychain-profile "MIDI-Interchange-Notary"
   ```

An App Store Connect API key works instead of an Apple ID and password, and suits CI or a shared machine. Create a Team key with the Developer role under App Store Connect ▸ Users and Access ▸ Integrations, then store it:
```bash
xcrun notarytool store-credentials "MIDI-Interchange-Notary" --key AuthKey_XXXXXXXXXX.p8 --key-id XXXXXXXXXX --issuer <issuer-uuid>
```

To change accounts, run `store-credentials` again with the same profile name, which overwrites the profile. To remove it, delete the `com.apple.gke.notary.tool` item in Keychain Access.

Then run `scripts/build_macos.sh`. It does the following:

1. PyInstaller signs every nested binary, framework and the bundle with `--options=runtime --timestamp`. The identity is passed through the `CODESIGN_IDENTITY` environment variable, read by `midi_interchange.spec`. Entitlements come from `scripts/entitlements.plist`, which is deliberately empty because the app needs no hardened-runtime exceptions.
2. The script checks the app with `codesign --verify --deep --strict`. It fails unless the signature has the Developer ID authority, the runtime flag and a timestamp.
3. It builds the DMG: a blank HFS+ image, `ditto` the app in, convert to compressed UDZO. This avoids the `hdiutil -srcfolder` "Resource busy" failures seen on macOS 26.
4. It signs the DMG, submits it with `notarytool submit --wait`, and on rejection prints the notary log and fails.
5. It staples the ticket to the DMG and to `dist/MIDI Interchange.app`, then confirms both with `stapler validate` and `spctl --assess`.

Options:

- `SKIP_NOTARIZE=1 scripts/build_macos.sh` signs without submitting, for a quick local check. Gatekeeper reports such a build as `Unnotarized Developer ID`.
- Without a `signing.local.env` (or `CODESIGN_IDENTITY`), the build falls back to ad-hoc signing and prints a warning.

Notes:

- The first signing run triggers a keychain prompt to allow `codesign` to use the private key. Choose **Always Allow**. While the prompt is open, the build waits, and if it waits too long the timestamp request fails with "timestamps differ by N seconds". Rerun after allowing access.
- Only the DMG is submitted. Its notarisation ticket also covers the app inside, which is why the script can staple the app in `dist/`. The copy *inside* the DMG isn't stapled, so if a user drags it out while offline, Gatekeeper checks it online the first time it opens.
- Before shipping a new release, bump `VERSION` at the top of `midi_interchange.spec`. It sets `CFBundleShortVersionString`, `CFBundleVersion` and the Windows version.

**macOS build status (2026-11-09):**
- Built on Apple silicon with Python 3.12 and PyInstaller 6.x. The DMG is about 39 MB and the app about 100 MB.
- The app is Developer ID signed (team 729JFYTH57), with the hardened runtime and timestamp, and needs no extra entitlements.
- The first notarisation submission was **Accepted** with no issues (207 binaries ticketed). The ticket is stapled to both the DMG and `dist/` app, and `spctl` reports **Notarized Developer ID** for each.
- A copy of the DMG marked with the quarantine flag, as if downloaded, opens and the app inside passes Gatekeeper and launches.
- There's no app icon yet.

## Project layout and conventions

```
main.py                        entry point; macOS FileOpen handling; CLI paths
midi_interchange/core/         pure Python model, timing, SMF import/export (no Qt imports)
midi_interchange/interchange/  drag-in payload extraction, drag-out temp files
midi_interchange/ui/           PySide6 controller, timeline, track panel, export panel, theme
tests/                         pytest suite (helpers.py builds synthetic SMFs)
tools/make_demo_midi.py        regenerates samples/
scripts/                       build scripts; installer.iss (Windows installer); entitlements.plist; signing.env.example (copy to git-ignored signing.local.env)
midi_interchange.spec          PyInstaller spec (bundle metadata, version, signing identity from env)
.vscode/                       VS Code extensions, launch configs, tasks, settings
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
- **`py` is not recognised, or `py -0` lists only "Python 3.13 (Store)".** The Microsoft Store Python has no `py` launcher. Install python.org 3.12 (`winget install Python.Python.3.12 --scope user`), then open a **new** terminal. Terminals and VS Code windows that were already open keep the old `PATH`.
- **`test_separate_files` fails on Windows with a full `C:\...` path.** Tests must compare file names with `os.path.basename`, not `split("/")`. Use `os.path` or `pathlib` for any new path handling.
- **SmartScreen blocks the built exe.** It's unsigned; see [Windows build](#windows-build).
- **Git shows `scripts/build_macos.sh` as modified (mode 100755 → 100644).** Run `git config core.filemode false` in the Windows working copy.
- **Qt "could not load the platform plugin".** Recreate `.venv` on that machine; it was probably copied from another one. On Linux you may also need the system XCB/EGL libraries (`libxcb-cursor0` etc.).
- **`codesign` fails with "timestamps differ by N seconds".** The keychain prompt asking for access to the signing key was left open too long. Click **Always Allow**, then rerun.
- **"Signing identity … not found in the keychain".** The certificate or its private key isn't in this Mac's login keychain, or `CODESIGN_IDENTITY` in `scripts/signing.local.env` has a typo. Check with `security find-identity -v -p codesigning`.
- **"No Keychain password item found for profile".** The notary profile hasn't been created on this machine. See step 4 of the signing setup.
- **Notarisation status `Invalid`.** The script prints Apple's JSON log; the `issues` array names each file and problem (usually an unsigned binary or one without the hardened runtime). Run `xcrun notarytool history --keychain-profile MIDI-Interchange-Notary` to see past submissions.
- **`hdiutil: create failed - Resource busy`.** This happens with `hdiutil create -srcfolder` straight after a build. The script avoids it by copying into a blank image. If you package by hand, do the same.
- **VS Code doesn't find the tests.** Check the selected interpreter is the project `.venv`, then run **Python: Configure Tests ▸ pytest ▸ tests**. Look in the Output panel under **Python Test Log**.
