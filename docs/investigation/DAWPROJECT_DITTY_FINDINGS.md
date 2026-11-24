# Cubase Ditty: DAWproject → MIDI comparison

Investigated on `feature/direct-daw-import-dawproject` after `7071c14`.
The user confirmed “guitarditty” means the supplied `Ditty-04-Macbook` set
(Cubase 15.0.30).

## Conclusion

The differences are real and some substantially change playback. Most are already
present in the supplied DAWproject versus the supplied Cubase MIDI. Reading the
DAWproject correctly cannot recreate MIDI processing or controller data that it
does not contain. One remaining difference is our deliberate clip-edge policy:
we cut notes at the visible clip end, whereas this Cubase MIDI retains some tails.
Do not change pitches, deduplicate notes or synthesise an arpeggiator just to make
this fixture match; that would guess at missing project behaviour.

No general importer timing/note-reading error was found in this set. An
independent test derives note events directly from the flat XML, applies 80 BPM
and clip windows without using importer/timing/pairing/export helpers, and checks
the **serialized and reparsed app export**. All **1,292 note events (646 notes)**
match, including channel and attack/release velocity. This proves adherence to
this file under our clip-edge rules, not equivalence to Cubase playback or to all
DAWproject features.

## Reproduce

```
.venv/bin/python scripts/compare_project_exports.py > /tmp/project-export-comparison.json
.venv/bin/pytest -q tests/test_dawproject_comparison.py tests/test_dawproject.py
```

The comparison now constructs the workspace, exports MIDI, serializes it and
reparses it. The previous script compared the pre-serialization model and rounded
times to 480 PPQ with Python's tie-to-even `round`. That could conceal half-tick
changes. The new report retains fractional reference ticks, distinguishes exact
matches from differences within one reference tick, and reports changed releases,
unmatched notes, controllers, bends, release velocities and track structure.
Velocity-zero note-ons are treated as note-offs. Repeated names are paired in order.
Release velocity is reported separately from note matching. Same-time tempo/meter
ordering is normalized for comparison; musical event ordering is retained.

## Measured differences

The app writes 960 PPQ; Cubase writes 480 PPQ. All comparisons below use musical
time, not raw tick integers. Both exports have the same 80 BPM, 4/4 timing map.

| Sounding track | App notes | Cubase notes | Notes matching within one Cubase tick | Remaining difference |
| --- | ---: | ---: | ---: | --- |
| Epic Choir | 36 | 36 | 36 | CC1 missing; release velocity differs |
| Intimate Strings | 108 | 113 | 0 | Held duplicate notes versus repeated short notes; CC1 missing |
| Epic Brass and Woods | 27 | 27 | 27 | Pitch bends missing; release velocity differs |
| Rare Flutes (D) | 47 | 47 | 47 | Pitch bends missing; release velocity differs |
| Soft Nylon Gtr | 18 | 27 | 0 | Held chords versus short sequential notes, an octave higher |
| Soft Steel Gtr 2 | 12 | 12 | 12 | Sub-tick rounding; release velocity differs |
| Soft Steel Gtr | 114 | 107 | 97 | Seven extra duplicates; ten paired note ends differ |
| Groove Agent SE 01 | 284 | 278 | 278 | Six extra cymbal notes; CC4 missing; release velocity differs |
| **Total** | **646** | **647** | **497** | |

The similar total note counts conceal substantial musical differences.

### Arpeggiation / MIDI processing: important, not recoverable from this DAWproject

At beat 24, Soft Nylon's DAWproject contains three simultaneous notes, MIDI keys
43, 47 and 50, each two beats long. Cubase MIDI instead begins with keys 55, 59,
62 at beats 23.9979167, 24.4979167 and 24.9979167, each 0.25 beat long. The pattern
continues with further retriggers. This changes rhythm, pitch and articulation;
it is not a PPQ conversion problem.

Intimate Strings likewise contains simultaneous duplicate sustained notes in the
XML; Cubase MIDI has repeated 0.5-beat notes. The native CPR contains readable
`PMidiArpeggiator` / `Arpache 5` strings, while the DAWproject contains no MIDI
arpeggiator device or settings. These observations strongly suggest rendered MIDI
inserts/modifiers, but the exact enabled insert and export-option configuration
has not been verified in Cubase.

Steinberg documents that MIDI **Export Inserts** includes MIDI modifiers and
inserts in the exported MIDI ([Cubase MIDI export options](https://www.steinberg.help/r/cubase-pro/15.0/en/cubase_nuendo/topics/preferences/preferences_midi_midi_file_export_options_r.html)).
That is consistent with the supplied files, not proof of the selected checkbox.

**Fixability:** use the rendered Cubase MIDI for the performed result, or bake
processing into parts in Cubase before exporting DAWproject and verify the result.
The importer cannot infer an arbitrary insert's settings/output from held notes.
A future native reader may expose processing state, but rendering that processing
is a separate capability, not simply reading saved notes.

### Controllers and pitch bends: important, absent from the XML

Cubase MIDI contains **1,224 CC events**: 307 CC1 on Epic Choir, 697 CC1 on Intimate
Strings, and 220 CC4 on Groove Agent. It also contains **207 pitch-bend events**:
52 on Brass and 155 on Flutes, ranging from -228 to +7436. The supplied DAWproject
arrangement has no `Points` or MIDI expression data to recover these from.

These can affect dynamics, articulation/hi-hat position and pitch, depending on
the destination instrument. Their musical significance is much greater than the
small timing-rounding differences. Steinberg's published limitations also list
MIDI CC/pitch-bend as unsupported in this exchange route
([Steinberg DAWproject limitations](https://helpcenter.steinberg.de/hc/en-us/articles/25142209226642-DAWproject-Exchange-Cubasis-projects-with-Cubase-and-other-DAWs)).

**Fixability:** not from the supplied DAWproject alone. Use Cubase MIDI, or a future
paired-import facility that explicitly takes performance events from MIDI while
using DAWproject for layout. Automatic merging is not currently implemented and
must not assume these exports align identically.

### Duplicate and extra notes: present in the source, origin partly unresolved

Soft Steel has seven extra notes in the app result. They are additional copies
of existing same-time/pitch/velocity notes in the DAWproject; they are not created
by the reader. For example, the chord at beat 15.75 contains keys **47, 43, 47**
in XML, while Cubase MIDI contains **43, 47** once each. They may change attack,
voice count or note-release behaviour on some instruments.

Groove Agent has six extra key-49, velocity-127 notes at beats **20, 36, 52, 100,
116 and 132**. They are explicit notes inside enabled clips in the DAWproject
and absent from the corresponding MIDI. They can add audible cymbal hits.

The available XML has no per-note mute flag: its note attributes are only time,
duration, channel, key, velocity and release velocity. Whether the differences
come from muted notes, Cubase processing, or differences in the project state
at export cannot be established from these files alone.

**Fixability:** automatic deduplication would remove intended overlapping notes
in other projects, and deleting cymbals would be arbitrary. Verify the source
notes and export configuration in Cubase, preferably with a tiny fixture that
differs only by one note's mute state. Do not silently repair this by guessing.

### Guitar note tails: important, fixable through an explicit policy

Nine Soft Steel chord notes in the XML extend a beat beyond their clip ends.
For example, the chord beginning at beat **57.75** has a clip ending at **60**,
but its stored note durations end at **61**. Cubase MIDI retains the releases
at 61; our visible-trim export cuts them at 60. At 80 BPM this is **0.75 seconds**
of sustain. Three such chords account for nine shortened stored notes; overlap
of two key-50 notes also changes FIFO pairings, giving ten differing paired ends
in the comparison report.

Both the original durations and the clip bounds are retained in our model, so
this information is recoverable. The app's current documented trim behaviour
cuts note tails to clip boundaries. The DAWproject reference defines clip and
note durations separately but does not settle Cubase's playback-tail policy
([official reference](https://github.com/bitwig/dawproject/blob/main/Reference.html)).

**Fixability:** add a defined “allow note tails beyond imported part ends” policy,
with rules for later user trims, loop boundaries and ranges. Do not globally stop
cutting note releases: that would change existing edit/export behaviour. This
investigation leaves the current policy unchanged; reconsideration is deferred
by agreement (2026-11-14), not a blocker for provisional completion.

### Small timing and structural differences: usually low importance

Among the 497 matching complete notes, 464 match exactly and 33 differ by at most
one Cubase tick at one or both boundaries. One 480-PPQ tick at 80 BPM is **1.5625
ms**. These small shifts reflect different source precision and output rounding;
there is no global offset in Ditty. Preserve the DAWproject times rather than
introducing a one-tick correction to imitate one exporter.

Release velocities differ: the DAWproject explicitly stores zero; Cubase MIDI
generally writes 64, and most Groove Agent releases use 100. This often has little
effect but matters on instruments using release velocity. Do not replace explicit
source zero values with guessed defaults.

Empty track count, conductor naming, same-time meta ordering, MIDI running-status
encoding and PPQ can differ without changing the performance. Byte equality is
not an appropriate acceptance test. Normalized musical events and the meaningful
differences above are the relevant comparison.

## Follow-up

1. Confirm Cubase's insert/modifier export settings and inspect the six cymbals
   and duplicate guitar notes. A differential note-mute fixture would resolve
   that ambiguity more reliably than modifying the reader.
2. Imported-part note-tail policy is deferred by agreement (2026-11-14); keep current cutting behaviour. It does not block provisional DAWproject completion.
3. Warn users that source DAWproject data may omit rendered MIDI processing and
   performance controllers; the existing generic “plug-ins skipped” warning does
   not fully explain this particular loss.
4. Continue native-reader investigation independently; DAWproject equivalence is
   not evidence that native MIDI processing can be reproduced.

Verification: **31 passed** across the importer and comparison suites;
`git diff --check` passes. No production importer/export behaviour changed in
this investigation, and no build/release was made.
