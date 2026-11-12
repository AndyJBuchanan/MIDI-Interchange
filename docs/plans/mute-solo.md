# Plan: mute and solo

Status: **built and studio-tested, including feedback changes** (2026-11-12). Branch: `feature/mute-solo` from `main`.

This came from the clip-trims studio test (2026-11-12): replace the include tickbox and the Solo for Export menu with standard mute and solo.

**Behaviour:** standard music-app mute and solo. The only difference is that the result decides what is exported, not what is heard.

- **Buttons:** each track header gets an **M** and an **S** button in place of the include tickbox.
- **Which tracks export globally:** if any tracks are soloed, those tracks export. Otherwise, all unmuted tracks export. Several tracks can be soloed at once. Range exports use the range's stored include/exclude result as described below.
- **Click modifiers:**
  - A click toggles the button.
  - ⌥/Alt-click on S solos only that track (exclusive solo). ⌥-click on S of a track that is already the only solo unsolos it.
  - ⌥/Alt-click on M sets every track's mute to the clicked track's new state, as Cubase does. Muting a soloed track cancels its solo (see below), so muting all also clears every solo.
- **Mute and solo transitions:**
  - Soloing a muted track overrides its mute. That track's M button is shown greyed out while its own solo is active; the track exports normally. Other muted tracks keep their normal lit M while a solo is on (no "implied mute" display), which we understand to be Cubase's behaviour; confirm in the studio.
  - Cancelling solo restores that track's previous muted/unmuted state.
  - Muting a soloed track cancels its solo and sets mute. Subsequently unmuting it does not restore solo.
  - Exclusive solo and clearing solos must also restore the previous mute states of tracks whose solo ends.
  - The clear-mutes button clears hidden mutes (remembered under a solo) as well as visible ones, so unsoloing such a track afterwards leaves it unmuted.
- **Cancel-all buttons:** compact boxed **M** and **S** buttons sit in the top-left panel, rather than text buttons. They clear all mutes or all solos respectively, and light up while the corresponding state is present. The top M indicator counts only explicit mutes not overridden by that track's solo; hidden mutes do not light it, but Clear mutes still clears them. Tooltips explain their actions.
- **Old controls removed:** the Solo for Export / Unsolo (Restore Track Selection) menu items and the stored state behind them (`controller.solo`) go.
- **Undo:** each mute or solo action is one undo step, including its effects on other tracks and following ranges. Locking/unlocking a range or changing a range checkbox is also one undo step.
- **Colours:** mute is yellow/orange; solo is red, for track and global buttons. When no solo is active, unmuted tracks (neither muted nor soloed) are drawn normally and muted tracks are dimmed. While any solo is active, soloed tracks are drawn normally and the other tracks are dimmed. Solo overrides the lane dimming of a previously muted track while that solo is active.

**Ranges: follow global M/S until locked.**

- Each range still stores a collapsed include/exclude result (`Range.excluded`), rather than separate per-range mute and solo states.
- A new range starts unlocked. Its included tracks are set from the effective global M/S result when it is created.
- Track M/S changes and global clear-M/clear-S actions update every unlocked range to match the effective global result. This includes changes to other tracks' eligibility caused by entering or leaving solo.
- An unlocked range's track checkboxes are greyed out and cannot be edited, but continue to show its current export inclusion state. Clicking a greyed-out checkbox does nothing for now (agreed 2026-11-12; recorded in DESIGN_NOTES as a possible later change: click to lock and apply).
- Each range gets a padlock in the range header, inline with its track checkboxes. The padlock shows the range's track lock state.
- Clicking the padlock to **lock** the range preserves its current track inclusion, enables its checkboxes for independent editing, and prevents subsequent track/global M/S changes from altering that range.
- Clicking again to **unlock** immediately replaces its track inclusion with the current global M/S result, greys out the checkboxes and resumes following global changes. Previous manual checkbox choices are discarded.
- Range export uses the range's stored inclusion directly. A locked range may therefore export a track that the global M/S result excludes; do not apply another global M/S filter at export time.
- **Range context menu:** "Reset to track toggles" becomes **Unlock** (same as clicking the padlock to unlock). **Include all** and **Exclude all** lock the range first if it isn't already locked, then apply, as one undo step. Individual track entries and their heading are removed; use the range checkboxes for individual choices.
- **New tracks:** imports and tracks created by clip moves/copies always start unmuted and effectively included. They join an existing solo group when needed to remain included; otherwise solo starts off. One shared track-addition path handles this, using the central solo-state rule. New tracks are included in locked ranges, and unlocked ranges copy the resulting global selection.
- **Lane dimming:** a range always draws each track dimmed or undimmed to match what that range will actually export. Outside ranges, lanes follow the global M/S result. So a globally muted track shows normally inside a locked range that includes it, as an off track does today.

**Code:**
- **Model:** replace `Track.enabled` with mute/solo state and retain the mute state needed when solo ends. Put the global eligibility rule in one place in `core` (replacing `enabled_tracks`). Whole exports use that rule; range creation and updates copy its result into unlocked ranges. Range exports continue to use each range's stored inclusion.
- **Range model:** add a track-lock state to each range. Copies and undo/redo snapshots preserve it alongside the range's inclusion list.
- **UI:** `track_panel.py` gets the track buttons and compact global M/S buttons in its top-left area. The range header gets the padlock inline with its track checkboxes, with disabled/enabled checkbox states and updated header drawing.
- **Other places that read `enabled`:**
  - drag-out, `new_track_for_clip` and seeding new ranges;
  - the old ⌥ "every range" toggle is replaced by following unlocked ranges automatically. ⌥-click on M now operates on all track mutes and must respect range locks.
  - `set_range_tracks` (the context-menu Include all / Exclude all / Reset) and the timeline's range lane painting (`_paint_track_regions`).

**Tests:**
- Whole exports: mute, solo, several solos, solo overriding mute, restoring mute on unsolo, and muting a soloed track cancelling solo without later reactivation on unmute.
- Exclusive solo, ⌥-click S on the only solo unsoloing it, ⌥-click M setting all mutes to the clicked track's new state and clearing solos, both global clears (clear-mutes also clearing hidden mutes), undo/redo of complete actions, and the old menu items being gone.
- Context menu: Unlock replaces Reset; Include all / Exclude all lock an unlocked range. A new track is included in locked ranges. Clicking a greyed checkbox on an unlocked range changes nothing.
- New ranges copy the global result. Every track/global M/S action updates unlocked ranges, including the effect on non-soloed tracks.
- Locking preserves the inclusion list and enables editing; global changes leave locked ranges alone. Unlocking immediately copies the current global result and disables independent editing.
- Locked range exports honour their own inclusion even for globally excluded tracks, in Preserve, Rebase and Separate modes and through both Save MIDI and drag-out.
- Padlock/header rendering, checkbox editability, context-menu consistency and undo/redo of locking, unlocking and manual edits.

**Checklist:** mute and solo tracks, including soloing a muted track, unsoloing it, and muting then unmuting a soloed track. Check the global boxed M/S buttons and exclusive solo. Create two ranges; lock one and edit its track checkboxes. Change track/global M/S: only the unlocked range follows. Unlock the other: its ticks immediately match global M/S. Drag out and save whole and by range into Cubase and Reason, check which tracks arrive, and undo/redo each action.

## Rules for the build session

- Build only this plan, and only when the user says so.
- If the code doesn't fit the plan, stop and ask rather than designing around it.
- Work on the feature branch named above. Don't switch branches, and don't push.

Implementation verification: 229 automated tests passed. The track controls and range padlocks were also rendered and inspected headlessly. The user passed the studio checklist, including the feedback retests in TEST_CHECKLIST section 8h.

Feedback follow-up verification: 238 automated tests passed. Imported and clip-created tracks share `_add_track` and the central `has_solos` rule. Workflow tests use named fixtures so manual-test MIDI exports in `samples/` do not affect expected track counts. Version: 0.2.2. Studio feedback retest: TEST_CHECKLIST section 8h, passed locally by the user (2026-11-12).
