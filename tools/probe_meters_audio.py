#!/usr/bin/env python3
"""Correlate state fields 4..11 against real capture audio, with alignment search.

Records the interface while sampling the state packet, builds a 50 ms RMS
envelope per capture channel, then searches a small time shift between the two
timelines before scoring. Without the shift search, a 100 ms stream-start skew
is enough to make a real meter look like noise.

    ./.venv/bin/python tools/probe_meters_audio.py [seconds] [input-channel]

Make noise into the given input while it runs.
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
BLOCK_S = 0.05
SHIFT_BLOCKS = 12          # search +-600 ms


def pearson(a, b):
    n = min(len(a), len(b))
    if n < 8:
        return 0.0
    a, b = a[:n], b[:n]
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    return num / (da * db) if da and db else 0.0


def shifted(col, shift):
    if shift >= 0:
        return col[shift:]
    return col[:shift]


def main():
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
    probe_ch = int(sys.argv[2]) if len(sys.argv) > 2 else 1     # 1-based
    raw = "/tmp/uc1810c_cap.raw"
    dev = uc.Dev()

    rows = []                                  # (t, fields[4..11])
    t_start = time.time()
    rec = subprocess.Popen(
        ["arecord", "-D", "hw:2", "-f", "S32_LE", "-c", str(CHANNELS),
         "-r", str(RATE), "-t", "raw", "-q", raw],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    t_audio = time.time()

    t_end = t_start + seconds
    next_report = t_start + 5
    while time.time() < t_end:
        try:
            fields = dev.read_state()[4:12]
        except Exception as exc:
            # the device stalls 0xA1 if it is polled too fast while streaming
            print("  state read failed (%s), backing off" % exc, file=sys.stderr)
            time.sleep(0.5)
            continue
        rows.append((time.time(), fields))
        if time.time() >= next_report:
            next_report += 5
            print("  %2.0fs  field4..11 = %s"
                  % (time.time() - t_start,
                     " ".join("%05x" % v for v in fields)), file=sys.stderr)
        time.sleep(0.5)          # 2 Hz: 20 Hz made the device stall

    rec.terminate()
    try:
        rec.wait(timeout=3)
    except subprocess.TimeoutExpired:
        rec.kill()

    data = open(raw, "rb").read()
    samples = array.array("i")
    samples.frombytes(data)
    nframes = len(samples) // CHANNELS
    dur = nframes / RATE
    print("\ncaptured %.2f s, %d channels" % (dur, CHANNELS))
    if nframes < int(RATE * 1):
        print("too little audio")
        return

    block = int(RATE * BLOCK_S)
    nblocks = min(nframes // block, int(dur / BLOCK_S))
    env = []
    for c in range(CHANNELS):
        col = []
        for b in range(nblocks):
            base = (b * block) * CHANNELS + c
            s = 0.0
            n = 0
            for i in range(0, block, 16):
                v = samples[base + i * CHANNELS] / 2147483648.0
                s += v * v
                n += 1
            col.append(math.sqrt(s / n))
        env.append(col)

    print("\npeak RMS per capture channel:")
    for c in range(CHANNELS):
        peak = max(env[c]) or 1e-12
        print("  ch%-2d %6.1f dBFS %s" % (c + 1, 20 * math.log10(peak),
                                          "<-- probe input" if c + 1 == probe_ch else ""))

    # state fields on the same grid, aligned to the audio start time
    grid = [[0.0] * nblocks for _ in range(8)]
    counts = [0] * nblocks
    for t, f in rows:
        b = int((t - t_audio) / BLOCK_S)
        if 0 <= b < nblocks:
            counts[b] += 1
            for k in range(8):
                grid[k][b] += f[k]
    for k in range(8):
        for b in range(nblocks):
            if counts[b]:
                grid[k][b] /= counts[b]

    print("\nbest correlation per field (shift search +-600 ms):")
    print("  field  channel        r     shift")
    best_overall = (0, None, None, 0)
    for k in range(8):
        best = (0.0, None, 0)
        for c in range(CHANNELS):
            for sh in range(-SHIFT_BLOCKS, SHIFT_BLOCKS + 1):
                r = pearson(grid[k], shifted(env[c], sh))
                if abs(r) > abs(best[0]):
                    best = (r, c, sh)
        r, c, sh = best
        note = ""
        if abs(r) > 0.6 and c is not None and c + 1 == probe_ch:
            note = "  <-- tracks the probe input"
        elif abs(r) > 0.6:
            note = "  <-- tracks ch%d" % (c + 1)
        print("  %-5d  ch%-2d      %+6.2f   %+d ms%s"
              % (k + 4, (c + 1) if c is not None else 0, r, sh * int(BLOCK_S * 1000), note))
        if abs(r) > abs(best_overall[0]):
            best_overall = (r, k + 4, (c + 1) if c is not None else 0, sh)

    print("\nstrongest: field %s vs ch%s r=%+.2f (shift %+d ms)"
          % (best_overall[1], best_overall[2], best_overall[0],
             best_overall[3] * int(BLOCK_S * 1000)))


if __name__ == "__main__":
    main()
