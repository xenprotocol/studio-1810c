#!/usr/bin/env python3
"""Pin down the DSP channel addressing and the audio-mode switch."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import uc1810c as uc

SHAPES = [(0xC1, 3), (0xC1, 0), (0xC0, 0), (0xC1, 1), (0xC1, 2), (0xC1, 4)]


def rd(d, req, length, wvalue, rt, wix):
    try:
        return bytes(d.dev.ctrl_transfer(rt, req, wvalue, wix, length, timeout=1500)).hex()
    except Exception as exc:
        return "ERR%s" % getattr(exc, "errno", "?")


def wr(d, req, wvalue, rt, wix, data=b""):
    try:
        d.dev.ctrl_transfer(rt, req, wvalue, wix, data, timeout=1500)
        return "OK"
    except Exception as exc:
        return "ERR%s" % getattr(exc, "errno", "?")


def main():
    d = uc.Dev()

    print("[A] 0xB1 IN, shapes x lengths")
    for rt, wix in SHAPES:
        row = ["len%d=%s" % (ln, rd(d, 0xB1, ln, 0, rt, wix)) for ln in (2, 4, 8)]
        print("  rt=%#04x wix=%d  %s" % (rt, wix, "  ".join(row)))

    print("\n[B] 0xD4 IN, shapes x wValue")
    for rt, wix in SHAPES:
        row = ["v%d=%s" % (v, rd(d, 0xD4, 8, v, rt, wix)) for v in (10, 11)]
        print("  rt=%#04x wix=%d  %s" % (rt, wix, "  ".join(row)))

    print("\n[C] 0xD1 OUT then 0xD2 IN (interface 3 recipient)")
    for length in (8, 64, 244, 256):
        o = wr(d, 0xD1, 1, 0x41, 3, bytes(length))
        i = rd(d, 0xD2, length, 1, 0xC1, 3) if o == "OK" else "-"
        print("  len=%-4d out=%s in=%s" % (length, o, i[:40] if i else i))

    print("\n[D] 0x42 SwitchAudioMode OUT (wIndex 3 = legacy iface)")
    for val in (0, 1):
        print("  wValue=0 wIndex=3 val=%d -> %s" % (val, wr(d, 0x42, 0, 0x41, 3, b"")))
        print("  wValue=%d wIndex=3       -> %s" % (val, wr(d, 0x42, val, 0x41, 3, b"")))
        print("  wValue=0 wIndex=0 val=%d -> %s" % (val, wr(d, 0x42, 0, 0x40, 0, b"")))

    print("\n[E] after mode pokes: 0xA4 and 0xB1 again")
    print("  0xA4 wValue=1 wix=3 ->", rd(d, 0xA4, 8, 1, 0xC1, 3))
    print("  0xB1 wix=3         ->", rd(d, 0xB1, 2, 0, 0xC1, 3))


if __name__ == "__main__":
    main()
