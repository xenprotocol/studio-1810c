#!/usr/bin/env python3
"""Does the vendor channel need a preceding state sync? And what does the
state packet actually contain (static config vs live meters)?"""
import struct
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import uc1810c as uc


def attempt(label, fn):
    try:
        r = fn()
        print("  OK   %-52s -> %s" % (label, r if r is not None else ""))
        return r
    except Exception as exc:
        print("  FAIL %-52s -> %s" % (label, exc))
        return None


def main():
    d = uc.Dev()

    print("[A] state read with corrected packet")
    s = attempt("0xA1/0xA2", d.read_state)
    if s:
        print("   first 16 fields:", ["%#x" % v for v in s[:16]])

    print("\n[B] same requests again, immediately after a successful sync")
    attempt("0xB1 IN 2", lambda: d._in(0xB1, 2).hex())
    attempt("0xA4 IN 8 wValue=1", lambda: d._in(0xA4, 8, wvalue=1).hex())
    attempt("0xD2 IN 8 wValue=1", lambda: d._in(0xD2, 8, wvalue=1).hex())
    attempt("0xD4 IN 8 wValue=10", lambda: d._in(0xD4, 8, wvalue=10).hex())

    print("\n[C] is the packet static or live? 5 reads, 250 ms apart")
    reads = []
    for i in range(5):
        reads.append(d.read_state())
        time.sleep(0.25)
    for idx in range(4, 63):
        vals = [r[idx] for r in reads]
        if len(set(vals)) > 1:
            print("   field[%2d] changes: %s" % (idx, ["%#x" % v for v in vals]))
    static = [idx for idx in range(4, 63) if len(set(r[idx] for r in reads)) == 1]
    print("   static fields:", static)
    print("   static values:", ["%#x" % reads[0][i] for i in static])

    print("\n[D] switch state fields vs ALSA (kernel reads the same bytes)")
    cur = d.read_state()
    print("   state 58/59/60/61/62 = %d %d %d %d %d"
          % (cur[58], cur[59], cur[60], cur[61], cur[62]))
    os.system("amixer -D hw:2 cget numid=3 2>/dev/null | tail -1")
    os.system("amixer -D hw:2 cget numid=4 2>/dev/null | tail -1")
    os.system("amixer -D hw:2 cget numid=7 2>/dev/null | tail -1")


if __name__ == "__main__":
    main()
