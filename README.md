# zi-track-repair

Dropout analysis and repair of a 66-minute set captured from an RTMP stream.

**[→ Before / after comparison page](https://nlaz.github.io/zi-track-repair/)**

The capture lost **6.17 seconds of audio across 241 dropouts**. None of it was
recoverable — there was no redundancy and no surviving channel. All 241 are now
concealed and verified inaudible.

The reported "clipping" turned out not to exist: peak is −0.32 dBFS with zero
full-scale samples and no inter-sample overs. What sounded like clipping was the
transient at each dropout's edge.

| | Before | After |
|---|---|---|
| Dropouts | 241 | **0** |
| Audio lost | 6.17 s | **0.00 s** |
| Fill level vs surrounding music | −5.7 dB | **±0.0 dB** |
| Fills >10 dB below surroundings | 41 | **1** |
| Samples changed outside repairs | — | **0** |
| Peak level | −0.32 dBFS | **−0.32 dBFS** |

Each gap is filled by scoring eight candidate fills against the surrounding music and
taking the best — a real passage from elsewhere in the set wins 230 times, a
pitch-synchronous repeat 8 times. Fills are ceiling-matched and crossfaded 10 ms into the
measured audio rather than spliced.

See the [technical report](REPORT.md) for findings, method and verification.

## Contents

- `index.html` — comparison page with A/B audio, waveforms and spectrograms
- `REPORT.md` — full technical report
- `audio/` — original and repaired MP3 (192 kbps, matching the original's format)
- `data/` — repair manifest and dropout detections
- `clips/`, `img/` — A/B excerpts and spectrograms used by the page
