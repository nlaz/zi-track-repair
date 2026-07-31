#!/usr/bin/env python3
"""Conceal dropouts by scoring candidate fills against the surrounding music.

    python3 tools/repair.py decoded.wav spans.json -o repaired.wav -m manifest.csv

Nothing here recovers lost audio; it invents audio convincing enough that the seam
disappears. For each span it builds candidates —

  * the six best-matching passages elsewhere in the track (sample-accurate
    normalised cross-correlation of the 240 ms either side), searched either
    freely over ±10 s or — by default — only at whole multiples of the local
    beat. See `top_lags`: left free, that search answers "which passage sounds
    most like this one", which in dense percussion is decided by timbre and
    leaves the position within the bar to chance,
  * a pitch-synchronous repeat of the span's own neighbours (Hann overlap-add at
    hop P; a naive `x[a-P + i%P]` puts a discontinuity at every period),
  * an autoregressive interpolation (Janssen, order 128) for short spans,

— and scores each on how well it matches its surroundings:

    band_error + 1.5·level_error + 4.0·rhythm_error + 0.25·excess_above_ceiling

The rhythm term matters more than it looks. Band energy and level are averages
over the whole fill, and an average cannot see that the energy arrives at the
wrong moments. Without it, a fill can match the spectrum exactly and still drop a
hit out of a percussive roll.

Every fill is then ceiling-matched, crossfaded 10 ms into the measured audio
rather than spliced, and capped so it can never exceed the original's peak.
"""
import argparse
import csv
import json
import shutil
import sys

import numpy as np
import scipy.sparse as sp
from scipy.signal import firwin, filtfilt
from scipy.sparse.linalg import spsolve

sys.path.insert(0, __file__.rsplit('/', 1)[0])
from audiokit import (SR, load, load_rw, mono, rms, fmt, band_energy,
                      band_error_db, onset_count)
from beatgrid import local_beat, off_grid_ms

CEIL_DEFAULT = 32767
PAD = 12000
XFADE = int(0.010 * SR)
CTX = int(0.10 * SR)
CTX_WIDE = int(0.25 * SR)
MINLAG, MAXLAG = int(0.25 * SR), int(10.0 * SR)


# ------------------------------------------------------------- primitives
def cosw(n):
    return 0.5 * (1.0 - np.cos(np.pi * np.arange(n) / max(n - 1, 1)))


def levinson(r, p):
    a = np.zeros(p + 1); a[0] = 1.0; e = r[0]
    for i in range(1, p + 1):
        acc = r[i] + (np.dot(a[1:i], r[i - 1:0:-1]) if i > 1 else 0.0)
        k = -acc / e if e > 1e-14 else 0.0
        an = a.copy()
        for j in range(1, i):
            an[j] = a[j] + k * a[i - j]
        an[i] = k; a = an; e *= (1 - k * k)
        if e <= 1e-14:
            break
    return a


def ar_coeffs(ctx, p):
    s = ctx - ctx.mean()
    n = 1 << int(np.ceil(np.log2(max(len(s), 2) * 2)))
    F = np.fft.rfft(s, n)
    r = np.fft.irfft(np.abs(F) ** 2)[:p + 1]
    r = r / (r[0] + 1e-18); r[0] += 1e-6
    return levinson(r, p)


def janssen(x, g0, g1, p=128, ctxn=6000, iters=2):
    """Least-squares AR interpolation. Best on short gaps; decays toward the mean
    on long ones, which is how it produces silent holes if used too far."""
    y = x.copy(); G = g1 - g0
    a0, b1 = max(0, g0 - ctxn), min(len(x), g1 + ctxn)
    y[g0:g1] = np.linspace(x[g0 - 1], x[g1], G)
    p = int(min(p, max(16, (g0 - a0 + b1 - g1) // 8)))
    for _ in range(iters):
        fr = y[a0:b1].copy()
        coef = ar_coeffs(np.r_[x[a0:g0], x[g1:b1]], p)[::-1]
        M = len(fr) - p
        if M <= p:
            return y
        rows = np.repeat(np.arange(M), p + 1)
        cols = (np.arange(M)[:, None] + np.arange(p + 1)[None, :]).ravel()
        A = sp.csc_matrix((np.tile(coef, M), (rows, cols)), shape=(M, len(fr)))
        gi = np.arange(g0 - a0, g1 - a0)
        m = np.zeros(len(fr), bool); m[gi] = True
        AU, AK = A[:, m], A[:, ~m]
        Mm = (AU.T @ AU).tocsc() + sp.eye(int(m.sum()), format='csc') * 1e-9
        fr[gi] = spsolve(Mm, -(AU.T @ (AK @ fr[~m])))
        y[a0:b1] = fr
    return y


def period(ctx, lo=40, hi=1000):
    s = ctx - ctx.mean()
    n = 1 << int(np.ceil(np.log2(max(len(s), 2) * 2)))
    F = np.fft.rfft(s, n)
    ac = np.fft.irfft(np.abs(F) ** 2)[:len(s)]
    ac /= ac[0] + 1e-18
    a, b = int(SR / hi), min(int(SR / lo), len(ac) - 1)
    return a + int(np.argmax(ac[a:b])) if b > a else 256


def oa_extend(tail, P, L):
    """Hann overlap-add at hop P: 50% overlap sums to unity, so the repeat is
    continuous. A modulo wrap would click once per period."""
    P = max(8, int(P))
    g = tail[-2 * P:]
    if len(g) < 2 * P:
        return None
    grain = g * np.hanning(2 * P)
    out = np.zeros(L + 4 * P)
    for k in range(L // P + 4):
        o = k * P
        if o + 2 * P > len(out):
            break
        out[o:o + 2 * P] += grain
    return out[P:P + L]


def ncc(tmpl, region):
    n, m = len(tmpl), len(region)
    if m < n:
        return None
    t = tmpl - tmpl.mean()
    tn = np.sqrt((t ** 2).sum()) + 1e-9
    nf = 1 << int(np.ceil(np.log2(m + n)))
    num = np.fft.irfft(np.fft.rfft(region, nf) * np.conj(np.fft.rfft(t, nf)), nf)[:m - n + 1]
    c1 = np.cumsum(np.insert(region, 0, 0))
    c2 = np.cumsum(np.insert(region ** 2, 0, 0))
    s = c1[n:] - c1[:-n]
    ss = c2[n:] - c2[:-n]
    return num / ((np.sqrt(np.maximum(ss - s * s / n, 0)) + 1e-9) * tn)


# ------------------------------------------------------------ ceiling match
def ctx_spectrum(SRC, g0, g1):
    m = np.r_[SRC[g0 - CTX_WIDE:g0].mean(axis=1),
              SRC[g1:g1 + CTX_WIDE].mean(axis=1)].astype(np.float64) / 32768
    n = 4096
    if len(m) < n:
        return None, None
    w = np.hanning(n); acc = np.zeros(n // 2 + 1); c = 0
    for p in range(0, len(m) - n, n // 2):
        acc += np.abs(np.fft.rfft(m[p:p + n] * w)) ** 2; c += 1
    return np.fft.rfftfreq(n, 1 / SR), acc / max(c, 1) + 1e-18


def local_ceiling(SRC, g0, g1):
    """Locate the codec lowpass CLIFF, not a level threshold.

    Taking the highest bin within 70 dB of the spectral *peak* collapses to the
    floor in bass-heavy passages — the peak is the bass — and lowpasses the fill
    at 8 kHz, stripping real treble.
    """
    f, P = ctx_spectrum(SRC, g0, g1)
    if f is None:
        return 23000.0
    db = 10 * np.log10(P)
    k = max(3, int(200 / (f[1] - f[0])))
    sm = np.convolve(db, np.ones(k) / k, mode='same')
    lo, hi = np.searchsorted(f, 9000), np.searchsorted(f, 23000)
    if hi - lo < 8:
        return 23000.0
    step = max(2, int(1000 / (f[1] - f[0])))
    best_i, best_d = -1, 0.0
    for i in range(lo, hi - step):
        d = sm[i] - sm[i + step]
        if d > best_d:
            best_d, best_i = d, i
    if best_d < 20.0 or best_i < 0:
        return 23000.0
    return float(np.clip(f[best_i], 9000.0, 23000.0))


def match_ceiling(fill, fc, SRC, g0, g1):
    """Trim genuine excess above the local ceiling; never cut real content."""
    if fc >= 23000 or len(fill) < 64:
        return fill
    f, P = ctx_spectrum(SRC, g0, g1)
    if f is None:
        return fill
    n = min(4096, 1 << int(np.floor(np.log2(len(fill)))))
    if n < 256:
        return fill
    ff = np.fft.rfftfreq(n, 1 / SR)
    F = np.abs(np.fft.rfft(fill[:n] * np.hanning(n))) ** 2
    band, cb = (ff > fc + 800) & (ff < 23000), (f > fc + 800) & (f < 23000)
    if band.sum() < 4 or cb.sum() < 4:
        return fill
    if 10 * np.log10((F[band].mean() + 1e-18) / (P[cb].mean() + 1e-18)) < 6.0:
        return fill
    nt = min(129, (len(fill) // 3) | 1)
    if nt < 15:
        return fill
    return filtfilt(firwin(nt, min(fc + 1200, 23500) / (SR / 2)), [1.0], fill)


# ------------------------------------------------------------- application
def seam_fix(fill, x, a, b):
    """Force value continuity with a slope-limited anchor.

    An unlimited linear extrapolation from an already-collapsing edge sample
    throws the anchor wildly (e.g. to -8253 beside a real value of 968).
    """
    G = len(fill)
    if G < 4:
        return fill

    def anchor(i, fwd):
        w = np.abs(np.diff(x[max(0, i - 240):i])) if fwd else np.abs(np.diff(x[i:i + 240]))
        lim = 3.0 * (np.median(w) if len(w) else 0.0) + 1.0
        return (x[i - 1] + np.clip(x[i - 1] - x[i - 2], -lim, lim)) if fwd else \
               (x[i] + np.clip(x[i] - x[i + 1], -lim, lim))

    d0, d1 = anchor(a, True) - fill[0], anchor(b, False) - fill[-1]
    Ld = int(max(2, min(G // 2, 0.005 * SR)))
    dec = 0.5 * (1 + np.cos(np.pi * np.arange(Ld) / Ld))
    c = np.zeros(G); c[:Ld] += d0 * dec; c[G - Ld:] += d1 * dec[::-1]
    return fill + c


def apply_fill(dst, g0, g1, ext, F):
    """Crossfade the fill into the measured audio. Value continuity alone is not
    continuity — the derivative still breaks, and on lowpassed material that
    break lands in an empty band where it is unmistakable."""
    G = g1 - g0
    if F <= 0:
        dst[g0:g1] = np.clip(np.round(ext[:G]), -32768, 32767)
        return
    w = cosw(F)
    head = dst[g0 - F:g0].astype(np.float64) * (1 - w) + ext[:F] * w
    tail = ext[F + G:] * (1 - w) + dst[g1:g1 + F].astype(np.float64) * w
    dst[g0 - F:g0] = np.clip(np.round(head), -32768, 32767)
    dst[g0:g1] = np.clip(np.round(ext[F:F + G]), -32768, 32767)
    dst[g1:g1 + F] = np.clip(np.round(tail), -32768, 32767)


# ---------------------------------------------------------------- the pass
class Repairer:
    def __init__(self, SRC, spans, ceil, beat=0.0, grid_beats=40, refine_ms=25.0):
        self.SRC = SRC
        self.N = len(SRC)
        self.ceil = ceil
        # beat > 0 restricts exemplar lags to whole multiples of it; set per
        # span by main(), since a DJ set has no single tempo. 0 = free search.
        self.beat = beat
        self.grid_beats = grid_beats
        self.refine = int(refine_ms / 1000 * SR)
        ms = self.N // 48 + 2
        self.dmask = np.zeros(ms, bool)
        for s in spans:
            a = max(0, int(s['t0'] * 1000) - 10)
            b = min(ms, int(s['t1'] * 1000) + 10)
            self.dmask[a:b] = True
        self.dcum = np.cumsum(self.dmask)

    def dirty(self, a, b):
        ia = max(0, a // 48)
        ib = min(len(self.dcum) - 1, b // 48 + 1)
        return (self.dcum[ib] - self.dcum[ia]) > 0

    def top_lags(self, g0, g1, K=6):
        """The K best places to borrow from, best first.

        Ranking is normalised cross-correlation of the 240 ms flanking the gap.
        Left to range freely that objective has many near-ties in dense
        percussion — a busy drum window correlates respectably with almost any
        other — so it settles on timbre and lets the position within the bar
        fall where it may. Measured over this track the lags it picked sat a
        median 57 ms from a whole beat, and in the worst cluster 121 ms: a third
        of a beat, so every borrowed fragment arrived between the hits instead
        of on them, which is audible as invented rhythm.

        With `beat` set, only whole multiples of it are considered, and the
        winner is refined ±25 ms to recover sample alignment (and absorb tempo
        drift). Note the two are not alternatives that usually disagree: on
        synthetic gaps cut from clean audio the free search already lands ~25 ms
        from the grid on its own. It is specifically on real dropouts that it
        wanders, and that is the case the constraint is for.
        """
        SRC = self.SRC
        C = int(0.240 * SR)
        maxlag = MAXLAG if self.beat <= 0 else \
            int(self.grid_beats * self.beat * SR) + self.refine
        lo, hi = max(0, g0 - maxlag - C), min(self.N, g1 + maxlag + C)
        reg = mono(SRC, lo, hi)
        pre, post = mono(SRC, g0 - C, g0), mono(SRC, g1, g1 + C)
        sp_, so = ncc(pre, reg), ncc(post, reg)
        if sp_ is None or so is None:
            return []

        if self.beat > 0:
            bs = self.beat * SR
            cand = []
            for m in range(1, self.grid_beats + 1):
                for sgn in (1, -1):
                    d0 = int(round(sgn * m * bs))
                    if abs(d0) < MINLAG:
                        continue
                    ds_ = np.arange(d0 - self.refine, d0 + self.refine + 1)
                    ip_, io_ = (g0 - ds_ - C) - lo, (g1 - ds_) - lo
                    ok_ = (ip_ >= 0) & (io_ >= 0) & (ip_ < len(sp_)) & (io_ < len(so))
                    if not ok_.any():
                        continue
                    v = 0.5 * (sp_[ip_[ok_]] + so[io_[ok_]])
                    j = int(np.argmax(v))
                    cand.append((int(ds_[ok_][j]), float(v[j])))
            if not cand:
                return []
            ds = np.array([c[0] for c in cand])
            sc = np.array([c[1] for c in cand])
        else:
            ds = np.r_[np.arange(MINLAG, MAXLAG), -np.arange(MINLAG, MAXLAG)]
            ip, io = (g0 - ds - C) - lo, (g1 - ds) - lo
            ok = (ip >= 0) & (io >= 0) & (ip < len(sp_)) & (io < len(so))
            ds, sc = ds[ok], 0.5 * (sp_[ip[ok]] + so[io[ok]])

        out = []
        for i in np.argsort(-sc):
            d = int(ds[i])
            if self.dirty(g0 - d, g1 - d):
                continue
            if any(abs(d - e[0]) < int(0.05 * SR) for e in out):
                continue
            out.append((d, float(sc[i])))
            if len(out) >= K:
                break
        return out

    def repair(self, D, g0, g1):
        SRC = self.SRC
        G = g1 - g0
        F = XFADE
        xs = [SRC[g0 - PAD:g1 + PAD, c].astype(np.float64) for c in (0, 1)]
        a, b = PAD, PAD + G
        ctx = np.r_[SRC[g0 - CTX:g0].mean(axis=1),
                    SRC[g1:g1 + CTX].mean(axis=1)].astype(np.float64)
        ref_b, ref_s, ref_rms = band_energy(ctx), band_energy(ctx, 256), rms(ctx)
        pre_n, post_n = mono(SRC, g0 - G, g0), mono(SRC, g1, g1 + G)
        target = (onset_count(pre_n) + onset_count(post_n)) / 2

        def score(x):
            band = band_error_db(x, ref_b, ref_s)
            lvl = abs(20 * np.log10(rms(x) / ref_rms))
            rhy = abs(onset_count(x) - target)
            s = band + 1.5 * lvl + 4.0 * rhy
            if rms(x) < 0.15 * ref_rms:          # never fill from silence
                s += 100.0
            if int((np.abs(x) < 1).sum()) > 0.02 * len(x):
                s += 100.0
            return s

        cands = []
        for d, nc in self.top_lags(g0, g1):
            th = rms(np.r_[SRC[g0 - d - CTX:g0 - d].mean(axis=1),
                           SRC[g1 - d:g1 - d + CTX].mean(axis=1)].astype(np.float64))
            gain = float(np.clip(ref_rms / th, 0.5, 2.0))
            ext = [SRC[g0 - F - d:g1 + F - d, c].astype(np.float64) * gain for c in (0, 1)]
            cands.append(('exemplar', d, nc, ext))

        P, Q = period(xs[0][:a]), period(xs[0][b:])
        per = []
        for c in (0, 1):
            f_ = oa_extend(xs[c][:a], P, G + 2 * F)
            b_ = oa_extend(xs[c][b:][::-1], Q, G + 2 * F)
            per.append(np.zeros(G + 2 * F) if (f_ is None or b_ is None)
                       else f_ * (1 - np.linspace(0, 1, G + 2 * F)) +
                            b_[::-1] * np.linspace(0, 1, G + 2 * F))
        cands.append(('periodic', None, None, per))

        if G < int(0.040 * SR):
            ar = [janssen(xs[c], a, b)[a - F:b + F].copy() for c in (0, 1)]
            cands.append(('ar', None, None, ar))

        best = None
        for nm, d, nc, ext in cands:
            m = (ext[0][F:F + G] + ext[1][F:F + G]) / 2
            s = score(m)
            if best is None or s < best[0]:
                best = (s, nm, d, nc, ext)

        s, nm, d, nc, ext = best
        fc = local_ceiling(SRC, g0, g1)
        for c in (0, 1):
            f_ = match_ceiling(ext[c], fc, SRC, g0, g1)
            m = np.abs(f_).max()
            if m > self.ceil:
                f_ = f_ * (self.ceil / m)
            apply_fill(D[:, c], g0, g1, seam_fix(f_, xs[c], a, b), F)
        lvl = 20 * np.log10(rms((ext[0][F:F + G] + ext[1][F:F + G]) / 2) / ref_rms)
        return {'method': nm, 'lag_s': (round(d / SR, 3) if d else ''),
                'ncc': (round(nc, 3) if nc else ''), 'score': round(s, 2),
                'level_db': round(float(lvl), 1)}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('wav')
    ap.add_argument('spans')
    ap.add_argument('-o', '--out', default='repaired.wav')
    ap.add_argument('-m', '--manifest', default='repair_manifest.csv')
    ap.add_argument('--free-lag', action='store_true',
                    help='search exemplar lags freely instead of on the local '
                         'beat grid (reproduces the earlier, rhythm-blind pass)')
    ap.add_argument('--tempo-conf', type=float, default=0.30,
                    help='onset autocorrelation below which the local tempo is '
                         'not trusted and the lag search is left free')
    args = ap.parse_args()

    shutil.copyfile(args.wav, args.out)
    SRC = load(args.wav)
    D = load_rw(args.out)
    spans = json.load(open(args.spans))
    # never exceed the source peak
    ceil = max(int(np.abs(SRC[i:i + 20_000_000].astype(np.int32)).max())
               for i in range(0, len(SRC), 20_000_000))
    print(f"{len(spans)} spans, peak ceiling {ceil} "
          f"({20*np.log10(ceil/32768):.2f} dBFS)")

    R = Repairer(SRC, spans, ceil)
    rows = []
    ngrid = 0
    for k, s in enumerate(spans):
        g0 = int(round(s['t0'] * SR)) - int(0.002 * SR)
        g1 = int(round(s['t1'] * SR)) + int(0.001 * SR)
        if g1 - g0 < 8 or g0 < PAD or g1 > len(SRC) - PAD:
            continue
        beat, conf = (0.0, 0.0) if args.free_lag else local_beat(SRC, g0 / SR)
        R.beat = beat if conf >= args.tempo_conf else 0.0
        ngrid += R.beat > 0
        info = R.repair(D, g0, g1)
        lag = info['lag_s']
        rows.append({'timecode': fmt(g0 / SR), 'seconds': round(g0 / SR, 3),
                     'span_ms': round((g1 - g0) / SR * 1000, 1),
                     'method': info['method'], 'exemplar_lag_s': lag,
                     'match_ncc': info['ncc'], 'spectral_score': info['score'],
                     'fill_level_db': info['level_db'],
                     'bpm': (round(60 / beat, 1) if beat else ''),
                     'tempo_conf': round(conf, 3),
                     'off_beat_ms': (round(off_grid_ms(float(lag), R.beat), 1)
                                     if (lag != '' and R.beat) else '')})
        if (k + 1) % 50 == 0:
            print(f"  {k+1}/{len(spans)}", flush=True)
    D.flush()

    hdr = ['timecode', 'seconds', 'span_ms', 'method', 'exemplar_lag_s',
           'match_ncc', 'spectral_score', 'fill_level_db', 'bpm', 'tempo_conf',
           'off_beat_ms']
    with open(args.manifest, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=hdr); w.writeheader(); w.writerows(rows)

    from collections import Counter
    lv = np.array([r['fill_level_db'] for r in rows])
    print(f"\n  repaired {len(rows)} spans, {sum(r['span_ms'] for r in rows)/1000:.2f} s")
    print(f"  methods: {dict(Counter(r['method'] for r in rows))}")
    print(f"  fill level vs context: median {np.median(lv):+.1f} dB, "
          f"below -6 dB: {(lv < -6).sum()}")
    ob = np.array([r['off_beat_ms'] for r in rows if r['off_beat_ms'] != ''])
    print(f"  beat-gridded: {ngrid}/{len(rows)} spans"
          + (f"; chosen lags sit a median {np.median(ob):.0f} ms off the beat"
             if len(ob) else ""))
    print(f"  wrote {args.out} and {args.manifest}")


if __name__ == '__main__':
    main()
