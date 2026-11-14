# DAWproject importer

Branch: `feature/direct-daw-import-dawproject`, based on and targeting
`feature/direct-daw-import`. Implemented for review; studio verification pending.

## Reader contract

`interchange/readers.py` owns the reader registry, detection, file filters and
path-to-payload loading. Both Open and drag/drop use it; clipboard MIDI continues
to supply bytes. A format parser returns `(Source, list[Track])` or raises `ImportError_`.
The registry wraps it in `ImportResult`, which unpacks as that pair and carries
the format-neutral policy for preserving imported track state.
Source warnings are the persisted diagnostics, surfaced by the existing controller
and Source Info. Readers do not mutate the workspace or write input files.

Each registry entry declares extensions, a detector, a read function and whether
it needs a path. MIDI remains byte-backed with its existing 64 MB limit.
DAWproject is path-backed: only `project.xml` and optional `metadata.xml` are read
from the ZIP. Each XML member is capped at 16 MB, entity/DTD declarations are
rejected, and no archive member is extracted. Timeline recursion, loop repetitions
and generated MIDI events are bounded. A byte-backed DAWproject is also accepted
for tests or future adapters.

## Musical mapping

Implementation follows the [official DAWproject reference](https://github.com/bitwig/dawproject/blob/main/Reference.html),
checked against the supplied Cubase 15.0.30 and 16.0.5 exports.

- Arrangement tracks and clips, names, MIDI channels, keys, attack/release
  velocities and note durations. Notes become paired mido messages.
- Inherited beat/second units and mixed clip content units. Seconds are integrated
  through the stepped tempo map, including notes crossing tempo changes.
- Transport tempo/meter, stepped tempo automation, time-signature changes and
  arrangement markers. Tempo ramps fail explicitly rather than drift silently.
- Clip `playStart`, `playStop` or duration become reversible model trims.
  Negative content starts (silence) and notes preceding content zero are handled.
- Content references resolve by ID. Loops are unrolled with note releases cut at
  boundaries. Nested MIDI clips are flattened into their containing clip; nested disabled MIDI
  clips fail explicitly because flattening would lose their independent mute state.
- Track mute/solo is preserved for newly imported project tracks. Group tracks
  are flattened with inherited mute/solo applied to descendants. Existing track
  controls retain their state when placement joins clips to that track.
- `Source.input_format` and `format_version` distinguish DAWproject provenance
  from SMF. `app` records exporter name/version; metadata Title is the song title.
  DAWproject uses 960 PPQ as its MIDI export resolution; source times are stored
  in beats with denominators bounded to 1e9 to fit session numeric limits
  (sub-nanobeat approximation, not grid snapping). Original bytes remain empty.

## Clip mute scope and behaviour

The Cubase 15 fixture includes 52 disabled MIDI clips. Preserve them with an
explicit `Clip.muted` flag rather than discard them or mute their whole track.
The flag travels with duplicated, split, moved and trimmed clips, undo/redo and
sessions. A clip context-menu action toggles it; muted clips have a subdued fill
and a `[muted]` label. This is an independent gate: track solo or locked range
inclusion does not override clip mute. Every export mode and content-based trim
ignores muted clips. Full extent, stored events, source details and timeline
positions remain available. Existing Clear All Mutes retains its track-only scope.

Sessions now write schema 3. Explicit upgrades accept schema 2 (default source
format SMF, version unknown, clip mute false) and schema 1 (also preserve original
size and clear retained bytes as before). Loading never rewrites input files.
Older application versions cannot restore schema 3.

## Explicit limitations

Audio, media, devices, plug-in states, launcher scenes and automation are skipped
with diagnostics. This includes MIDI CC/expression automation and per-note
expression; they are not rendered from instruments or plug-ins. Only arrangement
MIDI is supported. No lyrics are invented from clip labels. Unsupported format
versions, broken references, invalid note values, tempo ramps and malformed
archives/XML fail through the normal import error path before workspace mutation.
DAWproject is not a native Cubase reader. Other DAW exporters remain unverified.

## Paired-export evidence

Run `.venv/bin/python scripts/compare_project_exports.py` for a per-track JSON
comparison of audible notes: start, end, pitch, attack velocity and channel,
rounded to 480 PPQ. Track mute and clip mute are respected; repeated track names
are paired in order. Release velocity is excluded from this comparison because
Cubase's DAWprojects use zero where MIDI often uses 64.

| Project | Imported MIDI clips | Stored notes (including muted) | Muted clips | Audible DAWproject notes | Paired MIDI notes on matching tracks | Matching complete notes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Ditty-04-Macbook | 175 | 1501 | 52 | 646 | 647 | 497 |
| GA & Padshop 2-(alt instr 2)-01 | 182 | 6435 | 0 | 6308 | 1581 | 1556 |
| indy-001x | 104 | 819 | 2 | 803 | 663 | 0 |

These files are comparison material, not interchangeable golden outputs. For
example, indy DAWproject Bass Sequence starts at beat 36 whereas its MIDI starts
at beat 33. GA DAWproject carries 93/97 BPM changes whereas the paired MIDI has a
single 93 BPM event. Ditty's audible Epic Choir matches all 36 complete notes
when release velocity is excluded; that comparison is an automated regression.
Other differences include extra material, timing, note lengths and mute state;
the report preserves these discrepancies rather than normalising them away.
They need studio investigation before claiming full paired-export equivalence.

## Manual verification

- Open and drag each DAWproject into an empty workspace; inspect positions and
  Source Info, including warnings and tempo changes.
- Check disabled Ditty clips stay visible and silent; unmute one, export, then
  undo and repeat with a locked range and track solo.
- Save/relaunch with an imported project after moving its original file; verify
  source details, trims, mute and export remain intact.
- Listen/compare the paired exports in Cubase and explain the discrepancies above.

## Automated verification

- Full regression run: **420 passed, 3 platform skips** (local-socket tests run
  with permission outside the sandbox).
- After the final shared-result policy adjustment: **192 passed, 2 platform
  skips** covering importer, placement, song matching, UI assembly, mute/solo,
  Source Info and session compatibility.
- Final importer suite: **28 passed**, including disabled loops retaining their
  notes, nested aliases, inherited group mute/solo, malformed archives/XML,
  seconds and mixed units, stepped tempo/meter, marker mapping, all export modes
  with locked ranges and solo, and all three supplied Cubase project sets.
- `git diff --check` passes. No build or release produced; manual checks above
  remain pending.
