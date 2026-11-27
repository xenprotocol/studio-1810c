#!/usr/bin/env python3
"""Are state fields 4..11 really the input level meters?

Records the interface while sampling the state packet, then correlates each of
the eight fields against the RMS envelope of every capture channel. A field that
tracks audio will show a high correlation with one channel and near-zero with
the rest.

    ./.venv/bin/python tools/probe_meters_corr.py [seconds]

Nothing is written to the device; the only side effect is that opening the PCM
forces the interface to a streaming altset (and therefore a sample rate).
"""
import array
import math
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import uc1810c as uc

RATE = 96000
CHANNELS = 14
BLOCK = int(RATE * 0.05)          # 50 ms envelope
RAW = "/tmp/uc1810c_cap.raw"


def pearson(a, b):
    n = min(len(a), len(b))
    if n < 4:
        return 0.0
    a, b = a[:n], b[:n]
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    return num / (da * db) if da and db else 0.0


def main():
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 6.0
    dev = uc.Dev()

    rec = subprocess.Popen(
        ["arecord", "-D", "hw:2", "-f", "S32_LE", "-c", str(CHANNELS),
         "-r", str(RATE), "-t", "raw", "-q", RAW],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    time.sleep(0.4)                        # let the stream start

    rows = []
    t_end = time.time() + seconds
    while time.time() < t_end:
        t = time.time()
        try:
            fields = dev.read_state()[4:12]
        except Exception as exc:
            print("state read failed:", exc)
            break
        rows.append((t, fields))
        time.sleep(0.02)

    rec.terminate()
    try:
        rec.wait(timeout=3)
    except subprocess.TimeoutExpired:
        rec.kill()
    if rec.returncode not in (0, -15, 143):
        print("arecord said:", rec.stderr.read().decode()[-300:])

    raw = open(RAW, "rb").read()
    samples = array.array("i")
    samples.frombytes(raw)
    nframes = len(samples) // CHANNELS
    print("captured %.2f s  (%d frames, %d ch)" % (nframes / RATE, nframes, CHANNELS))
    if nframes < BLOCK * 2:
        print("too little audio to analyse")
        return

    # per-channel RMS envelope in 50 ms blocks
    nblocks = min(nframes // BLOCK, 400)
    env = []
    for c in range(CHANNELS):
        col = []
        for b in range(nblocks):
            base = (b * BLOCK) * CHANNELS + c
            s = 0
            for i in range(0, BLOCK, 8):          # stride: 8x faster, still smooth
                v = samples[base + i * CHANNELS] / 2147483648.0
                s += v * v
            col.append(math.sqrt(s / (BLOCK / 8)))
        env.append(col)

    print("\npeak RMS per capture channel (dBFS):")
    for c in range(CHANNELS):
        peak = max(env[c]) or 1e-9
        print("  ch%-2d %.1f" % (c + 1, 20 * math.log10(peak)))

    # state fields, resampled onto the same 50 ms grid
    t0 = rows[0][0]
    grid = [[0.0] * nblocks for _ in range(8)]
    counts = [0] * nblocks
    for t, f in rows:
        b = int((t - t0) / 0.05)
        if 0 <= b < nblocks:
            counts[b] += 1
            for k in range(8):
                grid[k][b] += f[k]
    for k in range(8):
        for b in range(nblocks):
            if counts[b]:
                grid[k][b] /= counts[b]

    print("\ncorrelation (field vs channel envelope), best match per field:")
    for k in range(8):
        scores = sorted(((abs(pearson(grid[k], env[c])), c) for c in range(CHANNELS)),
                        reverse=True)
        top = scores[0]
        rest = sum(s for s, _ in scores[2:]) / max(1, len(scores) - 2)
        print("  field %-2d -> ch%-2d  r=%+.2f   (next best %.2f, rest avg %.2f)"
              % (k + 4, top[1] + 1, pearson(grid[k], env[top[1]]), scores[1][0], rest))


if __name__ == "__main__":
    main()
