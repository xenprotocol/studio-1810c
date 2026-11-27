#!/usr/bin/env python3
"""Characterise why 0xA1 stalls: try each request shape in isolation."""
import struct
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import uc1810c as uc


def attempt(label, fn):
    try:
        r = fn()
        print("  OK   %-58s -> %s" % (label, r if r is not None else ""))
        return True
    except Exception as exc:
        print("  FAIL %-58s -> %s" % (label, exc))
        return False


def main():
    d = uc.Dev()
    print("device open: %04x:%04x" % (d.dev.idVendor, d.dev.idProduct))

    print("\n-- read-only probes")
    attempt("bRequest 0xB1 IN 2 (family status)", lambda: d._in(0xB1, 2).hex())
    attempt("bRequest 0xA2 IN 8, wValue=1 (no preceding set)",
            lambda: d._in(0xA2, 8, wvalue=1).hex())
    attempt("bRequest 0xA4 IN 8, wValue=1 (clock internal)",
            lambda: d._in(0xA4, 8, wvalue=1).hex())
    attempt("bRequest 0xD2 IN 8, wValue=1 (no preceding set)",
            lambda: d._in(0xD2, 8, wvalue=1).hex())

    print("\n-- 0xA1 shapes (252 bytes, tag+len set)")
    def set_state(seq, field0, windex=0, length=252):
        pkt = bytearray(length)
        struct.pack_into("<I", pkt, 0, field0)
        struct.pack_into("<I", pkt, 8, uc.TAG_STATE)
        struct.pack_into("<I", pkt, 12, uc.STATE_LEN)
        return d._out(0xA1, bytes(pkt), wvalue=seq, windex=windex)

    for seq, f0, note in ((1, 0, "fields[0]=0 like the kernel"),
                          (1, 1, "fields[0]=seq"),
                          (0, 0, "seq 0"),
                          (0x1234, 0, "seq 0x1234"),
                          (0xFFFF, 0, "seq 0xFFFF")):
        if attempt("0xA1 seq=%#06x %s" % (seq, note), lambda: set_state(seq, f0)):
            attempt("    then 0xA2 IN 252 wValue=%#x" % seq,
                    lambda: d._in(0xA2, 252, wvalue=seq).hex()[:64])
    attempt("0xA1 244 bytes (in-packet length)",
            lambda: set_state(7, 0, length=244))
    attempt("0xA1 wIndex=1", lambda: set_state(8, 0, windex=1))


if __name__ == "__main__":
    main()
