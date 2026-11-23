# How we work on this project

Read this at the start of every session. The project owner set these rules. Follow them without being reminded. Where a rule has a longer home, it's linked.

**This file is the only place these rules are kept.** A session can start in a worktree, on another machine or in the cloud, where no local notes or memory exist. If the owner sets or changes a working rule, record it here, on the release branch, when the owner asks.

## The process, in order

1. **Pick** the task. The owner chooses it. "Pick up", "let's do" or "time for" a feature means this step only: ask which task, then stop.
   - [docs/ROADMAP.md](docs/ROADMAP.md) is the **only** source of features. Only items under **Agreed, not started** can be picked and planned.
   - Items under **Suggested, not agreed** first need discussion and the owner's agreement. A version tag on them (for example "idea for 0.5.0") is not agreement. When offering tasks, say which section each sits in.
2. **Discuss and plan.**
   - Agree the behaviour with the owner, then write the plan for review in `docs/plans/<feature>.md`, on the **release branch**.
   - "Plan this" means a written plan only. Read code only as far as the plan needs, and make **no code edits** until the owner has agreed the plan and says to implement. If edits were made by mistake, discard them when told.
   - Planning is done with the most capable model. Find the design questions and put them to the owner before any code is written: problems found while coding are expensive.
3. **Implement and test**, on a feature branch (see below), only when the owner says to build.
   - Building is normally done in a **separate session on a cheaper model** (Sonnet), from the agreed plan. A planning session offers to hand over with a complete brief. It doesn't start building itself.
   - A build session builds the plan. It doesn't fix or change anything beyond it without discussion or a direct instruction.
4. **Manual test** by the owner, usually. Manual checks go in [docs/TEST_CHECKLIST.md](docs/TEST_CHECKLIST.md) as a new numbered section before section 9, headed with the feature's branch. The owner ticks the boxes.
5. **Commit**, only when the owner says to.
6. **Push**, only when the owner asks, then open the PR. "Commit" alone doesn't mean push.

When a feature is finished, remove it from the roadmap and set the plan's status to built (on the feature branch, so they merge with the code). Record what the owner observes of a DAW in the plan.

## Instructions and test feedback

- **Do only what the owner asked.** Don't fix, write or commit code unless told directly, or unless it has been discussed and agreed.
- **Test results are not instructions.** "Checklist uploaded" or "notes are in the file" means: read the notes, summarise what you see, and wait. Don't start fixing.
- **The owner's test reports stand.** Take what they say they did as exactly what they did. Don't offer theories that they dropped on the wrong track or clicked the wrong thing. If you can't reproduce a problem, say so plainly. Then make the app report its own reasoning (status bar, preview diagnostics), so the next studio run shows the cause.
- **Never ask the owner to find old test files** (exports or temp files from earlier sessions). They're transient and usually gone. Build equivalent test data from what's known (`samples/`, screenshots, their notes) and say it's a stand-in. At most, ask them to *keep* files from a *future* run, in the checklist itself.
- When unsure which of two readings the owner means, ask one short question. Don't act on the one you prefer.

## Where testing happens

- **The owner's hand testing happens on the studio Macs**, with the DAWs. Never search this development Mac for their test files, temp exports or logs. Ask them to copy files across, and remember their copy may lag this checkout.
- The canonical working copy is on the owner's development Mac. Copies on the studio Macs and the Windows PC are for testing and building only. Fixes come back to the canonical copy.
- **Windows is tested only at release time** ([RELEASING.md](docs/RELEASING.md), step 3). Don't ask for Windows testing between releases, and don't treat unticked Windows checklist items as gaps.
- **A Windows test run between releases is not a build.** A fix it needs is committed and pushed like any other fix, with no questions about build commits. The named-commit rule under Releases applies only once a release build commit has been named.
- Release downloads are built into `dist/`.

## Branches

Full rules: [docs/RELEASING.md, Branches](docs/RELEASING.md#branches). In short:

- A feature branch, `feature/<name>`, starts from the **current release branch** (`release/X.Y.Z`), never from `main`. Pull the release branch first. A large feature can be split into parts, each on its own branch, `feature/<name>-<part>`. A small fix uses `fix/<name>`, with the same rules.
- Features merge by **pull request into the release branch**, with a merge commit. Never straight into `main`, and never into a release branch by a plain merge.
- **Where docs go depends on when.** Before the feature branch exists, the roadmap entry and the plan go on the release branch: they're written and agreed there, and the feature branch is made from it. Once the feature branch exists, **that feature's docs go on the feature branch** with the code and merge into the release branch with it: README lines, its test checklist section, DEVELOPMENT.md notes, interop findings, and finally the roadmap removal and the plan's "built" status. The feature's merge carries all of them into the release branch. Docs changed after the feature has merged go on the release branch. Ask the owner when a change affects other features.
- **Before pushing a feature branch or opening a PR**, run `git log origin/<release>..<release>`. If the release branch holds unpushed commits, tell the owner. Push the release branch first, when asked, so the PR shows only the feature's own commits. Then check the PR on GitHub: its base, its commit list, and that its description mentions only what the PR contains.
- **Don't switch branches without asking**, even for a small docs fix. Ask which branch the change belongs on. Never switch branches, reset or commit in a folder another session is using: that session's next commit lands on the wrong branch. If a change needs another branch, suggest a separate worktree.
  - **Expected switches**, which need no asking: after a feature is merged, switch to the release branch it merged into and pull. After a release branch is merged into `main`, switch to `main` and pull.
- Don't delete release branches (the repository rules forbid it). Don't delete other branches unless asked.
- Don't rewrite history, delete a branch, or close a PR without the owner's say-so. A rewrite needs a backup branch first, and the owner is told what it changes.

## Git and GitHub

- **Stage files by name. Never use `git add -A` or `git add .`.** The working tree can hold untracked files from manual testing, such as temp exports dragged out of the app, and they must not be committed. Run `git status` before every commit and check the staged list.
- Files named `*delete-me*` are the owner's transient notes. They're never committed (they're git-ignored).
- Never push a document the owner is still reviewing (release notes, README, plans).
- **Use only the owner's personal GitHub account.** The repository is `AndyJBuchanan/MIDI-Interchange`. Before any GitHub action (push, PR, release), check that `gh api user --jq .login` prints `AndyJBuchanan`.
  - The development Mac also has work git and GitHub logins. Never use them for this repository.
  - The clone's identity and login are set in its local git config, as in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md#configure-each-clone-identity-and-github-login).
- **Never guess or look up credentials:** which Apple ID or developer account to sign with, or any work login. Ask the owner when it comes up. Secrets stay out of the repository (`scripts/signing.local.env` is git-ignored).
- Commit messages end with the attribution line the session gives. PR bodies likewise.

## Releases

Full checklist: [docs/RELEASING.md](docs/RELEASING.md).

- **Both platforms build one named commit.** Once that commit is named, commit nothing to the release branch until both builds are done and the release is published. Moving the branch after naming a build commit broke a Windows build.
- Checksums go in the release notes on disk. They're committed only after publishing.

## Tests

- Run the suite with `.venv/bin/python -m pytest -q`. The GUI tests run headless; `tests/conftest.py` sets the offscreen platform.
- **Reuse the existing fixtures.** For anything needing the main window, use `from test_ui_assembly import app, win`. Never build a `MainWindow()` by hand in a test. Hand-built windows made the whole suite segfault intermittently, in an unrelated drag test (2026-11-18).
- Before writing tests, read a neighbouring test file and follow its pattern.
- After adding UI tests, run the **full suite more than once**, four times for a new feature. Qt crashes can be intermittent.
- Add a regression test for any change to import or export behaviour. Other code conventions are in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md#project-layout-and-conventions).

## DAWs

- The owner uses **Reason and Cubase**. Logic is secondary; the others are low priority. Don't start work on other DAWs unprompted.
- **What the owner says about their DAW's behaviour stands.** Manuals, web results and fixture patterns only add to it. When they conflict, or a rule holds only in our fixtures, say so and ask. Don't "correct" the owner from documentation.
- **Direct project import means reading the DAW's own saved project** (`.cpr`, `.reason`, `.logicx` and so on). Not having to export is the whole point. So an export route, such as Cubase's DAWproject or MIDI export, is never the answer for a DAW. Exports from the same project are test references for checking a reader. DAWproject is also a format in its own right, for files people receive.
- Readers only ever read project files. They never modify them.
- Don't claim compatibility with an app until that drag or import has actually been tested.

## Describing the app

In release notes, the README, the About box, tooltips and summaries:

- The app is a **MIDI palette**: a place to hold and work on pieces of MIDI, so that moving MIDI between several apps is easier and more flexible. Frame features by what they do for that transfer.
- **It is not a DAW or an arranger.** Avoid "build a piece", "arrange" and "compose".
- Describe it in full, not by drag alone. The agreed one-liner: "A MIDI palette for moving MIDI between apps: drag in or import MIDI from one or more apps, pick the tracks and ranges you want, and drag them out or export to another."

## Reporting

- Say what was actually done and verified. Report failures with their output. Say when something was skipped or couldn't be confirmed.
- Don't claim a state you haven't checked, such as a PR's contents, a branch's position or a test result. Check it, then state it.
