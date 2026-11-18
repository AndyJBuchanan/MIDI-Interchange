# How we work on this project

Read this at the start of every session. These rules were set by the project owner; follow them without being reminded. Where a rule has a longer home, it's linked.

## The process, in order

1. **Pick** the task. The owner chooses it. "Pick up", "let's do" or "time for" a feature means this step only: ask which task, then stop.
   - [docs/ROADMAP.md](docs/ROADMAP.md) is the **only** source of features. Only items under **Agreed, not started** can be picked and planned.
   - Items under **Suggested, not agreed** first need discussion and the owner's agreement. A version tag on them (for example "idea for 0.5.0") is not agreement. When offering tasks, say which section each sits in.
2. **Discuss and plan.** Agree the behaviour with the owner, then write the plan in `docs/plans/<feature>.md` for review. **Make no code edits until the owner has agreed the plan and says to implement.** If edits were made by mistake, discard them when told.
3. **Implement and test**, on a feature branch (see below).
4. **Manual test** by the owner, usually. Manual checks go in [docs/TEST_CHECKLIST.md](docs/TEST_CHECKLIST.md) as a new numbered section before section 9, headed with the feature's branch. The owner ticks the boxes.
5. **Commit.**
6. **Push**, only when asked, then open the PR.

When a feature is finished, remove it from the roadmap and set the plan's status to built. Record what the owner observes of a DAW in the plan.

## Branches

Full rules: [docs/RELEASING.md, Branches](docs/RELEASING.md#branches). In short:

- A feature branch (`feature/<name>`) starts from the **current release branch** (`release/X.Y.Z`), never from `main`. Pull the release branch first.
- Features merge by **pull request into the release branch**, with a merge commit. Never straight into `main`, never into a release branch by a plain merge.
- Docs (README, roadmap, test checklist, interop notes) go on the release branch. A feature's plan goes on its feature branch.
- **Before pushing a feature branch or opening a PR**, run `git log origin/<release>..<release>`. If the release branch holds unpushed commits, tell the owner and push the release branch first (when asked), so the PR shows only the feature's own commits. Check the PR on GitHub afterwards: its base, its commit list, and that its description mentions only what the PR contains.
- Don't delete release branches (the repository rules forbid it). Don't delete other branches unless asked.
- Don't rewrite history, delete a branch, or close a PR without the owner's say-so. A rewrite needs a backup branch first, and the owner is told what it changes.

## Git hygiene

- **Stage files by name. Never `git add -A` or `git add .`.** The working tree can hold untracked files from manual testing (temp exports dragged out of the app), and they must not be committed. Run `git status` before every commit and check the staged list.
- Commit locally as work goes. **Push only when the owner asks**, and never push a document the owner is still reviewing (release notes, README, plans).
- Set the commit identity and `gh` login as in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md#configure-each-clone-identity-and-github-login).
- Commit messages end with the attribution line the session gives; PR bodies likewise.

## Tests

- Run the suite with `.venv/bin/python -m pytest -q`. The GUI tests run headless; `tests/conftest.py` sets the offscreen platform.
- **Reuse the existing fixtures.** For anything needing the main window, use `from test_ui_assembly import app, win`. Never build a `MainWindow()` by hand in a test: hand-built windows made the whole suite segfault intermittently in an unrelated drag test (2026-11-18).
- Before writing tests, read a neighbouring test file and follow its pattern.
- After adding UI tests, run the **full suite more than once** (four times for a new feature): Qt crashes can be intermittent.
- Add a regression test for any change to import or export behaviour. Other code conventions are in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## DAWs

- The owner uses **Reason and Cubase**. Logic is secondary; the others are low priority. Don't start work on other DAWs unprompted.
- **What the owner says about their DAW's behaviour stands.** Manuals, web results and fixture patterns only add to it. When they conflict, or a rule holds only in our fixtures, say so and ask. Don't "correct" the owner from documentation.
- Readers only ever read project files; they never modify them.

## Reporting

- Say what was actually done and verified. Report failures with their output, and say when something was skipped or couldn't be confirmed.
- Don't claim a state you haven't checked (a PR's contents, a branch's position, a test result). Check it, then state it.
- When unsure which of two readings the owner means, ask one short question. Don't act on the one you prefer.
