# Track repair — technical report

**Source:** `1784253717886.mp3` — 65:45, 48 kHz stereo, 192 kbps CBR MP3, 94.7 MB
**Reported symptom:** "the track is skipping and has clipping artifacts"

**Outcome:** 311 dropouts concealed across 330 repair spans. The original detector found
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
| Fills >10 dB below surroundings | 41 | **1** |
| Seams with broadband splice burst | — | **1%** |
| Digital-silence runs introduced | — | **0** |
| Samples changed outside repair + crossfade | — | **0** |
| Audio touched | — | 24.90 s (0.631%) |
| Peak level | −0.32 dBFS | **−0.32 dBFS** |
| Full-scale samples | 0 | **0** |
| Seam step vs neighbours, median | — | **0.21** (control 0.22) |
| L/R correlation | 0.9525 | **0.9525** |

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

## 8. Caveats

**The matched fills are not what was played.** 230 of 238 repairs contain real audio
lifted from elsewhere in the set. They are musically plausible and spectrally continuous,
but they are inventions. For a commercial release, spot-check the longest by ear:
**26:45.399** (172 ms), **44:11.734** (159 ms), **41:53.245** (141 ms), **12:02.938**
(150 ms).

**One span has no good answer.** 26:45.658, a 20 ms gap, sits 12.7 dB below its
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

## 9. Files

| File | Description |
|---|---|
| `audio/1784253717886.mp3` | Original capture, unmodified |
| `audio/1784253717886_repaired.mp3` | Repaired, 192 kbps |
| `data/repair_manifest.csv` | All 238 repairs: timecode, span, method, lag, match score, spectral score, fill level, crossfade |
| `data/dropouts_detected.csv` | All 241 detections with per-channel attenuation |
| `index.html` | Before/after comparison page with A/B audio |
