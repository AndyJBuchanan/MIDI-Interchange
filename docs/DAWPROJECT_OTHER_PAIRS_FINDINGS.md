# Cubase DAWproject comparison: indy and GA & Padshop

Follow-up to the [Ditty investigation](DAWPROJECT_DITTY_FINDINGS.md).

**Acceptance rule:** Cubase's supplied MIDI is the ground truth for the performed
MIDI. DAWproject fidelity tests diagnose whether the reader follows the XML; they
do not supersede the MIDI reference or establish performance equivalence. We are
not repairing Cubase's DAWproject exporter. Missing processing, notes or metadata
remain documented gaps until an input route can actually supply them.

## Comparison method

Compare the actual serialized/reparsed app MIDI with Cubase's MIDI, normalizing
PPQ and separating exact matches, one-reference-tick differences, changed releases
and missing/extra notes. Include controllers, bends and missing tracks. The default
comparison retains the whole DAWproject arrangement.

The new explicit `--window` option additionally tests a specified source beat
window, rebased to zero. It neither infers ranges nor changes input files or
normal import behaviour. This distinguishes export-scope discrepancies from
reader errors. The ranges below explain the files numerically; Cubase's actual
locator/export-option settings have not been independently inspected.

```
.venv/bin/python scripts/compare_project_exports.py > /tmp/whole-pairs.json
.venv/bin/python scripts/compare_project_exports.py \
  --window indy-001x 3 196 \
  --window 'GA & Padshop 2-(alt instr 2)-01' 0 192 \
  > /tmp/reference-window-pairs.json
.venv/bin/pytest -q tests/test_dawproject_comparison.py tests/test_dawproject.py
```

An independent raw-XML test also constructs note events without the importer
clock, pairing or export-cutting helpers. It applies inherited seconds, clip
playStart/duration, stored velocities, mute state and the stepped source tempo
map. It checks actual serialized output against **1,606 indy note events** and
**12,616 GA note events**, allowing at most one output tick for rounding ties.
This checks XML fidelity separately from MIDI-reference acceptance.

## indy-001x

### Export scope explains the apparent global offset and most extra notes

The whole DAWproject has 803 audible notes on four musical tracks, plus markers.
The reference has 1,307 notes, including two drum tracks missing from the
DAWproject arrangement. Comparing only same-named tracks without aligning scope
previously suggested almost every note was different.

The source window **[3, 196) beats**, rebased to zero, reproduces these reference
tracks:

| Track | App in window | Cubase MIDI | Exact complete-note matches | Residual difference |
| --- | ---: | ---: | ---: | --- |
| Bass Sequence | 390 | 390 | 390 | None, apart from release velocity |
| Industrial Stab | 225 | 225 | 225 | None, apart from release velocity |
| Secondary Motif | 24 | 24 | 24 | None, apart from release velocity |
| Texture Bed | 24 | 24 | 22 | Two shortened releases |
| **Available tracks** | **663** | **663** | **661** | |

For example, DAWproject Bass begins at beat 36; reference MIDI begins at beat 33.
Subtracting the explicit three-beat window origin explains that difference. The
extra late DAWproject notes fall outside the reference's apparent export window.
Do not insert a permanent three-beat correction into the reader.

Both files carry 120 BPM and 4/4. Neither reference nor output contains CC or
pitch-bend messages. DAWproject release velocities are zero; MIDI uses 64.

### Two drum tracks: important missing performance data

Cubase MIDI contains **596 Drum Core notes** and **48 Drum Core = notes**.
DAWproject has track definitions and corresponding arrangement lanes, but both
lanes are empty: no clips, notes or other timeline content. These 644 notes are
therefore not a parser traversal omission. Device state is not a substitute for
saved arrangement notes; the files do not establish why Cubase omitted them.

**Fixability:** not by reading the present DAWproject arrangement. Use the MIDI
reference for these notes, or later investigate the native project/DAW export
configuration. Do not generate a drum pattern to fill the gap.

### Two Texture Bed tails: important, same existing policy issue as Ditty

After rebasing, the two key-55 notes start at beats **105** and **121**. The app
releases at **113** and **129**, matching their clip ends. Cubase MIDI releases
at **114** and **130**, matching the longer stored XML note durations. Each loses
one beat (**0.5 seconds** at 120 BPM) under the current visible-trim policy.

**Fixability:** the data is present; an explicit imported-part tail policy can
preserve these releases. This is not a timing conversion fault or a reason to
change user trim/range boundaries globally. No production policy changed here.

## GA & Padshop 2-(alt instr 2)-01

### Export scope explains most extra arrangement and tempo changes

The reference's final note boundary is beat **192**. The DAWproject arrangement
continues much later. In a whole import/export the app has 6,308 audible notes;
the reference has 1,581.

The apparent tempo mismatch is also outside the comparable section. The app
preserves the DAWproject's 93/97 BPM changes; the first actual BPM change is near
beat **271.834**. Restricting the diagnostic export to **[0, 192)** gives the same
93 BPM, 4/4 timing map as the MIDI reference. Do not remove those later tempo
changes from the reader to imitate a shorter MIDI export.

| Track | App in window | Cubase MIDI | Matching complete notes | Residual difference |
| --- | ---: | ---: | ---: | --- |
| hbar Sample Pack 1 Kit | 1854 | 1008 | 1008 exact | 846 extra notes |
| HALion Sonic SE 01 | 80 | 80 | 80 within one reference tick | Small rounding only |
| Retrologue 01 | 14 | 14 | 14 exact | None |
| Piano Chords | 194 | 194 | 194 exact | None in the reference window |
| Piano Chords (D) | 265 | 265 | 265 exact | None in the reference window |
| Prologue 01 | 20 | 20 | 0 at original pitch | All pitches differ by 24 semitones |
| **Total** | **2427** | **1581** | **1561** | |

Two other MIDI tracks, Engaging Peace and Where Are We, have track mute set in
the DAWproject and are excluded from the app's global export. They have no
performance tracks in the reference. Their stored events remain in the app model.
Neither MIDI comparison contains controller or pitch-bend messages.

### 846 extra kit notes: important source discrepancy, not repeated import

The 1,008 reference kit notes all match, but 846 additional notes remain inside
the same 192-beat window. They are not just copies of matching reference notes.
Extra-note counts by key are:

| MIDI key | Extra notes |
| --- | ---: |
| 36 | 9 |
| 37 | 120 |
| 38 | 128 |
| 39 | 48 |
| 40 | 206 |
| 41 | 16 |
| 42 | 97 |
| 43 | 34 |
| 45 | 4 |
| 46 | 96 |
| 47 | 12 |
| 49 | 10 |
| 51 | 66 |

For example, the very first XML clip includes a key-40, velocity-65 note at time
zero lasting approximately 0.001344086 seconds. It appears as a one-reference-tick
note in the app export and has no corresponding reference MIDI note. The
independent XML event check rules out reader-generated repetition as an
explanation. Many extras differ in onset/velocity from the reference and would
change the drum performance.

Whether these notes were muted individually or affected by other Cubase state
is not established. There is no corresponding note-mute attribute in this XML.

**Fixability:** cannot safely delete them from this DAWproject alone. Inspect
native note/export state later, or use Cubase MIDI for the performance. An
instrument-specific drum filter or deduplication rule would be an invented repair.

### Prologue: two-octave performance transpose absent from the XML

All 20 reference notes are **24 semitones higher** than their corresponding
DAWproject notes. For example, the first event at beat **112** has key **45** in
XML and key **69** in MIDI, both at attack velocity 51. All onset/duration/velocity/
channel correspondences match within one reference tick if a **diagnostic +24**
is applied to the comparison notes. The production reader does not apply it.

This strongly suggests a track modifier or other rendered processing. The exact
Cubase control responsible has not been established, and no transpose parameter
for these notes is supplied in the DAWproject arrangement.

**Fixability:** not by guessing a transpose in the DAWproject reader. A later
native reader may expose the missing state; the supplied MIDI is already the
performed ground truth. This is a musically important difference.

### Reference end and note-off safety

The reference contains five note-ons without corresponding explicit releases:
one in the kit, three in Piano Chords and one in Piano Chords (D). The diagnostic
comparison closes these at the reference end-of-track, as the normal MIDI reader
does. A windowed export emits safe releases at beat 192. This explains the five
apparent release-length differences in the unwindowed comparison; it is not a
reason to omit releases or create stuck notes to match raw MIDI bytes.

## Result and follow-up

No additional note-reading, lane traversal or seconds/tempo-conversion fault was
found in these two fixtures under the current clip-window policy. They still do
**not** satisfy performed-MIDI equivalence: indy lacks 644 drum notes and has two
shortened tails; GA has 846 extra kit notes and a 24-semitone Prologue difference.
Range selection explains a substantial part of the earlier discrepancies.

Keep both tests: the MIDI reference measures the required performance; independent
XML fidelity localizes faults to our reader versus absent/different source data.
Any native Cubase reader should be checked against this same MIDI ground truth.
DAWproject is provisionally implemented by agreement (2026-11-14). Imported-part
tail policy is deferred; current clip-edge cutting remains unchanged. Other
source discrepancies require additional/native input, not Cubase-export repair.

Verification: **35 passed** across the importer and comparison suites; whole and
explicit-window comparison commands completed successfully; `git diff --check`
passes. No production import/export behaviour changed, and no build/release was
made. Studio verification of export settings remains outstanding.
