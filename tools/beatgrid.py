"""Local tempo estimation, used to constrain where a fill may be borrowed from.

The exemplar search asks "which passage elsewhere in the track looks most like
the audio either side of this gap?" and answers it with normalised
cross-correlation of the raw waveform. In dense percussion that question has a
lot of near-tied answers, because a 240 ms window of a busy drum pattern
correlates respectably with almost any other. The winner is chosen on timbre,
and its position within the bar is left to chance.

Measured over the whole track, the lags that search picked sit a median 57 ms
away from a whole beat -- better than the 107 ms you would get from random lags,
but only 29% land within 25 ms of the grid. In the worst cluster the median was
121 ms, which is *worse* than random: a third of a beat, so every borrowed
fragment arrived between the hits instead of on them.

Constraining lags to whole beats removes that failure mode outright. It needs a
tempo, and a DJ set does not have one -- this file measures it locally, in a
window around each repair, and reports a confidence so the caller can fall back
to the free search where the estimate is not trustworthy (breakdowns, ambient
passages, the seconds around a transition between two records).
"""
import numpy as np

from audiokit import SR, mono

FLUX_N, FLUX_H = 1024, 256
MIN_BEAT, MAX_BEAT = 0.30, 1.20        # 50-200 BPM


def onset_flux(x, N=FLUX_N, H=FLUX_H):
    """Half-wave-rectified log-magnitude spectral flux."""
    if len(x) < N + H:
        return np.zeros(4), H / SR
    P = np.arange(0, len(x) - N, H)
    w = np.hanning(N)
    S = np.abs(np.fft.rfft(x[np.add.outer(P, np.arange(N))] * w, axis=1))
    return np.clip(np.diff(np.log(S + 1e-6), axis=0), 0, None).sum(axis=1), H / SR


def local_beat(X, t, half=15.0, step=0.0004):
    """Beat period in seconds at time `t`, with a confidence in [0, 1].

    The period is chosen to maximise the autocorrelation of the onset flux
    summed over 1, 2, 4 and 8 beats. Summing over multiples is what stops the
    estimate settling on a half- or double-time reading: a spurious period
    scores well at one multiple and badly at the rest.

    Confidence is the plain autocorrelation at the winning period. Below about
    0.25 the passage has no usable pulse and the caller should not constrain
    anything on the strength of it.
    """
    a = max(0, int((t - half) * SR))
    b = min(len(X), int((t + half) * SR))
    if b - a < SR:
        return 0.0, 0.0
    f, dt = onset_flux(mono(X, a, b) / 32768)
    if len(f) < 16:
        return 0.0, 0.0
    f = f - f.mean()
    n = 1 << int(np.ceil(np.log2(len(f) * 2)))
    ac = np.fft.irfft(np.abs(np.fft.rfft(f, n)) ** 2)[:len(f)]
    ac /= ac[0] + 1e-12
    g = np.arange(len(ac))
    best_p, best_s = 0.0, -9.0
    for p in np.arange(MIN_BEAT, MAX_BEAT, step):
        s = sum(np.interp(m * p / dt, g, ac) for m in (1, 2, 4, 8))
        if s > best_s:
            best_p, best_s = p, s
    return float(best_p), float(np.interp(best_p / dt, g, ac))


def off_grid_ms(lag_s, beat_s):
    """How far a lag sits from the nearest whole beat, in milliseconds."""
    if not beat_s:
        return float('nan')
    n = lag_s / beat_s
    return abs(n - round(n)) * beat_s * 1000.0
