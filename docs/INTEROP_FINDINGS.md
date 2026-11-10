# Interoperability Findings

Hand-testing results and clipboard investigation after the v0.1.0-pre release. The summary table lives in the README checklist; this page keeps the detail and the open questions.

## Drag-and-drop on macOS (tested by hand, 2026-11-09)

What the words mean:

- **Drag into MIDI Interchange:** MIDI is dragged from the other app into MIDI Interchange and imported.
- **Drag from MIDI Interchange:** MIDI is dragged from MIDI Interchange into the other app and imported there.
- **Works:** tested successfully, not merely accepted as a drop.
- **Not yet confirmed:** that direction hasn't been verified.
- **Doesn't work:** the app doesn't appear to support that drag.

Not every combination of tracks, clips or selections has been tried.

| Application | Into MIDI Interchange | From MIDI Interchange | Notes |
|---|---|---|---|
| Cubase 16 | Works | Works | Dragging several selected clips out of Cubase brings only one into MIDI Interchange; see below |
| Reason 14 | Works | Works | Reason splits a multi-channel track by channel; see below |
| RapidComposer 6 | Works | Not yet confirmed | Single clip/track only |
| Scaler 3 | Works | Works | Where it applies, e.g. the main page |
| Staccato.ai | Works | Works | Fine in both directions |
| Logic Pro | Doesn't work | Works | Logic doesn't drag MIDI out |

No app needed macOS file promises or any other native adapter: everything that worked did so with plain file URLs.

### DAWs and their hosted plugins (tested by hand, macOS, reported 2026-11-10)

Dragging MIDI between a DAW and a VST plugin running inside it (for example Scaler 3 or RapidComposer as a plugin):

| Host | Plugin → host sequencer | Host sequencer → plugin | Notes |
|---|---|---|---|
| Cubase 16 | Works | Works | From the Project window only **one** MIDI part goes, however many are selected, the same as dragging to the desktop or to MIDI Interchange (see the Cubase section below) |
| Reason 14 | Works | Doesn't work | Reason takes MIDI dragged out of a hosted VST into its sequencer, but can't drag sequencer MIDI into the plugin |

These aren't MIDI Interchange bugs or feature requests. They are more evidence that MIDI drag-and-drop between music apps is inconsistent and often one-way, even inside a single host. See DESIGN_NOTES "Why MIDI Interchange".

## Clipboard investigation

Captured on macOS with the Clip-Test utility (`../Clip-Test`), by copying clips in each app. Raw captures are in `../Clip-Test-Results` (not in this repo).

**Short answer: none of the three DAWs puts usable MIDI on the system clipboard, and none offers a practical route to it. Clipboard import isn't worth building for these apps.**

### Cubase 16: a pointer, not data

- One item, type `com.steinberg.pasteboardtype.0x105020168`, **8 bytes** whatever was copied: one clip, many clips or a range selection.
- The 8 bytes are a little-endian 64-bit value, for example `0x0aa6bf5080`, `0x0a8db7a400`, `0x0a8db7aa00`. They are heap addresses inside Cubase's own process. The type name itself (`0x105020168`) also looks like an address.
- The clipboard only says "Cubase has something copied"; the MIDI stays in Cubase's memory. Another process can't use a pointer into Cubase.
- **Verdict:** nothing to reverse engineer. Not viable.

### Reason 14: proprietary, compressed or encrypted

- One item, type `se.propellerheads.smuggler.clippingtype.XSSN`. Sizes vary with content: 724 bytes for 1 clip, 3,372 for 3 clips.
- The layout:
  - **Header:** the ASCII text `Propellerheads Reason Clipboard` followed by `0x1A`.
  - **Padding:** zeros up to offset `0x78`.
  - **Two fixed words:** `e7 1f de 31` (the same in every capture) and `00 00 40 00`.
  - **Payload:** the rest.
- The payload is high-entropy: 7.6 to 7.9 bits per byte, and zlib can't shrink it at all. It isn't zlib, raw deflate, gzip, LZMA or bzip2 at any offset tried. That points to encryption, or compression followed by encryption. Reason's song files are known to be obfuscated in a similar way.
- **Verdict:** the MIDI is probably in there, but getting it out would mean breaking Reason's encryption. That's fragile, could break with any Reason update, and may conflict with its licence terms. Not practical. Reason already drags MIDI into MIDI Interchange, which covers the need.

### Logic Pro: a text listing, no notes

- Logic writes only plain text (`public.utf8-plain-text`, plus the legacy `NSStringPboardType` alias). Its own clipboard format never reaches the system pasteboard.
- The text is a tab-separated listing of the copied regions: position in bars, beats, divisions and ticks; region name; track number; and length. For example:
  `39 1 1 1  Liverpool  2  4 0 0 0`
- There are **no notes**, so it can't be turned into MIDI. At most it could place empty regions.
- **Untested idea:** copying rows from Logic's *Event List* editor may give one text line per note event. If so, those lines could be parsed into MIDI. That's fragile, depends on the display settings, and is only worth a look if Logic matters a lot, since Logic can't drag MIDI out.
- **Verdict:** not viable for regions. Event List text might be worth one quick capture.

### What other apps do (web research, 2026-11-09)

- **There is one documented cross-app MIDI clipboard convention: `public.midi-audio` (macOS) holding a Standard MIDI File.**
  - **Sibelius and Pro Tools** use it, from Sibelius 2024.3 with a current Pro Tools. Copying MIDI in either one puts standard MIDI on the public clipboard. Sibelius has *Paste MIDI* (Home ▸ Paste ▸ Paste MIDI).
  - Avid says any other app using `public.midi-audio` the same way can copy and paste with both.
  - Its Sibelius forum suggested, around launch, that only Pro Tools did this so far.
- **Finale** (discontinued in 2024) was reported to put generic MIDI on the OS clipboard.
- **Dorico** accepts MIDI pasted from the clipboard but, as of 2020, didn't put MIDI on it. Its drag and clipboard formats are reportedly the same.
- **Logic**'s clipboard text was described as a byte dump; the captures above show a region listing.
- **No source describes copying several DAW clips to the clipboard as MIDI.** Multi-clip interchange in the reports is always by exported file.

What this means for MIDI Interchange:

- `public.midi-audio` is the one format worth supporting. It's cheap:
  - **Paste:** the drop code already finds any format whose bytes start with `MThd`, so a Paste command could reuse `extract_payloads()` on the clipboard's mime data.
  - **Copy:** put the export SMF on the clipboard as `public.midi-audio`.
- **Not yet tested:** it would let MIDI Interchange exchange MIDI with Pro Tools and Sibelius by copy and paste. Clip-Test should confirm what Pro Tools or Sibelius really writes before anything is built.

Sources: [Avid: Copy and paste music between Sibelius and Pro Tools](https://www.avid.com/resource-center/sibelius-pro-tools-copy-paste), [Sibelius forum: copy and paste MIDI data between Sibelius and Pro Tools](https://www.sibelius.com/cgi-bin/helpcenter/chat/chat.pl?com=thread&start=769447&groupid=3&guest=1), [Steinberg forum: Pasting midi between apps](https://forums.steinberg.net/t/pasting-midi-between-apps/127746).

### Conclusion

There is still no MIDI clipboard format that DAWs share in practice. Cubase, Reason and Logic keep copy and paste internal to themselves. The only documented public convention is `public.midi-audio`, used by Pro Tools and Sibelius. Drag and drop with file URLs remains the working route. Clipboard support in MIDI Interchange is only worth considering as `public.midi-audio` copy and paste, and only after a Clip-Test capture from Pro Tools or Sibelius confirms it. Clip-Test flags `MThd` data and file URLs automatically.

## Open issues

### Reason splits multi-channel tracks — importer behaviour

**Confirmed 2026-11-10 on the studio Mac.** Dragging from MIDI Interchange into Reason 14 works, for the whole workspace and by range. But a track whose clips use more than one MIDI channel arrives in Reason as **one track per channel**, all with the same name, and Reason adds the channel to each track's name. It went unnoticed before because most files use only channel 1 or 10.

- How it shows up in clip assembly: clips keep their own channel when moved (DESIGN_NOTES Risk 9). Staccato.ai files, for example, put same-named tracks on different channels, so assembling them gives a multi-channel track.
- MIDI Interchange's export is not at fault: `tests/test_export_assembly.py` proves an assembled track is written as one track holding every note, and `samples/reason-check/` has a one-channel and a two-channel assembled file that show the difference in Reason.
- Reason's own export confirms its model (`samples/non-synthetic/Nov01-01-000-Reason.mid`, exported from the Staccato song after a drag-in): every track is written on **channel 1**, the original channel is kept only in the track name ("… Ch4", "… Ch8", "… Ch10"), it writes at **15360 PPQ**, and adds note-less "Transport" and "Master Section" tracks. MIDI Interchange imports it cleanly.
- Other importers may do the same. Workaround for now: assemble clips that share a channel, or set channels in the source DAW first.
- Decision deferred (back burner): an export option to put each track on one channel, and/or per-clip channel changes. See DESIGN_NOTES Risk 9 and the to-do list.


### Cubase: several selected clips drag in as one — Cubase limitation

**Settled (2026-11-09): Cubase exports only one clip per drag, whatever the destination.** MIDI Interchange isn't losing anything. Confirmed again on 2026-11-10 with a VST hosted in Cubase as the destination: one part, the same as the desktop and MIDI Interchange.

What the tests showed:

- Dragging several clips from Cubase 16, on one track or across tracks, produces **one** `.mid` file even when dropped on the Finder. That file holds only the primary (clicked) clip, not a merge.
- **Clip-Test "Read last drag" sees nothing from Cubase.** After every Cubase drag the drag pasteboard was empty (0 items), though its change count had moved on. Cubase seems to fill the drag pasteboard lazily and clear it when the drag ends, so its drags can't be inspected afterwards. Raw captures are in `../Drag-Test-Results`.
- As controls, the same tool showed the expected contents for other drags:
  - four MIDI files dragged together from the Finder: four items, one file URL each;
  - a drag out of MIDI Interchange: one temp `.mid` plus Qt's own types;
  - single MIDI files dragged from the Finder.
- Dragging the file Cubase created from the Finder into MIDI Interchange works as expected.
- MIDI Interchange imports every file URL in a drop ([drag_import.py](../midi_interchange/interchange/drag_import.py) `extract_payloads()`), and the Finder test above confirms that multi-file drops arrive.

What others report: Steinberg forum users have described the same thing since at least Cubase 8.5: dragging one part to the desktop gives a `.mid` file, but a multi-part selection "only will make a midi file for one of them". The suggested workarounds are one part at a time, or File ▸ Export ▸ MIDI File. Steinberg's own help documents dragging a single part only. No official multi-part drag support, setting or fix was found.

Ways to move several Cubase clips into MIDI Interchange (for users):

1. **Drag them one at a time.** Each lands as its own track (works today).
2. **File ▸ Export ▸ MIDI File in Cubase**, after soloing or selecting the tracks you want and setting the locators to cover the clips. Then drag or open that file in MIDI Interchange, which handles multi-track Type 1 files and lets you pick ranges and tracks. Not yet tried with Cubase 16's export options.
3. **Untested:** in Cubase, glue the parts on a track into one part, then drag that part. That only helps for parts on the same track.

Dragged parts also **lose their position**: tested 2026-11-09, a Cubase part at bar 9 arrives at bar 1. That's normal for a dragged clip; a MIDI file has no field for it.

**Response in MIDI Interchange (feature/clip-assembly):** drop each part where it belongs. The insertion cursor shows the track and bar; a part whose track name matches the track under the cursor joins it, otherwise it becomes a new track at that bar. Clips can be Option-dragged between tracks, copied, butted against the previous clip, and tracks merged. See the README "Using it" table.

Sources: [Steinberg forum: How do I export a single midi part?](https://forums.steinberg.net/t/how-do-i-export-a-single-midi-part/75973), [Steinberg forum: Midi export seems impossible with Cubase 12](https://forums.steinberg.net/t/midi-export-seems-impossible-with-cubase-12/807297), [Steinberg help: Exporting MIDI Parts as MIDI Files (Cubase 12)](https://archive.steinberg.help/cubase_pro/v12/en/cubase_nuendo/topics/parts_events/parts_and_events_midi_files_exporting_t.html).

### New Document / Clear All

Done on feature/clip-assembly: File ▸ New (⌘N, also on the toolbar) empties the workspace as one undoable step and keeps the export settings.
