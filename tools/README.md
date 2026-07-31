# tools

The code that produced the repair. Three stages, each runnable on its own, plus a
shared helper module.

```bash
pip install numpy scipy                     # the only dependencies

ffmpeg -i capture.mp3 -c:a pcm_s16le decoded.wav      # 48 kHz 16-bit stereo

python3 tools/detect.py decoded.wav -o spans.json
python3 tools/repair.py decoded.wav spans.json -o repaired.wav -m manifest.csv
python3 tools/verify.py decoded.wav repaired.wav spans.json
```

`verify.py` exits non-zero if any check fails, so it drops straight into CI.

| file | what it does |
|---|---|
| `audiokit.py` | shared: memmapped WAV I/O, envelopes, critical-band energy, onset counting, the two seam measures |
| `detect.py` | two detectors + span shaping → `spans.json` |
| `repair.py` | candidate generation and scoring → repaired WAV + manifest |
| `verify.py` | seven checks, each against a control drawn from the same file |

Everything works on a memmap, so a 66-minute track never loads into RAM.

---

## Why it is shaped this way

Each part of this exists because a simpler version shipped and was wrong. The
docstrings carry the detail; the short version:

**Two detectors, not one.** The edge detector requires the level before the cliff
to exceed −25 dBFS. That guard suppresses false positives in quiet passages, and
in doing so it silently excludes every dropout that lands in one — on the source
track, 70 of 311. A second pass looks for near-silent floors *relative to their
surroundings*, with no absolute loudness requirement.

**A relative test cannot see a fault larger than its window.** A 10.46 s dropout
was missed by both detectors: its own neighbourhood is the same dropout, so
"quiet before, quiet after" reads as a quiet passage. Anything scanning for
anomalies needs a check at a much longer timescale, or it will pass over the
largest problem in the data. `detect.py` does not attempt this — that gap turned
out to be a false start and was handled by trimming.

**Spans are wider than the silence.** Dropouts do not stop and restart; they cut
out in under 2 ms and fade back in over 30–60 ms. That ramp is real music at the
wrong, rising level. Repairing only the silent core leaves it behind.

**Score against the surroundings, not just the gap.** A metric that only looks
inside the gap cannot tell that the fill is 20 dB quieter than the music around
it. That mistake put 66 audible holes into a version that reported zero dropouts
remaining.

**Include a term for *when*, not just *how much*.** Band energy and level are
averages over the fill. Two fills with identical spectra and identical loudness
can place their transients completely differently, which in rhythmic material is
the first thing a listener notices. Hence the onset-density term.

**Crossfade, never splice.** Forcing the boundary samples to line up makes the
value continuous while the derivative still breaks, and that break is broadband.
On lowpassed material it lands in an empty band above the content ceiling, where
it is unmistakable — 98% of seams in one version, invisible to a check that only
looked above 8 kHz.

**Every threshold needs a control.** "Median seam ratio 0.20" is meaningless
alone. Measured against random points in untouched audio from the same file
(0.22), it means the repairs are smoother than the material's own transitions.
Two separate false alarms were caught this way — 95 fills that looked 6 dB down,
and 264 residual regions that looked like damage — both ordinary musical dynamics.

---

## Gotchas

**Span boundaries.** `repair.py` writes the *true* repaired boundary to the
manifest. If you feed `verify.py` a spans file whose starts predate the 2 ms
pre-guard, pass `--pre-guard-ms 2` — otherwise every seam is probed a few
milliseconds inside the fill and reads as a false click. The same applies to
`--guard-ms`, which must cover the pre-guard plus the crossfade or check 1
reports changes outside the repair regions that are not real.

**The ultrasonic check compares medians, not an exceedance count.** With a few
hundred control samples the 99th percentile is the second-highest value and far
too noisy to gate on. The failure it guards against measured 258× the control
median, so a 3× ratio separates it with room to spare.

**AR interpolation is only offered below 40 ms.** It decays toward the mean, so
on long gaps it produces a quiet hole with no sharp edge — invisible to a dropout
detector. In practice the scorer never picks it outright.
