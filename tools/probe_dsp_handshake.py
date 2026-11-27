#!/usr/bin/env python3
"""Does the DSP parameter channel need the bulk handshake first?

Universal Control's device layer has three call shapes we have not combined:

    0xC1 0x00  IN  wValue 0        bulk protocol version (expect 1.x)
    0xC1 0x01  IN  wValue 0 / 1    max command / max response length
    0xD1 OUT + 0xD2 IN             DSP blob read (stalls for us today)

The working theory: 0xD1 is refused until the host has introduced itself with
the 0xC1 requests. This does the handshake, then retries the read, and prints
every step so a stall is attributable to one call rather than the whole chain.

    ./.venv/bin/python tools/probe_dsp_handshake.py
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import uc1810c as uc

VENDOR_IFACE = 5          # App-Specific interface (class 254), no endpoints


def show(label, fn):
    try:
        value = fn()
        print("  %-42s OK   %s" % (label, value))
        return value
    except Exception as exc:
        print("  %-42s FAIL %s" % (label, exc))
        return None


def main():
    dev = uc.Dev()
    d = dev.dev

    print("bulk / DSP handshake, interface %d\n" % VENDOR_IFACE)

    version = show("0xC1 0x00 version (2 bytes)",
                   lambda: d.ctrl_transfer(uc.RT_IN_IF, 0x00, 0, VENDOR_IFACE, 2,
                                           timeout=2000))

    if version:
        v = struct.unpack("<H", bytes(version))[0]
        print("      protocol version = %d.%d" % (v >> 8, v & 0xFF))

    max_cmd = show("0xC1 0x01 wValue=0 max command len",
                   lambda: d.ctrl_transfer(uc.RT_IN_IF, 0x01, 0, VENDOR_IFACE, 4,
                                           timeout=2000))
    max_rsp = show("0xC1 0x01 wValue=1 max response len",
                   lambda: d.ctrl_transfer(uc.RT_IN_IF, 0x01, 1, VENDOR_IFACE, 4,
                                           timeout=2000))
    for label, raw in (("max command", max_cmd), ("max response", max_rsp)):
        if raw:
            print("      %s = %d bytes" % (label, struct.unpack("<I", bytes(raw))[0]))

    print("\nDSP blob read (0xD1 out, 0xD2 in):")
    for length in (8, 64, 252):
        seq = 1
        ok_out = show("0xD1 OUT seq=%d len=%d" % (seq, length),
                      lambda: dev._out(0xD1, bytes(length), wvalue=seq))
        if ok_out is None:
            continue
        data = show("0xD2 IN  seq=%d len=%d" % (seq, length),
                    lambda: dev._in(0xD2, length, wvalue=seq))
        if data:
            print("      first bytes: %s" % bytes(data[:16]).hex())
            break


if __name__ == "__main__":
    main()
