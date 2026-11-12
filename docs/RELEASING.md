# Releasing

How to set the version, build the end-user downloads on both platforms and publish a GitHub release. Machine setup (Python, the signing certificate, notarisation, Inno Setup, the `gh` login) is in [DEVELOPMENT.md](DEVELOPMENT.md).

Users download the app; they don't build it. You can build everything on your own machines. Signing with your own Apple Developer ID is optional (without it the Mac app is ad-hoc signed and Gatekeeper warns), and publishing a GitHub release needs write access to the repository you publish to (your fork, or the main repository if you maintain it). Each release ships three files:

| File | Platform | Built on | Notes |
|---|---|---|---|
| `MIDI-Interchange-<ver>-macOS-arm64.dmg` | macOS 15+ on Apple silicon (see below) | a Mac | Developer ID signed, notarised, stapled |
| `MIDI-Interchange-<ver>-Windows-x64-Setup.exe` | Windows 10/11 x64 | Windows | Installer. **Recommended** for Windows users |
| `MIDI-Interchange-<ver>-Windows-x64.zip` | Windows 10/11 x64 | Windows | Portable: extract it and run the exe |

**The minimum macOS version comes from the Python used to build.** A Homebrew Python 3.12 is built for the host macOS, and the bundled Python framework then requires that version. v0.1.0-pre was built on macOS 26 with Homebrew Python, which gave a minimum of **macOS 15**; the bundled Qt needs 14.4. Check after each build:

```bash
vtool -show-build "dist/MIDI Interchange.app/Contents/Frameworks/Python.framework/Versions/3.12/Python" | grep minos
```

To support older Macs, build with the python.org macOS installer, whose framework targets macOS 11 (pass `PYTHON=/usr/local/bin/python3.12`). Qt 6.12 still needs macOS 14.4. The minimum isn't yet written into `Info.plist` as `LSMinimumSystemVersion`, so an older Mac can open the app and see it fail to start rather than get a clear message.

## Version numbers

**There's one place to change: the `__version__ = "x.y.z"` line in [`midi_interchange/__init__.py`](../midi_interchange/__init__.py).** The About box shows it too.

Everything else comes from that line:

| Where the version appears | How it gets there |
|---|---|
| macOS `CFBundleShortVersionString` / `CFBundleVersion` (Finder ▸ Get Info) | the spec's `info_plist` (the spec imports `__version__`) |
| Windows exe *File version* / *Product version* (Properties ▸ Details) | the spec's `VSVersionInfo` resource |
| Windows installer version, and the version in *Settings ▸ Apps* | `build_windows.ps1` passes `/DAppVersion` to `installer.iss` |
| DMG, zip and Setup exe file names | `build_macos.sh` reads it back from `Info.plist`; `build_windows.ps1` reads the `__version__` line |

Rules:

- **Use `MAJOR.MINOR.PATCH` digits only**, for example `0.1.0` or `0.2.0`. macOS and Windows version fields don't accept suffixes. The package refuses to import with anything else (so the app and the spec both stop) and gives a clear error.
- **Pre-release labels go on the git tag and the GitHub release, not in `__version__`.** For example, `__version__ = "0.1.0"` is released as tag **`v0.1.0-pre`**, and the downloads keep the plain `0.1.0` in their names.
- **Tags are `v` + `__version__`, plus an optional `-label`:** `v0.1.0-pre`, `v0.2.0-beta.1`, `v1.0.0`. Mark any tag with a label as a GitHub *pre-release*.
- **Bump `__version__` for every build you ship.** The Windows installer upgrades in place by `AppId`, so the version is how users and Windows tell builds apart. Two different builds should never share a version.
- If you want two pre-releases of the same version (`v0.2.0-beta.1`, then `v0.2.0-beta.2`), the downloads would have the same file names. Bump `PATCH` instead, or attach the second set to its own release.
- Never change the `AppId` GUID in `scripts/installer.iss`; it isn't part of versioning.

## Release checklist

### 1. Prepare (any machine)

1. Pull the latest `main`, and make sure the tree is clean and the tests pass: `.venv/bin/python -m pytest -q`
2. Set `__version__` in `midi_interchange/__init__.py`, commit with a message like `Bump version to 0.2.0`, and push.
3. Write the release notes in `docs/releases/v<ver>[-label].md` (copy the previous one), then commit and push.
4. Note the commit hash (`git rev-parse --short HEAD`). Both platforms must build **this exact commit**.

### 2. Build on macOS

```bash
git pull && git status --short     # must be clean, at the release commit
```
```bash
scripts/build_macos.sh
```

This section assumes you've set up signing and notarisation ([DEVELOPMENT.md](DEVELOPMENT.md#macos-signing-and-notarisation)). Without it the script still builds, with ad-hoc signing and a warning; that's fine for your own machine but Gatekeeper warns other users, so skip the notarisation checks below. For a release you ship, the build is only usable if the output shows the notary JSON with `"status":"Accepted"`, the stapling and validation lines, and `source=Notarized Developer ID` for both the DMG and the app. Run without `SKIP_NOTARIZE`. Copy the printed SHA-256 into the release notes.

Quick check: mount the DMG, drag the app to a scratch folder and launch it. Finder ▸ Get Info should show the new version.

### 3. Build on Windows

Use a clone made from GitHub, not a copied working tree; see DEVELOPMENT.md, "Get the code".

```powershell
git pull; git status --short
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
```

The output must include the zip, the `Installer:` line and two SHA-256 lines. `exe version` must show the new version. Install from the Setup exe and launch it from the Start menu. Then check *Settings ▸ Apps* shows the new version, and that the zip's exe runs after you extract it.

Windows is only tested at release time, so do the hand tests now: section 11 of [TEST_CHECKLIST.md](TEST_CHECKLIST.md) (Alt for Option, Ctrl for ⌘), plus a quick drag in and out with the DAWs you use on Windows. Record results in the README interop table.

### 4. Collect the files on one machine

Copy the two Windows files into `dist/` on the Mac, or upload from Windows instead (step 5 works from either). If you copied them, check the hashes match the ones the Windows build printed:

```bash
shasum -a 256 dist/MIDI-Interchange-<ver>-*
```

### 5. Publish the GitHub release

Publishing uses the GitHub CLI (`gh`). Confirm it's signed in as the account that owns, or can write to, the repository you're publishing to. It must print your own username:

```bash
gh api user --jq .login
```

Create the tag on the release commit and push it. Or, for a draft you want to check before anyone sees the tag, skip this, pass `--draft --target <commit>` to `gh release create`, and let GitHub create the tag when you publish (a lightweight tag, as for v0.1.0-pre):

```bash
git tag -a v<ver>[-label] <commit> -m "MIDI Interchange <ver>[ label]"
```
```bash
git push origin v<ver>[-label]
```

Create the release. `<owner>` is the GitHub account or organisation that holds the repository (`AndyJBuchanan` for the main project, or your own username for a fork). Add `--prerelease` for any tag with a label, and use `--draft` if you want to check it on GitHub before publishing:

```bash
gh release create v<ver>[-label] -R <owner>/MIDI-Interchange --verify-tag --prerelease --title "MIDI Interchange <ver> (<label>)" --notes-file docs/releases/v<ver>[-label].md dist/MIDI-Interchange-<ver>-macOS-arm64.dmg dist/MIDI-Interchange-<ver>-Windows-x64-Setup.exe dist/MIDI-Interchange-<ver>-Windows-x64.zip
```

Check the release on GitHub: all three files are attached, and the notes and their SHA-256 lines are right. Download the DMG with a browser and open it; Gatekeeper must not warn.

To add or replace a file afterwards, for example when the Windows files come later:

```bash
gh release upload v<ver>[-label] -R <owner>/MIDI-Interchange --clobber <file>
```

## Release history

| Tag | Version | Commit | Notes |
|---|---|---|---|
| `v0.2.0-pre` | 0.2.0 | `7145b12` (published 2026-11-10) | Both platforms built from the tagged commit. The Windows tests were fixed on main first (PR #3, test helper only). |
| `v0.1.0-pre` | 0.1.0 | `9092edb` (published 2026-11-09) | First public pre-release. The Windows files were built from the Windows working copy before the commit authors were rewritten. Their code is identical to the tagged commit apart from the macOS-only "⌥-drag" hint text. |
