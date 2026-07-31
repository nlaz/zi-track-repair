#!/usr/bin/env python3
"""Find stream dropouts and derive repair spans.

    python3 tools/detect.py decoded.wav -o spans.json

Two detectors run, because one is not enough:

  edge   a fall of >THRESH dB inside one millisecond. Finds the obvious ones.
         NOTE the `pre > -25 dBFS` guard: it suppresses false positives in quiet
         passages, and in doing so it silently excludes every dropout that lands
         in one. On the source track that hid 70 of 311 events. It is kept
         because it is precise, not because it is sufficient.

  floor  a region whose level falls near digital silence *relative to its own
         surroundings*, with no absolute loudness requirement. Catches what the
         edge detector is built to skip.

Candidates from the floor detector are then gated against the shape of the known
population, because quiet intros and breakdowns also sit far below a sliding
reference. Spans are widened from the cliff to the end of the recovery ramp —
a dropout does not stop and restart, it fades back in over 30-60 ms, and that
ramp is damaged audio too.
"""
import argparse
import json
import sys

import numpy as np

sys.path.insert(0, __file__.rsplit('/', 1)[0])
from audiokit import (SR, load, envelope, sliding_reference, runs, fmt, mono)


# --------------------------------------------------------------- detectors
def detect_edge(db, nb, fall_db=32.0, pre_db=-25.0, min_ms=3):
    """Abrupt-edge dropouts. Returns block indices."""
    out, i = [], 2
    while i < nb - 3:
        if db[i - 1] > pre_db and db[i] < db[i - 1] - fall_db:
            pre = db[max(0, i - 30):i].max()
            j = i
            while j < nb - 1 and db[j] < pre - 25:
                j += 1
            if j - i >= min_ms:
                out.append(i)
                i = j
        i += 1
    return out


def detect_floor(db, sm, nb, depth=40.0, min_ms=6, floor_max=-46.0, skip_start_ms=1200):
    """Regions far below a sliding local reference AND near digital silence."""
    ref = sliding_reference(sm, nb)
    out = []
    for a, b in runs(sm < ref - depth):
        if b - a < min_ms or a < skip_start_ms:
            continue
        if sm[a:b].min() > floor_max:
            continue
        out.append((a, b))
    return out, ref


def gate_floor_candidates(db, sm, nb, cands):
    """Keep only candidates shaped like damage, not like quiet music.

    Relative, not absolute: an absolute "must be loud either side" rule rejects
    real dropouts whose neighbour is itself damaged.
    """
    keep = []
    for a, b in cands:
        W = 300
        pre = np.percentile(db[max(0, a - W):max(1, a)], 90) if a > 0 else -99
        post = np.percentile(db[b:min(nb, b + W)], 90) if b + 10 < nb else -99
        floor = float(sm[a:b].min())
        dur = b - a
        if (floor <= -60.0 and pre - floor >= 40.0 and post - floor >= 40.0
                and pre >= -30.0 and post >= -30.0 and dur <= 260):
            keep.append((a, b))
    return keep


# ------------------------------------------------------------ span shaping
def span_for(db, sm, nb, i0):
    """Cliff top -> end of the monotonic recovery ramp, in ms блоks.

    Two rules were tried and rejected first:
      * "recover to within 6 dB of context" over-extends badly when the music is
        genuinely quiet after the dropout (327 ms marked for a ~20 ms ramp).
      * "rise has stalled over 10 ms" under-extends, tripping on noise dips.
    Walking a running maximum until the rise stalls over 20 ms works on both.
    """
    ctx = np.percentile(db[max(0, i0 - 1500):max(1, i0)], 85)
    s = i0
    while s > 0 and db[s - 1] < ctx - 12 and i0 - s < 60:
        s -= 1
    f0 = i0 + int(np.argmin(sm[i0:i0 + 60]))
    floor = sm[f0]
    seg = sm[f0:f0 + 221]
    if len(seg) < 40:
        return s, i0 + 20
    rmax = np.maximum.accumulate(seg)
    j = 0
    while j < 200 and j + 20 < len(rmax):
        if rmax[j] > floor + 10 and (rmax[j + 20] - rmax[j]) < 2.0:
            break
        j += 1
    return s, f0 + j + 5


def merge(spans, gap_ms=15):
    spans = sorted(spans)
    out = []
    for a, b in spans:
        if out and a <= out[-1][1] + gap_ms:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


# ------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('wav')
    ap.add_argument('-o', '--out', default='spans.json')
    ap.add_argument('--edge-only', action='store_true',
                    help='skip the floor detector (reproduces the original, incomplete scan)')
    args = ap.parse_args()

    X = load(args.wav)
    print(f"{args.wav}: {len(X)/SR:.1f} s")
    db, sm, nb = envelope(X)

    edge = detect_edge(db, nb)
    print(f"  edge detector      : {len(edge)} dropouts")

    hits = [(i, i + 4) for i in edge]
    if not args.edge_only:
        cands, _ = detect_floor(db, sm, nb)
        gated = gate_floor_candidates(db, sm, nb, cands)
        # keep only those the edge detector did not already find
        et = np.array(sorted(edge)) if edge else np.array([-1e9])
        extra = [(a, b) for a, b in gated
                 if np.min(np.abs(et - a)) > 120]
        print(f"  floor detector     : {len(cands)} candidates -> {len(gated)} damage-shaped"
              f" -> {len(extra)} not already found")
        hits += extra

    spans = []
    for a, _ in hits:
        s, f = span_for(db, sm, nb, int(a))
        if f - s >= 4:
            spans.append([s, f])
    spans = merge(spans)

    out = [{'t0': round(a / 1000.0, 4), 't1': round(b / 1000.0, 4),
            'ms': round(b - a, 1)} for a, b in spans]
    json.dump(out, open(args.out, 'w'), indent=1)
    total = sum(o['ms'] for o in out)
    print(f"\n  repair spans       : {len(out)}   total {total/1000:.2f} s")
    if out:
        longest = sorted(out, key=lambda o: -o['ms'])[:5]
        print("  longest:")
        for o in longest:
            print(f"     {fmt(o['t0'])}  {o['ms']:6.1f} ms")
    print(f"  wrote {args.out}")


if __name__ == '__main__':
    main()
