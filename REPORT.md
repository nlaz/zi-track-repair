# Track repair — technical report

**Source:** `1784253717886.mp3` — 65:45, 48 kHz stereo, 192 kbps CBR MP3, 94.7 MB
**Reported symptom:** "the track is skipping and has clipping artifacts"

**Outcome:** 241 dropouts (6.17 s of missing audio) concealed across 239 repair spans.
Zero dropouts remain. Zero samples outside the repair spans were altered.

---

## 1. Findings

### 1.1 The file is not corrupt

The MP3 bitstream decodes with **zero frame errors and zero CRC errors**. This is the
first thing worth establishing, because it rules out a whole class of fixes: there is no
damaged container to re-parse, no truncated frames to recover. The defects were baked
into the PCM *before* the MP3 encode.

Two metadata fields explain how:

```
TAG:|RtmpSampleAccess=false
TAG:encoder=Lavf61.1.100
```

There is also no Xing/LAME header (ffprobe falls back to `Estimating duration from
bitrate`). Together these say the file is an **ffmpeg capture of a live RTMP stream**,
not a DAW bounce. The damage is network loss recorded faithfully.

### 1.2 The skipping is real — 241 dropouts

| | |
|---|---|
| Confirmed dropouts | **241** |
| Total audio lost | **6.17 s** (0.156% of the track) |
| Duration | median 18 ms, mean 25.6 ms, max 134 ms |
| Rate | 3.7 per minute |

The signature is unambiguous and non-musical: a **~45 dB collapse in under 2 ms**,
then ~80 ms near-silence, then a **gradual 30–60 ms fade back in**. No acoustic event
decays 45 dB in 2 ms. The slow fade-in is the decoder's own anti-click ramp on recovery
from a buffer underrun.

The rate **worsens through the session** — 10 dropouts in the first five minutes, rising
to 38–40 per five minutes after the 40-minute mark. That is a network connection
degrading over the course of a live broadcast.

### 1.3 There is no clipping — at all

This contradicts the reported symptom, so it was tested three independent ways:

| Test | Result |
|---|---|
| Sample peak | **−0.32 dBFS** (L), −0.43 dBFS (R) |
| Samples at full scale | **0** |
| Flat-top plateaus ≥4 samples above 50% FS | **0** (rules out clipping baked in from a clipped source that was later attenuated) |
| True peak, 4× oversampled | **−0.29 dBTP** |
| Inter-sample overs | **0** |

There is no clipping by any measure. **What sounds like clipping is the transient at
each dropout edge.** A 45 dB cut in 2 ms is a step edge, and a step edge contains energy
at every frequency simultaneously — which is exactly the full-height vertical stripe
visible in the spectrogram. The click is not *beside* the gap; the click **is** the
gap's edge. Time spent on limiters or gain-staging would have found nothing.

### 1.4 The data is genuinely gone

Before attempting concealment, the one thing that would have allowed true
reconstruction was checked — a surviving channel:

| | |
|---|---|
| Events with an intact channel (<6 dB down) | **0** |
| Events with both channels >20 dB down | **235 / 241** |
| Median attenuation of the *least*-damaged channel | **−25.8 dB** |

There is no cross-channel recovery path and no redundancy anywhere in the file. Those
6.17 seconds were never captured and cannot be restored. Everything below is
**concealment: plausible invention, not recovery.**

### 1.5 Not damage — varying lowpass

The spectrogram shows the content ceiling shifting between ~16 kHz and ~18.7 kHz across
sections (e.g. minutes 35–51 versus 51–56). This is a DJ set mixing source tracks with
different codec lineages. It is normal and was left alone.

---

## 2. Approach

### 2.1 Choosing a method by measurement

Rather than assume which concealment technique to use, a **clean** passage (20:08, far
from any real dropout) was cut open at four gap widths, filled by five methods, and each
fill scored against the audio deliberately removed — so there was ground truth.

Scoring used per-critical-band energy error, ignoring bands more than 60 dB below the
loudest, which approximates what hearing is sensitive to.

**Per-band energy error in dB, lower is better:**

| Gap | Silence | Linear | Period repeat | AR model | Beat exemplar |
|---|---|---|---|---|---|
| 5 ms | 116.0 | 18.8 | 10.5 | **3.9** | 6.5 |
| 18 ms | 112.3 | 40.5 | 27.7 | 18.4 | **9.0** |
| 50 ms | 109.4 | 44.2 | 23.4 | 34.8 | **18.5** |
| 134 ms | 115.4 | 57.7 | 23.9 | 45.7 | **17.9** |

The result is a clean **crossover at roughly 25 ms**. AR extrapolation is the most
faithful method on short gaps and falls behind on long ones — not a flaw in the
implementation but a property of extrapolation. A predictor built from surrounding audio
can only continue what is already happening and decays toward the mean as it reaches
further; it cannot invent a snare hit that was meant to land mid-gap. Copying a real
passage can.

#### Two metrics that mislead

Both were tried first and both gave the wrong answer:

- **Waveform (sample-difference) error** ranks period-repeat *worse than leaving
  silence* on the 18 ms gap. The fill is spectrally almost right but phase-shifted, and
  subtracting two correctly-shaped waves that are out of step produces a large number.
- **Unweighted log-spectral distance** ranks the AR model last at every gap length,
  because near-empty high-frequency bins dominate the average and it is punished for
  differences far below audibility. Weighting each band by the energy actually in it
  reverses the verdict completely.

Concealment has to be judged by audible energy, then by ear.

### 2.2 Repair spans are wider than the silences

Because each dropout ends with a 30–60 ms fade-in, the damaged region extends well past
the silent core. That ramp is real music at the wrong, rising level. Repairing only the
silence leaves it behind and the result audibly swells into place.

Span boundaries were therefore derived from the **recovery envelope**: back up to the
top of the cliff, then walk forward along a running maximum of the smoothed envelope
until the monotonic rise stalls (gaining <2 dB over the next 20 ms). Spans within 15 ms
of each other were merged.

This is why **11.59 s of audio was replaced to fix 6.17 s of silence**.

Two earlier criteria were tried and rejected against hand-inspected envelopes:

- *"Recover to within 6 dB of context"* over-extended badly — at 43:45.579 it marked
  327 ms as damaged when the ramp completes in ~20 ms, because the music genuinely sits
  quiet for 300 ms afterwards. It would have replaced healthy audio.
- *"Rise has stalled over 10 ms"* under-extended, tripping on transient dips in a noisy
  envelope (23 ms at 29:32.103, where the ramp visibly runs to ~110 ms).

### 2.3 The two fills

**Below 25 ms — 102 spans — autoregressive interpolation.** Janssen's method: fit an
order-128 AR model to 6,000 samples of context either side, then solve the least-squares
system for the missing samples that best continue it from both directions, two
refinement passes.

**At or above 25 ms — 137 spans — similarity-matched exemplar.** The gap is filled with
the best-matching passage elsewhere in the track.

A first implementation used beat detection, which returned 362.7 ms (165 BPM) — likely a
double/half error. It was replaced with a **direct similarity search**: normalised
cross-correlation of the 120 ms of measured audio either side of the gap against ±8 s of
the track, rejecting any candidate whose source region overlaps another damaged span.
This makes no assumption about tempo. Matches averaged **ncc 0.68** (minimum 0.50) at
lags of 1.7–7.2 s. Where no candidate reached 0.50, the span fell back to AR.

Both channels use the same lag so the stereo image is preserved; the exemplar is
gain-matched to the surrounding context.

### 2.4 Constraints enforced on every fill

- **Contained.** Fills are written only inside the span. Edge blending happens *inside*
  the gap against a pitch-period continuation of the neighbours, so no measured sample
  is ever altered.
- **Continuous.** Both seams are forced onto a slope-limited extrapolation of the
  adjacent measured samples, with the correction decaying over ≤5 ms so the middle of
  the fill is untouched.
- **Bounded.** No fill may exceed the original file's peak (31579, −0.32 dBFS).

---

## 3. Results

| Check | Before | After |
|---|---|---|
| Dropouts detected | 241 | **0** |
| Audio lost | 6.17 s | **0.00 s** |
| Samples changed outside repair spans | — | **0** |
| Audio replaced | — | 11.59 s (0.294%) |
| Peak level | −0.32 dBFS | **−0.32 dBFS** |
| Full-scale samples | 0 | **0** |
| Seam step vs neighbours, median | — | **0.21** |
| Seam step vs neighbours, worst | — | **1.08** |
| L/R correlation | 0.9525 | **0.9525** |

**Seam test.** Each repair boundary's sample-to-sample step was compared against the
99.5th percentile of steps in the surrounding ±10 ms, excluding the seam itself. A
control of 6,000 random points in untouched audio scored a median of 0.23 and a worst
case of 1.69. The repaired seams score a median of **0.21** and a worst case of
**1.08** — smoother than naturally occurring transitions. **None of the 956 seams
exceeds 2×.**

### 3.1 Three defects the verification caught

Each of these passed a plausible-looking earlier check and would otherwise have shipped:

1. **Clipping was introduced** — 3 full-scale samples, into a file certified as having
   none. The exemplar gain-match could push a fill past full scale. Fixed with a hard
   ceiling at the original peak.

2. **Clicks at 32% of seams.** The first version left boundary steps up to **22.8×** the
   local norm, where natural audio never exceeds 2×. The cause was not the crossfade: the
   span *starts* were a sample or two late, leaving already-collapsing samples classed as
   measured. Linear extrapolation from a collapsing edge produced anchors like −8253 next
   to a real value of 968. Fixed by widening span starts 2 ms to swallow the cliff onset
   and slope-limiting the anchor.

   Note that the error metric could not see this: it scored only *inside* the gap, and the
   defect lived exactly at the boundary.

3. **One span under-measured** (31 ms against a true 101 ms), whose exemplar was itself a
   decaying passage despite a 0.677 match score. The retry pass kept reusing the stale
   boundary and could not converge. Fixed by re-deriving spans from the *repaired* audio
   and iterating to convergence.

---

## 4. Caveats

**The exemplar fills are not what was played.** 137 of the 239 repairs contain real audio
lifted from elsewhere in the set. They are musically plausible and spectrally continuous,
but they are inventions. For a commercial release, spot-check the longest by ear:
**26:45.399** (169 ms), **44:11.734** (156 ms), **43:01.952** (149 ms), **12:02.938**
(147 ms).

**A re-capture beats all of this.** This is a stream capture, so the performer may hold a
local recording of the same set. If one exists it is strictly better than any
concealment — worth asking before treating this as final.

**The published MP3 is a second encode.** The repair was performed and verified on a
lossless 48 kHz/16-bit master. The 192 kbps MP3 here matches the original's format so the
two are directly comparable, but it carries one additional lossy generation. The lossless
master is available on request; it was omitted here for size.

---

## 5. Files

| File | Description |
|---|---|
| `audio/1784253717886.mp3` | Original capture, unmodified |
| `audio/1784253717886_repaired.mp3` | Repaired, 192 kbps |
| `data/repair_manifest.csv` | All 239 repairs: timecode, span, method, exemplar lag, match score |
| `data/dropouts_detected.csv` | All 241 detections with per-channel attenuation |
| `index.html` | Before/after comparison page with A/B audio |
