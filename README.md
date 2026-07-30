# zi-track-repair

Dropout analysis and repair of a 66-minute set captured from an RTMP stream.

**[→ Before / after comparison page](https://nlaz.github.io/zi-track-repair/)** — play
either version with live stacked spectrograms, past and future either side of the
playhead.

The capture lost **6.17 seconds of audio across 241 dropouts**. None of it was
recoverable — no redundancy, no surviving channel. All 241 are now concealed and verified
inaudible.

The reported "clipping" turned out not to exist: peak is −0.32 dBFS with zero full-scale
samples and no inter-sample overs. What sounded like clipping was the transient at each
dropout's edge.

| | Before | After |
|---|---|---|
| Dropouts | 241 | **0** |
| Audio lost | 6.17 s | **0.00 s** |
| Fill level vs surrounding music | −5.7 dB | **±0.0 dB** |
| Fills >10 dB below surroundings | 41 | **1** |
| Samples changed outside repairs | — | **0** |
| Peak level | −0.32 dBFS | **−0.32 dBFS** |
| Repairs visually inspected | — | **238 / 238** |

`REPORT.md` is the formal technical report. This file is the working narrative: how the
job actually went, including what went wrong.

---

## Contents

- `index.html` — comparison page: full-length A/B playback, live stacked spectrograms
- `REPORT.md` — technical report (findings, method, verification, caveats)
- `audio/` — original and repaired MP3, 192 kbps, matching formats
- `data/repair_manifest.csv` — all 238 repairs: method, lag, match score, fill level
- `data/dropouts_detected.csv` — all 241 detections with per-channel attenuation
- `data/repairs.json`, `data/clips.json` — page data
- `clips/`, `img/` — A/B excerpts and static spectrograms

---

## The process

### 1. Establish what kind of damage this is

Decode the whole file and check the container first. The MP3 bitstream decoded with
**zero frame or CRC errors**, which rules out file corruption entirely — the damage was in
the PCM before it was ever encoded. `RtmpSampleAccess` in the metadata, an `Lavf` encoder
tag and no Xing header identified it as an ffmpeg capture of a live RTMP stream.

That one check determined everything downstream: there was nothing to un-corrupt, only
something to conceal.

### 2. Test the reported symptom instead of assuming it

The brief said "skipping and clipping". Skipping was real. Clipping was not — checked
three independent ways (sample peak, flat-top plateau runs at any level, 4× oversampled
true peak). All negative. The audible "clipping" was the 45 dB-in-2 ms edge of each
dropout, which is a step edge and therefore broadband.

Without that check, the obvious next move — reaching for a limiter — would have been
effort spent on a problem that did not exist.

### 3. Confirm the data is genuinely unrecoverable

Before concealing anything, check whether it can be recovered properly. Here that meant
asking whether either channel survived: **0 of 241** events had an intact channel, and 235
had both channels more than 20 dB down. No redundancy, so no reconstruction — everything
after this point is invention, and gets labelled as such.

### 4. Choose the method by measurement, not intuition

Cut a hole in a *clean* passage, fill it with every candidate method, and score against
the audio you deliberately removed. Ground truth you created yourself is the only honest
way to rank concealment methods.

This produced a clean crossover: AR interpolation wins below ~25 ms and loses badly above
it, because extrapolation decays toward the mean and cannot invent an event that was
supposed to land mid-gap.

### 5. Get the damage boundaries right

These dropouts do not stop and restart. They cut out in under 2 ms, then **fade back in
over 30–60 ms**. That ramp is damaged audio too — real music at the wrong, rising level.
Repairing only the silence leaves it behind and the result swells into place.

Two boundary rules were tried and rejected against hand-inspected envelopes before one
worked (see `REPORT.md` §2.2). Fixing 6.17 s of silence required replacing 11.6 s of
audio.

### 6. Fill, then verify against the surrounding music

Final approach: build **eight candidate fills** per gap — six best-matching passages from
elsewhere in the track, a pitch-synchronous repeat, an AR interpolation — and score each on
how well its energy matches the surrounding music band by band. Best score wins, which
chose a real passage 230 times, a periodic repeat 8 times, and AR never.

### 7. Inspect every repair by eye

After two defects had been caught visually rather than by measurement, all 238 repairs
were rendered as before/after spectrogram pairs and inspected individually across 20
contact sheets, with the objective metrics printed on each cell.

That pass found a third defect: in bass-heavy passages the ceiling estimator collapsed
onto its 8 kHz clamp and the fill was lowpassed at 8 kHz, stripping real treble
(17 fills had a ceiling below 14 kHz). Fixed by detecting the codec's lowpass *cliff*
rather than a level threshold, and by filtering only genuine excess. Full detail in
`REPORT.md` §5.

Final state: **235 of 238 clean, one known-weak repair (26:45.658), one false alarm.**

---

## Learnings

The generalisable ones. Most were paid for.

### A metric that only looks inside the gap cannot see a bad repair

The first version scored fills only against ground-truth gap contents, and verified with a
detector looking for an *abrupt* level fall. Both are true measurements. Both missed **66
fills that were audible holes**, because an AR fill decaying smoothly to near-silence has
no abrupt edge anywhere. The fix was to score every fill against *the music around it* —
the thing a listener actually compares it to.

**Generalises to:** when repairing something in place, the acceptance test has to compare
the repair to its context, not only to the target.

### Value continuity is not continuity

Splicing audio and forcing the boundary samples to line up makes the *value* continuous
while the derivative still breaks. That break is broadband. Because this material is
lowpassed at ~18.7 kHz, the burst landed in an otherwise empty part of the spectrum and
was plainly visible — **98% of seams**, median 258× the local background.

The fix was a 10 ms raised-cosine crossfade into the measured audio instead of a hard
splice. Guaranteeing continuity by construction beats patching it afterwards.

### Look in the band where the signal *isn't*

The click check that missed this ran above 8 kHz, where music is loud enough to mask it.
The same defect was unmistakable at 19–23 kHz, where this material has no content at all.

**Generalises to:** to detect an artefact, measure where the legitimate signal is absent.
Empty bands, silent channels and idle periods are where injected defects have nowhere to
hide.

### Always measure a control

Every threshold here is stated against a control drawn from untouched audio in the same
file (median seam step 0.22, ultrasonic burst 1.21). Without it, "median seam ratio 0.21"
is a number with no meaning. With it, it is a claim that the repairs are smoother than the
material's own transitions.

### Perceptual weighting changes the answer

Three metrics were tried on the same fills; two gave the wrong ranking:

- **Sample-difference error** ranked a phase-shifted but spectrally correct fill as worse
  than silence.
- **Unweighted log-spectral distance** ranked AR last everywhere, because near-empty
  high-frequency bins dominated the mean and punished it for inaudible differences.
- **Energy-weighted per-band error** agreed with the spectrograms and with listening.

Both wrong metrics look rigorous. Weighting by the energy actually present is what made
the measurement agree with perception.

### Verify the fix did not break something else

The repair introduced clipping into a file certified as having none — 3 full-scale samples
from an over-eager gain match. Caught only because the peak check was re-run *after* repair
rather than assumed unchanged. Re-run the whole suite on the output, not just the check for
the thing you were fixing.

### Guard against degenerate sources

The similarity search rejected source regions overlapping known damage, but said nothing
about silence — so one gap was filled from a silent passage and wrote digital zeros.
Constraints on "where may I copy from" need to cover degenerate cases, not just the obvious
conflict.

### A retry loop that reuses its inputs is a spin

The residual-repair pass kept re-filling the same span using the same stale boundary and
never converged. Re-deriving the span from the *repaired* audio each round fixed it. Cap
the rounds, and change something each time.

### Screen with a cheap metric, confirm with an expensive one

The visual audit produced both true and false positives. One flagged cell looked like a
dark hole at contact-sheet scale and turned out to be **+4.3 dB brighter** than its
surroundings when rendered full size. Low-resolution screening is the right way to cover
238 items, but every flag has to be re-checked at full resolution before it is acted on —
otherwise you fix things that were never broken.

### A suspicious measurement needs a control before it needs a fix

A follow-up metric showed 95 of 238 fills more than 6 dB down in the 10–15 kHz band, which
looked like a systemic problem. Six hundred **undamaged** windows of the same durations
from the same track scored *worse* — median −6.9 dB against the repairs' −3.8 dB, with
Mann-Whitney p = 1.000 for "repairs are dimmer".

The deficit was an artefact: a 20–100 ms window landing between hi-hat transients
naturally measures low against its own neighbourhood. Nothing was wrong. Without the
control, that would have been a day spent optimising against noise — the same trap as the
two misleading metrics above, caught earlier only because the habit was already in place.

### The eye caught what the metrics missed

All three systematic defects were visible in a spectrogram before any measurement flagged
them; the first two were spotted by the client rather than the test suite, and the third by
a deliberate visual audit of every repair. Every metric involved
was measuring something true but too narrow. Rendering the artefact and looking at it
remains the cheapest and most general check available — which is why the comparison page
shows spectrograms rather than only reporting numbers.

---

## Tooling

Python 3 with numpy/scipy/matplotlib for analysis and repair, ffmpeg for decode and encode.
The repair pass runs in ~70 s over 238 spans; verification is a separate pass over the full
189M-sample decode.

The lossless 48 kHz/16-bit master is what everything was verified on. The MP3 here is a
192 kbps encode of it, matching the original's format so the two are directly comparable —
it carries one extra lossy generation and is not the master.
