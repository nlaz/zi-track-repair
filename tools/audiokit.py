"""Shared audio helpers for the dropout detection / repair / verification tools.

Everything works on a 16-bit stereo WAV memmap so a 66-minute track can be
handled without loading it all into RAM.
"""
import numpy as np

SR = 48000
BLOCK_MS = 48          # samples per 1 ms envelope block at 48 kHz


# ---------------------------------------------------------------- file I/O
def load(path):
    """Memmap a 16-bit PCM WAV as an (N, 2) int16 array. Assumes a 44-byte header."""
    a = np.memmap(path, dtype='<i2', mode='r', offset=44)
    return a[:(len(a) // 2) * 2].reshape(-1, 2)


def load_rw(path):
    a = np.memmap(path, dtype='<i2', mode='r+', offset=44)
    return a[:(len(a) // 2) * 2].reshape(-1, 2)


def mono(X, a=None, b=None):
    s = X[a:b]
    return (s[:, 0].astype(np.float64) + s[:, 1].astype(np.float64)) / 2


def rms(x):
    return float(np.sqrt((np.asarray(x, dtype=np.float64) ** 2).mean()) + 1e-9)


def fmt(t):
    """Seconds -> MM:SS.mmm"""
    return f"{int(t // 60):02d}:{t % 60:06.3f}"


# ------------------------------------------------------------- envelopes
def envelope(X, chunk=2_000_000):
    """Per-millisecond peak envelope in dBFS, plus a 5 ms smoothed copy.

    Returns (db, smooth, n_blocks). Chunked so it works on a full-length track.
    """
    B = BLOCK_MS
    nb = len(X) // B
    pk = np.empty(nb, dtype=np.float32)
    for i in range(0, nb, chunk):
        j = min(nb, i + chunk)
        blk = X[i * B:j * B].astype(np.int32)
        pk[i:j] = np.abs((blk[:, 0] + blk[:, 1]) // 2).reshape(j - i, B).max(axis=1)
    db = 20 * np.log10(pk / 32768 + 1e-9)
    K = 5
    c = np.cumsum(np.insert(db.astype(np.float64), 0, 0))
    sm = (c[K:] - c[:-K]) / K
    sm = np.r_[sm, np.full(len(db) - len(sm), sm[-1])].astype(np.float32)
    return db, sm, nb


def sliding_reference(sm, nb, half_ms=2000, step=500, pct=75):
    """Local loudness reference: percentile over a sliding window, on a coarse grid."""
    xs = np.arange(0, nb, step)
    vals = np.array([np.percentile(sm[max(0, x - half_ms):min(nb, x + half_ms)], pct)
                     for x in xs])
    return np.interp(np.arange(nb), xs, vals).astype(np.float32)


def runs(mask):
    """Contiguous True runs in a boolean array -> list of (start, end) indices."""
    d = np.diff(mask.astype(np.int8))
    st = np.where(d == 1)[0] + 1
    en = np.where(d == -1)[0] + 1
    if mask[0]:
        st = np.r_[0, st]
    if mask[-1]:
        en = np.r_[en, len(mask)]
    return list(zip(st.tolist(), en.tolist()))


# ------------------------------------------------------- spectral measures
# Bark-ish critical band edges, Hz
BAND_EDGES = [0, 100, 200, 300, 400, 510, 630, 770, 920, 1080, 1270, 1480, 1720,
              2000, 2320, 2700, 3150, 3700, 4400, 5300, 6400, 7700, 9500, 12000,
              15500, 20000, 24000]


def band_energy(x, n=1024):
    """Mean per-critical-band energy of a signal."""
    if len(x) < n:
        n = 1 << int(np.floor(np.log2(max(len(x), 32))))
    if n < 32:
        return np.ones(1)
    hop = max(n // 2, 1)
    w = np.hanning(n)
    f = np.fft.rfftfreq(n, 1 / SR)
    idx = [np.where((f >= BAND_EDGES[i]) & (f < BAND_EDGES[i + 1]))[0]
           for i in range(len(BAND_EDGES) - 1)]
    idx = [i for i in idx if len(i)]
    acc = np.zeros(len(idx))
    cnt = 0
    for p in range(0, max(1, len(x) - n + 1), hop):
        S = np.abs(np.fft.rfft(x[p:p + n] * w)) ** 2
        acc += np.array([S[i].sum() for i in idx])
        cnt += 1
    return acc / max(cnt, 1) + 1e-12


def band_error_db(fill, ref_big, ref_small):
    """Mean |dB| deviation per band between a fill and its context reference.

    Picks the reference computed at matching FFT size — a short fill uses a
    smaller transform, which yields fewer usable bands.
    """
    big = len(fill) >= 1024
    fb = band_energy(fill) if big else band_energy(fill, 256)
    rb = ref_big if big else ref_small
    n = min(len(fb), len(rb))
    fb, rb = fb[:n], rb[:n]
    keep = rb > rb.max() * 1e-6
    if keep.sum() == 0:
        return 999.0
    return float(np.abs(10 * np.log10(fb[keep] / rb[keep])).mean())


def ultrasonic_burst(X, edge, half=int(0.25 * SR), lo=19000, hi=23000):
    """Peak 19-23 kHz energy within +-5 ms of `edge`, over the local median.

    This material is lowpassed around 18.7 kHz, so that band is empty and any
    splice discontinuity shows up there unmistakably even when music masks it
    lower down. Compare against a control drawn from untouched audio.
    """
    a, b = edge - half, edge + half
    if a < 0 or b > len(X):
        return np.nan
    m = mono(X, a, b) / 32768
    n, hop = 256, 48
    f = np.fft.rfftfreq(n, 1 / SR)
    band = (f >= lo) & (f <= hi)
    p = np.arange(0, len(m) - n, hop)
    pr = np.array([np.abs(np.fft.rfft(m[q:q + n] * np.hanning(n)))[band].sum()
                   for q in p]) + 1e-12
    k = len(pr) // 2
    return float(pr[k - 5:k + 6].max() / (np.median(pr) + 1e-12))


def seam_step_ratio(X, edge, ch, W=480):
    """Sample step at `edge` over the 99.5th percentile of neighbouring steps.

    The seam itself is excluded from the reference, so a value near 1 means the
    boundary is as smooth as the material's own transitions.
    """
    if edge < W + 4 or edge >= len(X) - W - 4:
        return np.nan
    seg = X[edge - W:edge + W, ch].astype(np.float64)
    d = np.abs(np.diff(seg))
    k = W - 1
    nb = np.r_[d[:k - 2], d[k + 3:]]
    return float(d[k] / (np.percentile(nb, 99.5) + 1e-9))


# ------------------------------------------------------------ rhythm
def onset_env(x, H=BLOCK_MS):
    nb = len(x) // H
    if nb < 3:
        return np.zeros(3)
    en = np.abs(x[:nb * H].reshape(nb, H)).max(axis=1)
    return np.clip(np.diff(np.log(en + 1e-6), prepend=0), 0, None)


def onset_count(x, thr=1.2):
    """Transients in a signal. Band energy and level are averages and cannot see
    *when* energy arrives; this is the term that can."""
    return float((onset_env(x) > thr).sum())
