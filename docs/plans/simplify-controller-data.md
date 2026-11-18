# Plan: simplify controller data on export

Status: **built and manually tested (2026-11-18).** Branch, when built: `feature/simplify-controller-data` from the release branch (`release/0.5.0`), as all features are.

An export option, **off by default**, that thins dense controller streams to the few points a DAW needs to draw the same curve.

## Why

DAWs write curves as a dense stream. Reason's export has a value every 1/32 beat. Importing that into Reason gives a staircase of points. Most DAWs draw straight lines between imported points, so a thinned stream comes back as a few clean points.

The app aims to be a transparent transport, and this deliberately changes the data. So it is opt-in, and every default path stays byte-for-byte as it is today.

## Behaviour

- A checkbox **Simplify controller data** in the export panel, beside **Trim leading/trailing silence**. Off by default. Tooltip: "Drops repeated controller values and thins curves to the fewest points within one step of the original. Changes the data."
- It's an export setting, like trim: it applies to Save MIDI and to drag-out alike (the app treats drags and file operations as equivalent), and to all four export modes. It's held on the controller and **not** saved with the session, so it is off again after a restart: it changes the data, so it shouldn't stay on unnoticed. (Trim and the export mode are saved; this one deliberately is not.)
- Source events and clip event lists are never modified. Turning it off restores the original output at once.

### What is simplified

All continuous messages, each stream keyed on the **final** output channel:

| Message | Stream key | Tolerance (fixed) |
|---|---|---|
| Control change | channel, controller number | 1 (one 7-bit step) |
| Pitch bend | channel | 128 (one 7-bit step of the 14-bit value, so the same relative size as a CC step) |
| Channel aftertouch | channel | 1 |
| Polyphonic key pressure | channel, note | 1 |

The CC tolerance may become selectable later. It's one named constant per message type now.

**Never touched** (left exactly as they are, including repeats): program change, key signature, meta events, SysEx, notes, and the controllers that aren't curves:
- Mode controllers 120–127, already excluded from edge state-carry.
- Bank select (0, 32).
- RPN/NRPN and data entry (6, 38, 96–101): their value messages must arrive in sequence.

### The two steps, per stream, in time order

1. **Tidy.** Of several events on the same tick, the later wins. Events at the very end of a stream that repeat the value before them are dropped, because the value holds after the last point anyway.
   - A repeat in the middle of a stream is **not** dropped on its own. A DAW that draws straight lines would turn "50, 50, then 100" (hold, then ramp) into a ramp from the first 50. Repeats are left to step 2, which collapses a run of equal values to its two ends and keeps the corner.
2. **Thin.** Keep the first and last point. Between them keep the fewest points such that, when the DAW joins the kept points with straight lines, the line is within tolerance of **every original point**.
   - Method: from an anchor point, extend the segment to the farthest point such that all points between stay within tolerance of the line; keep the point before the first failure and make it the new anchor. Done in one pass by tracking the range of slopes still allowed. This is near-minimal, not proven to give the absolute fewest points. Fine for this purpose.
   - The first event of a stream in an export is always kept. It's usually the carried start value the range rules emit, and no earlier value is known.

### Where it happens

Last, on the final stream, after the clip cutting, state-carry, rebasing and channel override have run. Range cuts and rebases are therefore unaffected, and a channel override that merges two channels onto one is thinned as the one stream the DAW will see.

It runs as one post-pass over each finished MIDI file (`simplify_midi`), on the tick-quantised events, so "within tolerance" is measured at the ticks that are actually written, at the export's PPQ. Event order, track names, range names and filenames are unchanged.

## Code

- **New `core/simplify.py`**: a pure function over the output track's messages (stream keys, tolerances, the exclusion set, the two steps). No Qt, no mido I/O beyond messages. All the rules above live here.
- **`core/export_smf.py`**: `ExportOptions` gets `simplify_controllers: bool = False`. It's applied in the one shared path that builds each output track, after the channel override in `_to_mido_track`. With it off, the code path is untouched.
- **`ui/controller.py`**: an attribute and `set_simplify_controllers`, like `set_trim`; passed through where `ExportOptions` is built.
- **`ui/export_panel.py`**: the checkbox, wired and refreshed like `trim_cb`.
- The drag-out path uses the same `build_exports`, so it needs no separate code. A test proves it.

## Tests (headless)

- **Unit, `simplify`:**
  - Same-tick later-wins; trailing repeats dropped; hold-then-ramp keeps its corner; a flat run collapses to its ends.
  - A straight ramp collapses to its two ends.
  - A step stays a step.
  - First and last points are kept.
  - **Tolerance guarantee** (property test over random curves): every original point is within tolerance of the line through the kept points.
  - Output never has more points than the input; applying it twice changes nothing.
  - Streams are independent per channel, controller, note.
  - Exclusions are untouched, repeats included.
  - Non-continuous messages and their order are untouched.
  - Pitch bend uses 128, the others 1.
- **Export integration:**
  - Off is byte-identical to today's output in all four modes.
  - On reduces a dense stream, and notes, program changes and tempo are identical.
  - Range edge state-carry is preserved.
  - A channel override merging two channels is thinned as one stream.
- **Controller and panel:** the setting reaches `ExportOptions`; the drag payload and Save MIDI give the same bytes for the same setting.
- **Real data:** thin the Reason fixture in `samples/` that has dense curves, and check the point count falls and every original point stays within tolerance.

## Docs and checklist

- README: a line in the export section, noting it changes the data and is off by default.
- TEST_CHECKLIST: a manual section (below).
- ROADMAP: remove the entry when built (the roadmap's own rule).

## Manual test (step 4)

- Import a Reason project with dense curves. Export with the option off, then on, into Reason. Off gives the staircase; on gives a few clean points that look the same.
- Same into Cubase.
- Drag out with the option on, and compare with Save MIDI.
- Check that sustain, program changes and notes are unchanged.

## Decisions settled in review (2026-11-18)

- **Never-touched list:** agreed as above (bank select, RPN/NRPN, data entry, mode controllers).
- **Polyphonic key pressure:** included, with channel aftertouch.
- **Branch:** features branch off the release branch.
- **Stepped data:** large jumps are already "simple". A jump bigger than the tolerance is never removed, so a deliberate step stays a step. Only a staircase of tiny steps, which is what a dense curve looks like, is flattened into a ramp. No extra filtering is needed.
