#!/usr/bin/env python3
"""Watch state fields 4..11 as dB, live, and look for the taps.

The eight values are 24-bit quantities on the same scale as matrix levels
(0x1000000 = 0 dB), so they print as dBFS-ish numbers directly. If one of them
is an input meter, tapping the mic makes it jump and fall back; a value that is
not a meter stays flat within its own drift band.

    ./.venv/bin/python tools/probe_meters_live.py [seconds]
"""
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import uc1810c as uc

FULL = float(0x1000000)     # matrix/level scale: 0 dB


def to_db(v):
    return 20 * math.log10(v / FULL) if v > 0 else -120.0


def main():
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 40.0
    dev = uc.Dev()
    series = [[] for _ in range(8)]
    print("watching fields 4..11 in dB   (Ctrl-C to stop early)")
    print(" t     " + "  ".join("f%-2d" % (k + 4) for k in range(8)))
    t_start = time.time()
    while time.time() - t_start < seconds:
        try:
            f = dev.read_state()
        except Exception as exc:
            print("  read failed (%s), backing off" % exc)
            time.sleep(0.6)
            continue
        vals = f[4:12]
        for k in range(8):
            series[k].append(vals[k])
        print(" %4.1f  " % (time.time() - t_start)
              + "  ".join("%3.0f" % to_db(v) for v in vals))
        time.sleep(0.5)

    print("\nsummary (dB):")
    print(" field   min   max   span   >median+6dB")
    for k in range(8):
        col = sorted(series[k])
        med = col[len(col) // 2]
        dbs = [to_db(v) for v in series[k]]
        spikes = sum(1 for v in series[k] if v > med * 2)
        print("  f%-2d  %5.0f %5.0f  %5.0f   %d" % (
            k + 4, to_db(col[0]), to_db(col[-1]),
            to_db(col[-1]) - to_db(col[0]), spikes))

    print("\nIf a field spikes repeatedly and falls back, that field is the meter.")


if __name__ == "__main__":
    main()
