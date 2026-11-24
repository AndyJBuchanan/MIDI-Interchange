# Plan: Cubase chord track as chord names

Status: **plan** (2026-11-16). Agreed in principle on 2026-11-15 ([roadmap](../../ROADMAP.md), [Cubase plan, decision 1](cubase-import.md#decisions-2026-11-15)): don't render chords as notes; show the chord names on a marker-style track. This plan covers decoding, the model, display, export, and the open questions.

## What we know already

**The data is there and looks readable.** Five real projects have chord tracks: GA (19 chords, 5 scale events), Ditty (42), Beat003vs (45), vocalfun001 (10) and BBCSO (1). The c-series projects have none.

- `MChordTrackEvent` (the track) holds `MChordEvent` objects, one per chord, each with a `CmString` and a `CmAttribCollection` holding a `ChordData` object.
- An `MChordEvent` body starts with an **f64 position in ticks** (GA's second chord: 15,360 = beat 32), then a byte that looks like the **root as a note number** (0x43 = G, 0x3E = D), then properties (`CHRD`, `XFLG`, `XEUI`, a GUID, `relP`, `ScAr`).
- `ChordData` should hold the chord type, tensions and bass note: **not decoded yet.**
- `MScaleEvent` objects hold scale names ("Major") at positions: Cubase's scale track, part of the chord track.
- A chord has no length: it lasts until the next chord. There may be "X" (no chord) events.

**Cubase's MIDI export doesn't carry chords.** GA's and Ditty's exports have no chord track and no text or marker events. So chords can only come from the native `.cpr`, unless dragging chord events out of Cubase produces something (to try).

**What the app has.** Markers arrive as `marker` meta events on an auxiliary "Markers" track. The header has one marker row, built from the marker events of the tracks the global mute/solo would export, each drawn as a line and a name in its track's colour. The Cubase reader already makes a Markers track this way. It reports "Chord track events are not imported" today.

## Proposal

### 1. Decode (Cubase reader)

- Read each `MChordEvent`: position, root, and from `ChordData` the type, tensions and bass note. Build a name in Cubase's own spelling (`Gmaj7/B`, `F#m7b5`, `X`). Read `MScaleEvent` names too.
- Respect the chord track's mute, if it has one.
- **Evidence first:** the fixture series below, with a screenshot of each chord track, so every name can be checked against what Cubase shows.

### 2. Model: an auxiliary "Chords" track

- Each chord becomes a **text meta event** (`FF 01`) holding its name, at its position, on an auxiliary track named "Chords", in one clip. That's the same shape as the Markers track. Text events are standard MIDI: other DAWs ignore them or show them, and our own exports round-trip.
- **How the app knows it's a chord track.** Two options:
  - (a) **A track role field** (`Track.role = 'chords'`): explicit, survives renames, and cheap. It needs session schema 6, done the same way as `source_transpose`. **Recommended.**
  - (b) Recognise it by name ("Chords"): no schema change, but fragile, because a user's own track might be called "Chords".
- **Scale events:** keep them on the same track as text events with a prefix (`Scale: C Major`), or leave them out at first. I'd leave them out until you want them.
- No chord voicing is ever rendered as notes, as agreed.

### 3. Display

What you suggested, in two places:

- **A chord row in the header**, below the marker row, shown only while there are chords, with its own "Show Chords" toggle like Show Markers. Each chord is a **grey rounded box** from its start to the next chord, with the name inside. A box too narrow for its name elides it, then hides it when zoomed far out. Grey keeps chords visibly different from markers, which use the track colour.
- **The Chords track's lane** draws the same boxes instead of the usual text ticks. Muting or soloing the track hides or shows its chords in the header, as markers do now.

### 4. Export

Two choices; **I recommend (a)**:

- (a) **Exported like markers:** the Chords track's text events go into exports and range exports like any auxiliary track, controlled by its export toggle. Reason and Cubase ignore text events, so this is harmless and keeps the chords in the file.
- (b) Never exported (display only).

**Extra export option (user, 2026-11-16): export as block chords.** Because the Chords track is marked as specialised (the role field, option 2a, makes this possible), its export can offer a choice: as text events (above), or as **block chords**, where each chord is written as notes held from its start until the next chord. That would need:

- **A voicing rule:** for example, close position from the root in a chosen octave, with the bass note (the slash part) an octave below; tensions added above. Cubase's own voicings (piano, guitar, basic) are not reproduced; ours would be a simple, predictable default.
- **A channel and velocity:** the track's export channel, and a fixed velocity.
- **"X" chords and gaps** produce silence.
- **A place for the choice:** per track (on the Chords track's header menu), so other tracks are unaffected.

This differs from the earlier decision only in that the user asks for it explicitly at export time; the import still never turns chords into notes.

### 5. Drags and other sources

- **From Cubase:** dragged parts carry MIDI only, and the MIDI export has no chords. If you try dragging chord-track events out of Cubase and it produces a file, we'll see what's in it.
- **Received MIDI files** with chord text events (our own exports, for example) would show up as chords if they land on a Chords track. Recognising other conventions, such as Yamaha XF chord events, could come later.
- **Logic** has a chord track too (secondary priority, see the [desk research](../../investigation/daw-desk-research.md)); this design would serve it.

## Fixtures (Cubase 16, saved as for the c-series)

| # | Content |
|---|---|
| **c34** | Chord track only, one bar each, in order: C, Cm, C7, Cmaj7, Cm7, Cm7b5, Cdim, Caug, Csus4, C/E, C#m, Dbm, and an X (no chord) |
| **c34s** | c34 plus two scale events (C Major, A Minor) |
| **c34m** | c34 with the chord track muted |

Plus a screenshot of each chord track, and a MIDI export of c34 to confirm it carries nothing. Ditty, GA and Beat003vs then serve as real-world checks.

## Steps

1. Decode `ChordData` from c34 and name every chord as Cubase shows it; test against the real projects.
2. Chords track in the Cubase reader (role field, session schema 6).
3. Chord row and lane drawing, with the Show Chords toggle.
4. Export behaviour and tests.
5. Docs and checklist.

Effort: small to medium. Decoding is the unknown; the model and drawing reuse the marker machinery.

## Questions for you

1. **Model:** a track role field (schema 6), or recognise the track by name?
2. **Export:** chords exported as text events like markers, or display only?
3. **Scale events:** show them too, or leave them out at first?
4. **Display:** grey boxes in a chord row under the markers, plus the same boxes on the track lane. Is that what you pictured?
5. **Drags:** can you try dragging a few chord-track events out of Cubase to the Finder and tell me what appears?
