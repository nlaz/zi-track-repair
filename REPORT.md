# Track repair — technical report

**Source:** `1784253717886.mp3` — 65:45 as captured, 48 kHz stereo, 192 kbps CBR MP3
**Delivered:** 64:45 — the first minute is a false start and is trimmed (§9)
**Reported symptom:** "the track is skipping and has clipping artifacts"

**Outcome:** 309 dropouts concealed across 329 repair spans in the delivered track.
The code is in [`tools/`](tools/). The original detector found
241 of them; a later scan found 70 more that it had been built to exclude (§7).
Zero dropouts remain, fills sit level with the surrounding music, and no sample outside
a repair span or its 10 ms crossfade was altered.

> **Revision note.** The first version of this repair shipped with two systematic
> defects — 66 fills that were audible holes, and broadband splice clicks on 98% of
> seams. Both were spotted by eye in the spectrogram, not by the verification suite.
> Section 4 documents what went wrong and why the original checks missed it. A
> subsequent **visual audit of all 238 repairs** (§5) found and fixed a third: fills in
> bass-heavy passages were being lowpassed at 8 kHz and losing real treble. A fourth,
> reported by ear at 41:50–41:53, is documented in §6: some spans stopped short and left
> part of the dropout unrepaired. A fifth, reported from the spectrogram at 2:18, is
> documented in §7 and is the most consequential: **70 dropouts were never detected at
> all**, because the detector required loud music before the cliff.

---

## 1. Findings

### 1.1 The file is not corrupt

The MP3 bitstream decodes with **zero frame errors and zero CRC errors**. That rules out
a whole class of fixes: there is no damaged container to re-parse and no truncated frames
to recover. The defects were baked into the PCM *before* the MP3 encode.

Two metadata fields explain how:

```
TAG:|RtmpSampleAccess=false
TAG:encoder=Lavf61.1.100
```

There is also no Xing/LAME header (ffprobe falls back to `Estimating duration from
bitrate`). Together these say the file is an **ffmpeg capture of a live RTMP stream**,
not a DAW bounce. The damage is network loss recorded faithfully.

### 1.2 The skipping is real — 311 dropouts

| | |
|---|---|
| Confirmed dropouts | **311** |
| — found by the first scan | 241 |
| — found later, after §7 | 70 |
| Total audio lost | **8.52 s** (0.216% of the track) |
| Duration | median 18 ms, mean 25.6 ms, max 134 ms |
| Rate | 4.7 per minute |

> The figures below in this section describe the 241 found by the first scan, since that
> was the population available when the analysis was done. §7 explains why the other 70
> were missing and confirms the same conclusions hold for them.

The signature is unambiguous and non-musical: a **~45 dB collapse in under 2 ms**, then
~80 ms near-silence, then a **gradual 30–60 ms fade back in**. No acoustic event decays
45 dB in 2 ms. The slow fade-in is the decoder's own anti-click ramp on recovery from a
buffer underrun.

The rate **worsens through the session** — 10 dropouts in the first five minutes, rising
to 38–40 per five minutes after the 40-minute mark. A network connection degrading over
the course of a live broadcast.

### 1.3 There is no clipping — at all

This contradicts the reported symptom, so it was tested three independent ways:

| Test | Result |
|---|---|
| Sample peak | **−0.32 dBFS** (L), −0.43 dBFS (R) |
| Samples at full scale | **0** |
| Flat-top plateaus ≥4 samples above 50% FS | **0** (rules out clipping baked in from a clipped source later attenuated) |
| True peak, 4× oversampled | **−0.29 dBTP** |
| Inter-sample overs | **0** |

**What sounds like clipping is the transient at each dropout edge.** A 45 dB cut in 2 ms
is a step edge, and a step edge contains energy at every frequency at once — exactly the
full-height vertical stripe visible in the spectrogram. The click is not *beside* the
gap; the click **is** the gap's edge. Time spent on limiters would have found nothing.

### 1.4 The data is genuinely gone

Before attempting concealment, the one thing that would allow true reconstruction was
checked — a surviving channel:

| | |
|---|---|
| Events with an intact channel (<6 dB down) | **0** |
| Events with both channels >20 dB down | **235 / 241** |
| Median attenuation of the *least*-damaged channel | **−25.8 dB** |

No cross-channel recovery path and no redundancy anywhere in the file. Those 6.17 seconds
were never captured. Everything below is **concealment: plausible invention, not
recovery.**

### 1.5 Not damage — varying lowpass

The content ceiling shifts between ~16 kHz and ~18.7 kHz across sections (e.g. minutes
35–51 versus 51–56). This is a DJ set mixing source tracks with different codec lineages.
It is normal, it was left alone — and it matters for repair, because a fill copied from a
section with a different ceiling looks obviously wrong in a spectrogram.

---

## 2. Approach

### 2.1 Choosing a method by measurement

A **clean** passage (20:08, far from any real dropout) was cut open at four gap widths,
filled by five methods, and each fill scored against the audio deliberately removed — so
there was ground truth. Scoring used per-critical-band energy error, ignoring bands more
than 60 dB below the loudest.

**Per-band energy error in dB, lower is better:**

| Gap | Silence | Linear | Period repeat | AR model | Beat exemplar |
|---|---|---|---|---|---|
| 5 ms | 116.0 | 18.8 | 10.5 | **3.9** | 6.5 |
| 18 ms | 112.3 | 40.5 | 27.7 | 18.4 | **9.0** |
| 50 ms | 109.4 | 44.2 | 23.4 | 34.8 | **18.5** |
| 134 ms | 115.4 | 57.7 | 23.9 | 45.7 | **17.9** |

AR extrapolation is the most faithful method on short gaps and the worst on long ones —
not a flaw in the implementation but a property of extrapolation. A predictor built from
surrounding audio can only continue what is already happening and decays toward the mean
as it reaches further. **That decay is the mechanism behind the holes in section 4.**

#### Two metrics that mislead

- **Waveform (sample-difference) error** ranks period-repeat *worse than leaving silence*
  on the 18 ms gap. The fill is spectrally almost right but phase-shifted, and subtracting
  two correctly-shaped waves that are out of step gives a large number.
- **Unweighted log-spectral distance** ranks the AR model last at every gap length,
  because near-empty high-frequency bins dominate the average and it is punished for
  differences far below audibility. Weighting each band by the energy actually in it
  reverses the verdict.

### 2.2 Repair spans are wider than the silences

Each dropout ends with a 30–60 ms fade-in, so the damaged region extends past the silent
core. That ramp is real music at the wrong, rising level; repairing only the silence
leaves it behind and the result audibly swells into place.

Span boundaries come from the **recovery envelope**: back up to the top of the cliff,
then walk forward along a running maximum of the smoothed envelope until the monotonic
rise stalls (gaining <2 dB over the next 20 ms). Spans within 15 ms of each other merge.

Two earlier criteria were tried and rejected against hand-inspected envelopes:

- *"Recover to within 6 dB of context"* over-extended badly — at 43:45.579 it marked
  327 ms as damaged when the ramp completes in ~20 ms, because the music genuinely sits
  quiet afterwards. It would have replaced healthy audio.
- *"Rise has stalled over 10 ms"* under-extended, tripping on transient dips in a noisy
  envelope (23 ms at 29:32.103, where the ramp visibly runs to ~110 ms).

### 2.3 Candidate scoring, not method-by-length

The final repair does not choose a method from gap length. For every span it builds
**eight candidate fills**:

- the **six best-matching passages** from elsewhere in the track,
- a **pitch-synchronous repeat** of the gap's own neighbours,
- an **AR interpolation** (short gaps only).

Each candidate is scored on how closely its per-band energy matches the surrounding
music, plus a penalty for overall level mismatch and a penalty for energy in bands the
surroundings do not use at all. Lowest score wins.

In practice this selects a real passage from elsewhere in the set **230** times and a
pitch-synchronous repeat **8** times. **AR never wins outright** — which, given the table
in 2.1, is the correct outcome.

Matching uses normalised cross-correlation of the 240 ms either side of the gap against
±10 s of the track, at **sample resolution**, rejecting any source region that overlaps
other damage or is near-silent. Both channels use the same lag, so the stereo image is
preserved.

*(A first implementation used beat detection, which returned 362.7 ms / 165 BPM — likely
a double-or-half error. Direct similarity search makes no tempo assumption and was
substituted. A later check confirmed rhythmic alignment is good: the onset-envelope
correlation between a gap's surroundings and its chosen source averages 0.62.)*

### 2.4 Constraints enforced on every fill

- **Crossfaded, not spliced.** Each fill extends 10 ms past the gap at both ends and
  raised-cosine crossfades into the measured audio. This is the single most important
  change from the first version — see 4.2.
- **Ceiling-matched.** Each fill is lowpassed to the local material's own content ceiling,
  so a passage copied from a higher-bandwidth source cannot introduce content the
  surrounding music does not have.
- **Never silent.** Candidates whose source is near-silent, or which contain runs of
  digital zero, are rejected outright.
- **Bounded.** No fill may exceed the original's peak (31579, −0.32 dBFS).

---

## 3. Results

| Check | Before | After |
|---|---|---|
| Dropouts detected | 311 | **0** |
| Audio lost | 8.52 s | **0.00 s** |
| Fill level vs surrounding music | −5.7 dB | **±0.0 dB** |
| Repairs visually inspected | — | **238 / 238** |
| Residual dips deeper than control p99 | — | **0** |
| Undetected dropouts found and repaired | — | **70** |
| Repair spans | — | **330** |
| Spans re-filled for rhythm match | — | **24** |
| Fills >6 dB below surroundings (±100 ms) | — | **2** |
| Fills >10 dB below surroundings | 41 | **1** |
| Seams with broadband splice burst | — | **1%** |
| Digital-silence runs introduced | — | **0** |
| Samples changed outside repair + crossfade | — | **0** |
| Audio touched | — | 24.90 s (0.631%) |
| Peak level | −0.32 dBFS | **−0.32 dBFS** |
| Full-scale samples | 0 | **0** |
| Seam step vs neighbours, median | — | **0.21** (control 0.22) |
| L/R correlation | 0.9525 | **0.9525** |

**Fill level.** Each fill's RMS against the RMS of the **±100 ms** either side of it,
measured on the final audio. The window matters: an earlier version of the manifest used
±250 ms, which in a track with dynamics this steep made 12 fills look more than 6 dB down
when only 2 are. All 330 rows are now measured uniformly at ±100 ms.

**Seam step.** Each boundary's sample-to-sample step compared against the 99.5th
percentile of steps in the surrounding ±10 ms, excluding the seam. Control points in
untouched audio score a median of 0.22; the repaired seams score 0.21, and none exceeds 2×.

**Broadband splice burst.** Energy from 19–23 kHz within ±5 ms of each seam, relative to
the local median. This material has effectively no content above ~18.7 kHz, so the band
is empty and any splice discontinuity is unmistakable there. Control median is 1.21; the
repaired seams score 1.32, with 1% above the control's 99th percentile.

---

## 4. What went wrong the first time

The first published version passed every check then in place and was still wrong in two
systematic ways. Both were found by looking at spectrograms.

### 4.1 AR fills decayed into holes

**66 of 239 fills were more than 10 dB quieter than the music around them** — 62 of them
AR fills, versus 3 of 137 matched fills. The worst was −27.1 dB. At 26:45.399 the result
was a 169 ms near-silent band, visibly *darker* than the original dropout it replaced.

The mechanism was already documented in section 2.1: AR extrapolation decays toward the
mean. The measurement predicted 45.7 dB error at 134 ms and 101 spans were routed to it
anyway, because the method was chosen by gap length with AR as the fallback whenever a
similarity match scored below 0.50.

**Why verification missed it.** The dropout detector looked for an *abrupt* fall — more
than 32 dB inside one millisecond. An AR fill that fades smoothly into near-silence has
no abrupt edge anywhere, so it passed a detector that reported "241 → 0". The metric used
to choose methods also scored fills only *inside* the gap, never comparing them to the
surrounding music.

**Fix:** candidate scoring against the surrounding spectrum (2.3), which ranks a mediocre
real passage far above a decaying AR fill. Plus an explicit fill-level check in
verification.

### 4.2 Hard splices clicked on 98% of seams

Every fill was written with a hard boundary, made value-continuous by a corrective ramp.
Value continuity is not enough: the derivative still breaks, and because this material is
lowpassed at ~18.7 kHz, the resulting broadband burst lands in an otherwise empty part of
the spectrum. Measured 19–23 kHz, the seams scored a median of **258× the local
background against a control of 1.21 — 98% of them above the control's 99th percentile**.
These are the bright vertical lines visible at the repair boundaries.

**Why verification missed it.** The seam check measured single-sample steps, which the
corrective ramp had made small by construction. A broadband-transient check *was* run,
but over >8 kHz — where the music itself is loud enough to mask the click. The defect
only becomes obvious in the empty band above the material's ceiling.

**Fix:** 10 ms raised-cosine crossfades into the measured audio instead of hard splices,
which brought the median to 1.32 against a control of 1.21.

### 4.3 Two smaller faults found on the way

- **The pitch-synchronous fill clicked once per period.** It was built with
  `x[a - P + (i % P)]`, and the modulo wrap put a discontinuity at every period boundary —
  roughly 20 of them inside a 130 ms fill. Replaced with Hann overlap-add at hop *P*,
  where 50% overlap sums to unity and the repeat is continuous.
- **One fill was copied from silence.** The source-vetting rejected regions overlapping
  known damage but said nothing about silence, so a span at 58:28.975 was filled from a
  silent passage and wrote three runs of digital zero. Now rejected explicitly.

### 4.4 The general lesson

Every one of these defects was visible in a spectrogram before any metric caught it. Each
metric that missed one was measuring something true but too narrow — abrupt falls, not
holes; sample steps, not spectral discontinuity; the inside of the gap, not its
relationship to the music around it. The verification suite now includes a check derived
from each failure.

---

## 5. Visual audit of all 238 repairs

After two defects had been found by eye rather than by measurement, every repair was
rendered as a before/after spectrogram pair (±800 ms, 0–24 kHz, fixed dB scale) and
inspected individually across 20 contact sheets. Objective metrics — fill level, per-band
error, seam burst — were printed on each cell so the visual read could be cross-checked
against numbers.

**Result: 235 of 238 clean. One real defect found, one known-weak repair confirmed, one
false alarm.**

### 5.1 Defect found: fills lowpassed at 8 kHz

Four repairs showed a dark rectangle in the AFTER spectrogram — content cut above a
horizontal line inside the span, where the BEFORE had content. That shape is the
signature of a lowpass, which pointed straight at the ceiling-matching step.

The cause was in `local_ceiling`, which took the highest frequency within 70 dB of the
**spectral peak**. In a bass-heavy passage the peak is the bass, so everything above
8 kHz fell below that threshold and the estimate collapsed onto its 8 kHz clamp. The
fill was then lowpassed at 8 kHz, stripping legitimate treble. **17 fills had a ceiling
below 14 kHz**; three sat at the 8 kHz floor.

Two changes fixed it:

- **Detect the codec cliff, not a level.** The ceiling is now found by locating the
  steepest drop (>20 dB across ~1 kHz) in the smoothed context spectrum above 9 kHz. If
  no cliff exists, no filtering is applied at all.
- **Trim excess only.** The fill is filtered only if its energy above the ceiling exceeds
  the context's by more than 6 dB — so the step can remove foreign brightness but can
  never remove content the fill legitimately shares with its surroundings.

Measured on the affected spans, 8–18 kHz energy relative to context:

| Repair | before fix | after fix |
|---|---|---|
| 30:51.751 | −3.8 dB | **+1.5 dB** |
| 02:00.505 | −4.4 dB | **−1.8 dB** |
| 56:29.060 | −20.4 dB | **+4.3 dB** |

### 5.2 False alarm: the high-frequency "deficit"

A follow-up measurement suggested a wider problem: 95 of 238 fills sat more than 6 dB
below their context in the 10–15 kHz band, 60 of them more than 10 dB down.

A control settled it. Six hundred **undamaged** windows, drawn at the same distribution
of durations from clean parts of the same track and measured the same way, scored a
median of **−6.9 dB with 41% below −10 dB** — worse than the repaired fills at −3.8 dB
and 25%. A Mann-Whitney test on "are repaired fills dimmer than natural windows" returns
**p = 1.000**.

The deficit is an artefact of the metric, not a property of the repairs: a 20–100 ms
window that happens to fall between hi-hat transients naturally measures well below its
own ±150 ms neighbourhood. Without the control this would have been a day spent
optimising against noise.

### 5.3 Confirmed weak: 26:45.658

The one repair known to be poor was confirmed visually and numerically (−13 dB level,
−10.3 dB at 10–18 kHz). Widening the span and re-searching did not improve it; no
comparable passage exists nearby. It remains the single worst fill in the track.

### 5.4 One visual misread, corrected

At contact-sheet scale, 56:29.060 appeared to have a dark block. Rendered at full size it
is **+4.3 dB brighter** than its surroundings — a texture difference from the exemplar,
not a hole. Worth recording: low-resolution visual screening produces false positives as
well as true ones, and every flag was re-checked at full resolution before being acted
on.

---

## 6. Under-repaired spans (reported by ear at 41:50–41:53)

A cluster of four repairs in 2.5 s was audibly glitchy. The fills themselves were fine —
levels within ±1.3 dB, three of four matching well. The fault was the **span boundaries**:
at 41:52.522 the dropout runs about 210 ms but the span covered only 50 ms, leaving
roughly 160 ms of the original dropout untouched immediately after the repair.

### 6.1 Why the verification missed it

The dropout detector fires on a fall of more than **32 dB inside one millisecond**. After
partial repair, the transition from fill into the surviving damage decays over 2–3 ms, so
the steepest single-millisecond step is **−30.5 dB** — just under the threshold. The
residual was 7 dB below its surroundings and plainly visible in an envelope plot, but no
sample pair satisfied the rule.

This is the same failure mode as §4.1 in a new place: a detector tuned to one signature
(an abrupt edge) cannot see damage that presents with a slightly gentler one.

### 6.2 The fix

A **level-based residual scan** was added: for each repair span, look ±400 ms either side
for sustained regions still far below the local reference level.

The threshold came from a control rather than from judgement. Run over 400 pseudo-spans
placed in clean audio, the same criterion produced dips with a median depth of **16.4 dB**
and a 99th percentile of **42.8 dB** — this music simply has deep short dips. Scoring the
real spans against that reference, **23 of 337 dips exceeded the control's p99**; the
other 314 were ordinary musical dynamics.

Repairing only those, and iterating until the scan came back empty, took three rounds and
added **22 repairs totalling 1.67 s**. Regions were excluded from exemplar sourcing as
they were identified, so no fill was copied from still-damaged audio.

| | v6 | v7 |
|---|---|---|
| Residual dips deeper than control p99 | 21 | **0** |
| Repair spans | 238 | **260** |
| Audio touched | 16.75 s | 18.74 s |
| Samples changed outside repairs | 0 | **0** |
| Peak | −0.32 dBFS | **−0.32 dBFS** |

Without the control this would have looked like 264 residual regions totalling 11.4 s,
and "fixing" all of them would have replaced 9.7 s of undamaged music.

---

## 7. Dropouts the detector was built to miss

A gap visible in the spectrogram at 2:18 turned out to be a dropout at **02:19.554** that
appears in neither the 241 detections nor any repair span. It was never detected.

### 7.1 The cause

The detector required the level immediately before the cliff to exceed **−25 dBFS**:

```
if db[i-1] > -25 and db[i] < db[i-1] - 32:
```

That guard was there to stop quiet passages producing false positives. Its side effect is
that **any dropout landing in a quieter section of the music was excluded by
construction** — never counted, never given a span, never repaired. The "241 → 0" reported
in earlier revisions was measured against an inventory that had this hole in it.

### 7.2 Finding them

Dropouts collapse to near-digital-silence while music does not, so the track was rescanned
for regions whose floor reaches near silence *relative to their own surroundings*, with no
absolute loudness requirement. That produced 88 candidates.

Roughly half were not damage. Quiet passages, intros and breakdowns also sit far below a
±2 s sliding reference dominated by adjacent loud music — including **30:41.926**, the
passage identified as musical back in the very first analysis. Rendering the longest
candidates made the split obvious by eye, and a rule was then fitted to match that
judgement:

- floor at or below **−60 dBFS**,
- surroundings at least **40 dB above the floor** on *both* sides,
- surroundings themselves above −30 dBFS (so we are not inside a quiet section),
- duration ≤ 260 ms.

The relative form matters. An absolute "must be loud before and after" gate rejected real
dropouts whose neighbour was itself damaged; requiring the floor to be far below its own
surroundings does not.

**70 accepted, 18 rejected.** A sample spread across the whole track was re-rendered and
every one was a dropout: full-height dark band, envelope collapsing to −50/−90 dBFS, loud
music either side.

### 7.3 The unrecoverability claim, re-checked

Section 1.4 established that no dropout had a surviving channel — but that was measured on
the original 241 only. Re-running it on the 70 newly found events:

| | |
|---|---|
| Events with an essentially intact channel (<6 dB down) | **0 / 70** |
| Events with the least-damaged channel >20 dB down | **69 / 70** |
| Median attenuation of the least-damaged channel | **−53.2 dB** |
| Single-channel dropouts (one side recoverable) | **0** |

Same conclusion: the damage is symmetric across channels and there is no cross-channel
recovery path for these either.

Worth recording *how* that was measured, because the first attempt got it wrong. Taking
RMS across the whole repair span gave a median of −6.9 dB and appeared to show 25 events
with an intact channel — which would have meant 25 repairs could have been genuinely
recovered rather than concealed. That measurement was diluted by the recovery ramp, which
is part of the span but is not silent. Measuring the near-silent core instead gives −53.2
dB and no intact channels.

### 7.4 Result

| | v7 | v8 |
|---|---|---|
| Dropout-shaped deep dips remaining | 70 | **1** |
| Repair spans | 260 | **330** |
| Dropouts concealed | 241 | **311** |
| Audio genuinely lost | 6.17 s | **8.52 s** (measured, not assumed) |
| Audio touched | 18.74 s | 24.90 s |
| Samples changed outside repairs | 0 | **0** |
| Peak / L-R correlation | — | unchanged |

The single remaining dip is **30:41.986**, and it is music: the fall into it is a gradual
250 ms decay rather than a 2 ms cliff, and the waveform shows a run of decaying percussive
hits with widening gaps. It is deliberately left alone.

---

## 8. Rhythm: a fill can match the spectrum and still be wrong

A repair at **00:19.969** was reported as having "a blip of new sound". The fill was not
quiet, not clicky, and not spectrally far off — it passed every check in place. It was
still wrong.

That passage is a dense percussive roll: the 112 ms windows either side each contain
**3 onsets**. The chosen fill contained **2**. In a roll, dropping a hit is an audible
rhythmic hiccup, and the fill also carried a brighter low-frequency element than its
surroundings — together, a blip.

The scoring had no term for this. It compared *how much* energy a candidate had per band
and *how loud* it was overall, both of which are averages over the whole fill. Neither can
see that the energy arrives at the wrong moments.

### 8.1 The added term

Candidates are now also scored on **onset density** — transients per fill, against the mean
of the equal-length windows either side:

```
score = band_error + 1.5 × level_error + 4.0 × |onsets(fill) − onsets(neighbourhood)|
```

Applied to the 47 spans whose fill was at least one onset sparser than its neighbourhood,
re-searching with this term produced a better candidate for 24 of them. **The other 23
were reverted** — the new candidate was kept only where it was measurably closer on
density without being worse on level.

| on the 24 accepted spans | before | after |
|---|---|---|
| Mean onset-density error | 1.35 | **0.27** |
| Mean level error | 2.4 dB | **1.5 dB** |

Across all 330 spans, mean absolute level error moved 1.80 → 1.76 dB, and spans more than
6 dB *too loud* fell from 6 to 5. The reported span went from 2 onsets to 3, matching its
neighbourhood exactly.

### 8.2 Why this was invisible

Every metric in the suite up to this point was an average over the fill: band energy,
RMS level, spectral score. An average is blind to arrangement. Two fills with identical
band energies and identical loudness can differ by having their transients in completely
different places — which is precisely what a listener notices first in rhythmic material.

---

## 9. The false start, and the one gap that could not be concealed

The capture does not begin with the set. It begins with roughly 49 seconds of music,
then **10.46 seconds of dead air** (00:49.46 – 00:59.92), and then the set proper starts
at **01:00.012**. The performer restarted.

### 9.1 What the dead section is

| | |
|---|---|
| Duration | **10.46 s** |
| Level in the core | rms **−75.5 dBFS**, peak −54.1 dBFS |
| Music either side | rms ≈ −14 dBFS, peak ≈ −1.4 dBFS |
| Spectrum | flat across 200 Hz – 10 kHz — a bare noise floor, no musical content |
| Correlation, 4 s before vs 4 s after | **−0.03** (unrelated material) |

It is 61 dB below the surrounding music and constant across all ten seconds, so it is
neither a fade nor a filtered breakdown. It is a total stream loss.

### 9.2 Why it was missed by every earlier scan

This is the fourth distinct way the detection missed something, and the most instructive:

- The **edge detector** caps a dropout's recovery search and never considered a candidate
  of this length.
- The **floor detector** found its edges, but the gate rejected them for having
  "quiet music before" and "quiet music after" — because the neighbourhood of a point
  inside a ten-second dropout *is itself the same dropout*. A relative test is blind to a
  hole larger than the window it compares against.
- The duration gate (`≤ 260 ms`) excluded it explicitly.

A long enough fault stops looking like a fault and starts looking like context.

### 9.3 Why it is not concealed

10.46 s is roughly four bars. Every concealment method here works by borrowing real audio
from elsewhere in the set, which is inaudible at 20–100 ms and obvious at four bars — the
listener simply hears a passage twice. Concealment does not scale to this.

### 9.4 What was done instead

Both files are trimmed at exactly **60.000 s**, so the delivered track begins at the
restart. The trim point sits on the noise floor 12 ms before the first transient, so the
attack is intact and there is no click; a 3 ms fade guards the join.

| | as captured | delivered |
|---|---|---|
| Duration | 65:45.55 | **64:45.55** |
| Dropouts concealed | 311 | **309** |
| Repair spans | 330 | **329** |

The two dropped repairs (00:19.969 and 00:41.305) fell inside the trimmed minute. All
remaining timecodes in the manifest and on the review page are relative to the delivered
track, not the original capture.

---

## 10. The 38:19 cluster: fills borrowed from the wrong point in the bar

Reported by ear: *"starting at 38:19 there's a repeated back-to-back series of repairs…
the spectrum looks like it creates new patterns that didn't match the pattern."*

That is an accurate description of the defect, and of its cause.

### 10.1 Why this stretch and not another

38:15.4–38:52.5 holds **17 dropouts in 42 seconds** — about five times the track's average
density. 3.5% of that passage is invented audio, against 0.48% overall. Any weakness in
the fills is concentrated there, which is why it is the passage a listener notices.

The spans themselves are not the problem. Each one matches the measured damage extent to
within a millisecond, no dropout in the window went undetected, and no residual tail
survives past a span end (median 0 ms, against 0 ms for clean-audio controls, p = 0.21).

### 10.2 The exemplar came from the wrong beat

The passage runs at **145.14 BPM** — a 413.4 ms beat, stable to under a millisecond
across every 20 s window from 37:40 to 39:30. Measuring each fill's exemplar lag against
that grid:

| | median distance from a whole beat |
|---|---|
| Lags in this cluster | **121 ms** |
| A quarter-beat — what random lags would give | 103 ms |
| Lags across the whole track | 57 ms |

In the cluster the chosen lags were *worse than random*. Half a dozen sat within 20 ms of
a half-beat, meaning the borrowed fragment arrived precisely between the hits rather than
on them. That is what "creates new patterns" sounds like, and what it looks like on a
spectrogram: an inserted double hit at 38:33.2–38:33.4, a new transient at 38:49.4 and
again at 38:50.3, a dark hole where the pattern expects a hit at 38:37.3.

The cause is the ranking function. `top_lags` scores candidates by normalised
cross-correlation of the 240 ms flanking the gap. In dense percussion that measure has
many near-ties — a busy drum window correlates respectably with almost any other — so it
settles on timbre and leaves the position within the bar to chance.

### 10.3 The failure is specific to real dropouts

Constructing synthetic gaps and repairing them, the same free search behaves *well*:

| gaps | n | median off-beat | within 25 ms |
|---|---|---|---|
| Synthetic, cut from clean audio | 120 | 25 ms | 50% |
| Real dropouts | 270 | **58 ms** | 29% |

Mann-Whitney p = 1.2 × 10⁻⁴. Something about a real dropout's flanks degrades the match
in a way that deleting a window does not.

### 10.4 Two ground-truth tests that could not settle it

Because concealment has no ground truth, the natural check is to damage known-good audio
and compare the fill against what was really there. That was run twice:

1. **Windows cut from clean audio** (44 gaps, matched length distribution). Free search
   vs beat-grid: log-spectral distance 1.39 vs 1.42 dB, onset correlation 0.824 vs 0.840,
   p = 0.97 and 0.40.
2. **The dropout shape simulated** — a 1.5 ms collapse to −70 dBFS, a hold, then a
   30–60 ms raised-cosine recovery — with spans derived by the production detector
   (48 events). LSD 2.06 vs 2.07 dB, p = 0.39.

Neither result is evidence that beat alignment does not help, because in both the free
search *already* chose near-grid lags — 35 ms and 9 ms respectively. The two policies were
choosing the same exemplars, so the comparison had nothing to measure. **These tests are
uninformative, not negative**, and the reason is the finding in §10.3: the synthetic
damage never reproduced the condition under which the free search goes wrong.

This is recorded rather than quietly dropped because the honest state of the evidence is:
the defect is measured and visible, the fix removes it, and a controlled test of the fix
in isolation could not be constructed.

### 10.5 The fix

Exemplar lags are restricted to whole multiples of the **local** beat, then refined ±25 ms
to recover sample alignment and absorb tempo drift. A DJ set has no single tempo, so the
beat is measured per span (`tools/beatgrid.py`) from the autocorrelation of the onset
flux, summed over 1, 2, 4 and 8 beats so the estimate cannot settle on a half- or
double-time reading. Where that estimate is not confident — breakdowns, ambient passages,
the seconds around a transition — the search is left free.

Applied to the 86 spans that were demonstrably off-grid or newly merged:

| | before | after |
|---|---|---|
| Off-beat distance, re-filled spans | 154 ms | **11 ms** |
| Off-beat distance, whole track | 57 ms | **23 ms** |
| Exemplar lags within 25 ms of the beat | 29% | **55%** |
| Onset-pattern agreement in the cluster | 0.14 | **0.26** |

The last row is measured against the same passage one bar either side. 0.26 is exactly
the median that *undamaged* audio in this passage scores — the fills now sit in the bar
the way the surrounding music does. (An earlier draft of this compared against 0.51, the
figure for the whole excerpt; that was the wrong target, drawn from a more repetitive
later section.)

### 10.6 A second, unrelated defect found on the way

Checking seams for this work turned up **four splice clicks in the shipped version** that
every whole-file check had passed: 112×, 112×, 2786× and 4282× the local 19–23 kHz norm,
against a control maximum of 15×. At 35:59.941 the waveform stepped 20206 counts where the
original moves 322.

The cause is span spacing. `apply_fill` crossfades 10 ms into the audio either side of a
span; where the next span begins less than 20 ms after the previous one ends, the second
repair blends into and overwrites the first one's tail fade, producing a discontinuity
neither fill contains alone. Eight span pairs were that close — the span list had
accumulated across several detection passes and was never re-merged, and `detect.py`
merged at 15 ms, narrower than the crossfade it has to protect.

Those eight are now repaired as single spans (**329 spans → 321**, same 309 dropouts), and
two tools changed:

- `detect.py` merges at 20 ms, tied to twice `XFADE`.
- `verify.py` gained a per-seam ceiling. The existing ultrasonic check compares medians —
  robust, and the right test for a systemic fault — but a median cannot see four outliers
  among 642 seams. It moved from 1.58 to 1.58 while four audible clicks sat in the file.

### 10.7 A 24 ms A/B misalignment on the review page, fixed

Re-encoding the repaired MP3 exposed a separate problem in the page. It seeks by byte
offset — frame index × 576 bytes, plus a per-file header offset — because that is the only
way to decode a 24 s window out of a 93 MB file over HTTP range requests. The original
capture carries one more leading frame than a fresh encode does, so at the same nominal
time the two files decoded audio 24 ms apart: the stacked spectrograms did not line up, and
neither did the audio when switching between versions.

Measured against the lossless masters, the before file was reading 36 ms early and the
after file 12 ms. Advancing the before file's offset by one frame (44 → 620 bytes) brings
them into exact agreement and cuts the absolute error to 12 ms. Confirmed in the browser:
cross-correlating the two decoded envelopes over the same window now returns a lag of 0.

### 10.8 Also checked, and not the cause

**A skip in the timeline.** If the capture had dropped samples rather than muting, the
music would resume at a different point in the bar and no exemplar could match both sides
of a gap. Measured across 247 dropouts, the beat-phase step is 51 ms — *smaller* than the
98 ms measured across 494 clean boundaries. The capture mutes; it does not lose musical
time, so filling in place is correct.

**Under-covered spans, undetected dropouts, residual tails.** All three were checked
across the window and came back clean (§10.1).

---

## 11. Caveats

**The matched fills are not what was played.** 305 of 321 repairs contain real audio
lifted from elsewhere in the set (the other 16 are pitch-synchronous repeats of their own
neighbours). They are musically plausible, spectrally continuous and now placed on the
beat, but they are inventions. For a commercial release, spot-check the longest by ear:
**43:11.730** (343 ms), **40:52.518** (225 ms), **25:45.395** (175 ms), **42:01.180**
(174 ms). The first two are merged spans — each conceals two dropouts a few milliseconds
apart, so they are the longest continuous stretches of invented audio in the file.

**One span has no good answer.** 25:45.654, a 26 ms gap, sits 13.5 dB below its
neighbours because no comparable passage exists nearby; widening the span and re-searching
did not improve it. It is the only fill more than 10 dB down.

**A re-capture beats all of this.** This is a stream capture, so the performer may hold a
local recording of the same set. If one exists it is strictly better than any
concealment — worth asking before treating this as final.

**The published MP3 is a second encode.** Repair and verification were done on a lossless
48 kHz/16-bit master. The 192 kbps MP3 here matches the original's format so the two are
directly comparable, but carries one extra lossy generation. The lossless master is
available on request; it was omitted here for size.

---

## 12. Files

| File | Description |
|---|---|
| `audio/1784253717886.mp3` | Original capture, unmodified |
| `audio/1784253717886_repaired.mp3` | Repaired, 192 kbps |
| `data/repair_manifest.csv` | All 321 repairs: timecode, span, how found, method, lag, match score, fill level, local BPM, distance off the beat, spans merged, whether re-filled |
| `data/dropouts_detected.csv` | The original 241 detections with per-channel attenuation |
| `index.html` | Before/after comparison page with A/B audio |
| `tools/` | Detection, repair and verification code, runnable standalone |
