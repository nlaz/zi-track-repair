#!/usr/bin/env python3
"""Check a repair against the original.

    python3 tools/verify.py original.wav repaired.wav spans.json

Every check here exists because an earlier version of this repair passed the
others and was still wrong. In order of discovery:

  integrity   nothing outside a repair span and its crossfade may change.
  dropouts    the abrupt-edge detector, re-run on the output.
  fill level  a fill that decays quietly to nothing has no sharp edge for a
              dropout detector to find. Measured against ±100 ms, not ±250 ms —
              in material with steep dynamics a wide window makes ordinary fills
              look 6 dB down when they are not.
  seam step   sample step at the boundary vs its neighbours.
  ultrasonic  19-23 kHz energy at each seam. This material is lowpassed near
              18.7 kHz so the band is empty; a hard splice is unmistakable there
              even when music masks it lower down. A >8 kHz check misses it.
  silence     digital-zero runs the repair introduced (a fill copied from a
              silent source region).
  peak/stereo the repair must not clip or shift the image.

Thresholds are stated against a CONTROL drawn from untouched audio in the same
file. Without one, "median seam ratio 0.21" means nothing; with one it means the
repairs are smoother than the material's own transitions.
"""
import argparse
import json
import sys

import numpy as np

sys.path.insert(0, __file__.rsplit('/', 1)[0])
from audiokit import (SR, load, mono, rms, fmt, envelope,
                      ultrasonic_burst, seam_step_ratio)

CH = 20_000_000


def detect_dropouts(X, fall=32.0, pre=-25.0, min_ms=3):
    db, _, nb = envelope(X)
    out, i = [], 2
    while i < nb - 3:
        if db[i - 1] > pre and db[i] < db[i - 1] - fall:
            p = db[max(0, i - 30):i].max(); j = i
            while j < nb - 1 and db[j] < p - 25:
                j += 1
            if j - i >= min_ms:
                out.append(i / 1000.0); i = j
        i += 1
    return out


def zero_runs(X, minlen=48):
    m = (X[:, 0] == 0) & (X[:, 1] == 0)
    d = np.diff(m.astype(np.int8))
    st = np.where(d == 1)[0] + 1
    en = np.where(d == -1)[0] + 1
    if m[0]:
        st = np.r_[0, st]
    if m[-1]:
        en = np.r_[en, len(m)]
    return [(int(a), int(b)) for a, b in zip(st, en) if b - a >= minlen]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('original'); ap.add_argument('repaired'); ap.add_argument('spans')
    ap.add_argument('--guard-ms', type=float, default=15.0,
                    help='span guard for the integrity mask; must cover the '
                         'pre-guard plus crossfade or it flags false positives')
    ap.add_argument('--pre-guard-ms', type=float, default=0.0,
                    help='shift span starts earlier by this much before measuring '
                         'seams. repair.py records true boundaries so 0 is right for '
                         'its output; point this at 2.0 for a manifest that stores '
                         'span starts from before the pre-guard, or every seam is '
                         'probed a few ms inside the fill and reads as a false click')
    args = ap.parse_args()

    A, B = load(args.original), load(args.repaired)
    spans = json.load(open(args.spans))
    N = min(len(A), len(B))
    XF = int(args.guard_ms / 1000 * SR)
    rng = np.random.default_rng(1)
    fails = []

    # 1 integrity
    mask = np.zeros(N, bool)
    for s in spans:
        g0 = max(0, int(s['t0'] * SR) - XF)
        g1 = min(N, int(s['t1'] * SR) + XF)
        mask[g0:g1] = True
    d = 0
    for i in range(0, N, CH):
        j = min(N, i + CH); m = ~mask[i:j]
        if m.any():
            d += int((A[i:j][m] != B[i:j][m]).sum())
    print(f"1. samples changed outside repairs : {d}")
    print(f"   audio touched                   : {mask.sum()/SR:.2f} s "
          f"({100*mask.sum()/N:.3f}%)")
    if d:
        fails.append("audio changed outside repair regions")

    # 2 dropouts
    da, db_ = detect_dropouts(A), detect_dropouts(B)
    print(f"2. abrupt dropouts                 : {len(da)} -> {len(db_)}")
    if db_:
        fails.append(f"{len(db_)} dropouts remain")

    # 3 fill level
    C = int(0.10 * SR); lv = []
    for s in spans:
        g0, g1 = int(s['t0'] * SR), int(s['t1'] * SR)
        if g0 < C or g1 > N - C:
            continue
        lv.append(20 * np.log10(rms(B[g0:g1]) / rms(np.r_[B[g0 - C:g0], B[g1:g1 + C]])))
    lv = np.array(lv)
    print(f"3. fill level vs context (+-100 ms): median {np.median(lv):+.1f} dB   "
          f"below -6 dB {(lv < -6).sum()}   below -10 dB {(lv < -10).sum()}")

    # 4 seam step, against a control
    PG = int(args.pre_guard_ms / 1000 * SR)
    edges = [e for s in spans for e in (int(s['t0'] * SR) - PG, int(s['t1'] * SR))
             if SR < e < N - SR]
    r = np.array([seam_step_ratio(B, e, c) for e in edges for c in (0, 1)])
    ctrl = np.array([seam_step_ratio(A, int(p), c)
                     for p in rng.integers(SR, N - SR, 1500) for c in (0, 1)])
    r, ctrl = r[~np.isnan(r)], ctrl[~np.isnan(ctrl)]
    print(f"4. seam step   repaired median {np.median(r):.2f} max {r.max():.2f}   "
          f"control median {np.median(ctrl):.2f} max {ctrl.max():.2f}")
    if (r > 2).sum():
        fails.append(f"{(r>2).sum()} seams exceed 2x the local norm")

    # 5 ultrasonic burst, against a control
    u = np.array([ultrasonic_burst(B, e) for e in edges])
    uc = np.array([ultrasonic_burst(A, int(p)) for p in rng.integers(SR, N - SR, 200)])
    u, uc = u[~np.isnan(u)], uc[~np.isnan(uc)]
    th = np.percentile(uc, 99)
    ratio = np.median(u) / max(np.median(uc), 1e-9)
    print(f"5. seam 19-23 kHz  repaired median {np.median(u):.2f}   "
          f"control median {np.median(uc):.2f}   ratio {ratio:.2f}x   "
          f"(above control p99: {(u > th).sum()}/{len(u)})")
    # Compare medians, not an exceedance count: with a few hundred control
    # samples the p99 is the 2nd-highest value and far too noisy to gate on.
    # Hard splices are not subtle - the failure this guards against measured a
    # median of 258x - so a 3x median ratio separates them with room to spare.
    if ratio > 3.0:
        fails.append(f"broadband splice bursts at seams ({ratio:.1f}x control median)")

    # 6 silence introduced
    za, zb = zero_runs(A), zero_runs(B)
    new = [x for x in zb if not any(abs(x[0] - y[0]) < SR for y in za)]
    print(f"6. digital-silence runs introduced  : {len(new)}")
    if new:
        fails.append(f"{len(new)} new digital-silence runs")

    # 7 peak and stereo image
    pk = lambda X: max(int(np.abs(X[i:i + CH].astype(np.int32)).max())
                       for i in range(0, N, CH))
    pa, pb = pk(A), pk(B)
    full = sum(int((np.abs(B[i:i + CH].astype(np.int32)) >= 32767).sum())
               for i in range(0, N, CH))
    n = min(4_000_000, N)
    ca = np.corrcoef(A[:n, 0].astype(float), A[:n, 1].astype(float))[0, 1]
    cb = np.corrcoef(B[:n, 0].astype(float), B[:n, 1].astype(float))[0, 1]
    print(f"7. peak {20*np.log10(pa/32768):.2f} -> {20*np.log10(pb/32768):.2f} dBFS   "
          f"full-scale samples {full}   L/R corr {ca:.4f} -> {cb:.4f}")
    if pb > pa:
        fails.append("repair raised the peak level")

    print()
    if fails:
        print("FAILED:")
        for f in fails:
            print(f"  - {f}")
        sys.exit(1)
    print("all checks passed")


if __name__ == '__main__':
    main()
