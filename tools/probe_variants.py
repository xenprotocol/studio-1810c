#!/usr/bin/env python3
"""1) Find which bmRequestType/wIndex shape the stalled requests want.
   2) Functional proof of the matrix: does muting DAW->Main kill the meters?"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import uc1810c as uc

RT = {(0xC0, 0): "vendor/dev/in", (0xC1, 0): "vendor/if0/in", (0xC1, 3): "vendor/if3/in",
      (0xC2, 0): "vendor/ep/in", (0x41, 0): "vendor/if0/out", (0x40, 0): "vendor/dev/out"}


def try_in(d, req, length, wvalue, windex, rt):
    try:
        buf = d.dev.ctrl_transfer(rt, req, wvalue, windex, length, timeout=1500)
        return bytes(buf).hex()
    except Exception as exc:
        return "ERR %s" % getattr(exc, "errno", exc)


def probe_variants(d):
    print("[1] request shapes (recipient / wIndex sweep)")
    for req, length, wvalues in ((0xB1, 2, [0]), (0xA4, 8, [1, 2, 3]),
                                 (0xD4, 8, [10, 11, 12, 13])):
        for wvalue in wvalues:
            row = []
            for (rt, wix) in ((0xC0, 0), (0xC1, 0), (0xC1, 3), (0xC2, 0)):
                row.append("%s=%s" % (RT[(rt, wix)], try_in(d, req, length, wvalue, wix, rt)))
            print("  req=%#04x wValue=%-3d %s" % (req, wvalue, " | ".join(row)))

    print("\n[2] 0xD1 OUT then 0xD2 IN, several lengths")
    for length in (8, 64, 244, 256):
        try:
            d._out(0xD1, bytes(length), wvalue=1)
            out = d._in(0xD2, length, wvalue=1)
            print("  len=%-4d OK  %s" % (length, out.hex()[:64]))
        except Exception as exc:
            print("  len=%-4d ERR %s" % (length, exc))


def meters(d):
    s = d.read_state()
    return s[4:12]


def tone_test(d):
    print("\n[3] functional matrix proof (1 kHz tone on DAW 1/2)")
    dev = ["speaker-test", "-D", "hw:2", "-c", "2", "-t", "sine", "-f", "1000", "-l", "1"]
    p = subprocess.Popen(dev, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.6)
    peaks_on = []
    for _ in range(6):
        peaks_on.append(meters(d))
        time.sleep(0.12)
    p.terminate()
    p.wait()

    print("  meters while playing, DAW1/2 -> Main at unity:")
    for m in peaks_on:
        print("   ", ["%6d" % v for v in m])

    print("  now mute DAW 1 and DAW 2 into Main (both sides) and replay")
    for ch in (18, 19):
        for side in ("L", "R"):
            d.set_mixer(ch, 0, side, uc.MUTE)
    p = subprocess.Popen(dev, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.6)
    peaks_off = []
    for _ in range(6):
        peaks_off.append(meters(d))
        time.sleep(0.12)
    p.terminate()
    p.wait()

    print("  meters while playing, DAW1/2 muted:")
    for m in peaks_off:
        print("   ", ["%6d" % v for v in m])

    on = max(max(m) for m in peaks_on)
    off = max(max(m) for m in peaks_off)
    print("\n  peak while routed: %d   peak while muted: %d   -> %s"
          % (on, off, "MATRIX AFFECTS AUDIO" if off < on * 0.5 else "no clear effect"))

    print("  restoring DAW 1/2 -> Main at unity")
    for ch in (18, 19):
        for side in ("L", "R"):
            d.set_mixer(ch, 0, side, uc.UNIT_0DB)


if __name__ == "__main__":
    d = uc.Dev()
    probe_variants(d)
    tone_test(d)
