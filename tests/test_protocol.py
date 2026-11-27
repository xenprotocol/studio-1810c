#!/usr/bin/env python3
"""Protocol conformance tests for uc1810c (no hardware needed).

Packets are checked byte-for-byte against the constants and call sequences in
Linux sound/usb/mixer_s1810c.c, which was itself derived from usbmon captures.
"""
import struct
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import uc1810c as uc

FAIL = []


def check(name, cond, detail=""):
    if cond:
        print("  ok   %s" % name)
    else:
        print("  FAIL %s %s" % (name, detail))
        FAIL.append(name)


def transfers(dev):
    return [(t[0], t[1], t[2], t[3], t[4]) for t in dev.log]


def test_cmd_packet():
    print("CMD packet (bRequest 0xA0)")
    d = uc.Dev(dry_run=True, echo=False)
    d.set_mixer(18, 0, "L", uc.UNIT_0DB)
    kind, req, wval, widx, data = transfers(d)[0]
    check("request code 0xA0", req == 0xA0, hex(req))
    check("bmRequestType vendor|device|out", uc.RT_OUT == 0x40)
    check("wValue 0", wval == 0)
    check("wIndex 0", widx == 0)
    check("28 bytes", len(data) == 28, len(data))
    fields = struct.unpack("<7I", data)
    sel, b, tag, ln, c, dd, e = fields
    check("selector 0x64 (mixer)", sel == 0x64, hex(sel))
    check("input channel 18 (DAW 1)", b == 18)
    check("tag 'Pari'", tag == 0x50617269, hex(tag))
    check("len field 0x14", ln == 0x14, hex(ln))
    check("output pair 0 (Main)", c == 0)
    check("side L", dd == 0)
    check("level 0 dB = 2**24", e == 0x1000000, hex(e))
    # exact byte image, little endian
    check("wire bytes", data.hex() == "64000000" "12000000" "69726150"
          "14000000" "00000000" "00000000" "00000001", data.hex())

    d = uc.Dev(dry_run=True, echo=False)
    d.set_output(3, "R", 0)
    sel, b, tag, ln, c, side, e = struct.unpack("<7I", transfers(d)[0][4])
    check("selector 0x65 (output)", sel == 0x65, hex(sel))
    check("output pair 3 (S/PDIF)", b == 3)
    check("c unused", c == 0)
    check("side R", side == 1)
    check("mute level 0", e == 0)

    d = uc.Dev(dry_run=True, echo=False)
    d.set_switch(uc.CTL_48V_SW, True)
    sel, b, tag, ln, c, ctl, val = struct.unpack("<7I", transfers(d)[0][4])
    check("selector 0 (device)", sel == 0)
    check("48V control id 4", ctl == 4)
    check("value 1", val == 1)
    check("b and c zero", b == 0 and c == 0)


def test_state_packet():
    print("STATE packet (bRequest 0xA1 then 0xA2)")
    d = uc.Dev(dry_run=True, echo=False)
    d.read_state()
    (k1, r1, v1, i1, pkt), (k2, r2, v2, i2, _) = transfers(d)[:2]
    check("first transfer is OUT 0xA1", (r1, k1) == (0xA1, "out"))
    check("second is IN 0xA2", (r2, k2) == (0xA2, "in"))
    check("same sequence number in wValue", v1 == v2 == 1, (v1, v2))
    check("wIndex 0", i1 == i2 == 0)
    check("252 bytes (63 x u32)", len(pkt) == 252, len(pkt))
    f = struct.unpack("<%dI" % uc.STATE_FIELDS, pkt)
    check("fields[0] = 0 (device stalls the SET if it carries a value)", f[0] == 0)
    check("fields[2] = tag 'dems'", f[2] == 0x64656D73, hex(f[2]))
    check("fields[3] = 0xF4", f[3] == 0xF4, hex(f[3]))
    check("only tag+len set, everything else zero (kernel behaviour)",
          all(v == 0 for i, v in enumerate(f) if i not in (2, 3)))
    # sequence increments and wraps without hitting 0xFFFF
    for _ in range(3):
        d.read_state()
    check("sequence advances", d.seq == 5, d.seq)


def test_state_names():
    print("state field indices")
    check("48V field 58", uc.ST_48V == 58)
    check("LINE field 59", uc.ST_LINE == 59)
    check("MUTE field 60", uc.ST_MUTE == 60)
    check("MONO field 61", uc.ST_MONO == 61)
    check("A/B field 62", uc.ST_AB == 62)


def test_gain_math():
    print("gain conversion (kernel reference values)")
    check("0 dB -> 0x1000000", uc.db_to_raw(0.0) == 0x1000000)
    check("-inf/mute -> 0", uc.db_to_raw(-100) == 0 and uc.db_to_raw(-99) == 0)
    v3 = uc.db_to_raw(-3.0)
    check("-3 dB near kernel's 0xb53bf0 (+-0.5%)",
          abs(v3 - 0xB53BF0) / 0xB53BF0 < 0.005, hex(v3))
    v96 = uc.db_to_raw(-96.0)
    check("-96 dB near kernel's 0x109 (+-5%)", abs(v96 - 0x109) / 0x109 < 0.05, v96)
    check("round-trip 0 dB", abs(uc.raw_to_db(uc.db_to_raw(0.0))) < 1e-9)
    check("round-trip -20 dB", abs(uc.raw_to_db(uc.db_to_raw(-20.0)) + 20.0) < 0.01)


def test_dsp_and_clock():
    print("DSP channel and clock requests")
    d = uc.Dev(dry_run=True, echo=False)
    d.read_dsp_blob(64)
    (k1, r1, v1, i1, p1), (k2, r2, v2, i2, _) = transfers(d)[:2]
    check("0xD1 OUT then 0xD2 IN", (r1, k1, r2, k2) == (0xD1, "out", 0xD2, "in"))
    check("sequence matches", v1 == v2 == 1)
    check("write frame is 64 zero bytes", len(p1) == 64 and not any(p1))

    d = uc.Dev(dry_run=True, echo=False)
    d.clock_status(2)  # ADAT
    (k, r, v, i, _) = transfers(d)[0]
    check("0xA4 IN", (r, k) == (0xA4, "in"))
    check("wValue = source+1 = 3", v == 3, v)
    check("addressed to interface 3 (only shape the device answers)", i == 3, i)
    check("reads 8 bytes", d.log[0][4] == b"\0" * 8)


def test_names():
    print("channel naming")
    check("analog1 -> 0", uc.parse_input("analog1") == 0)
    check("analog8 -> 7", uc.parse_input("analog8") == 7)
    check("spdif1 -> 8", uc.parse_input("spdif1") == 8)
    check("adat1 -> 10", uc.parse_input("adat1") == 10)
    check("daw1 -> 18", uc.parse_input("daw1") == 18)
    check("daw18 -> 35", uc.parse_input("daw18") == 35)
    check("input_name(18) DAW 1", uc.input_name(18) == "DAW 1")
    check("pair main -> 0", uc.parse_pair("main") == 0)
    check("pair spdif -> 3", uc.parse_pair("spdif") == 3)


def test_reset_routing_shape():
    print("reset-routing packet sequence")
    d = uc.Dev(dry_run=True, echo=False)
    d.reset_routing()
    outs = [t for t in transfers(d) if t[1] == 0xA0]
    check("all packets are 0xA0", len(outs) == len(d.log))
    check("count = 18 output faders + 648 matrix cells + 8 feeds = 674",
          len(d.log) == 674, len(d.log))
    last = struct.unpack("<7I", d.log[-1][4])
    check("last packet routes DAW 8 R to S/PDIF", last[0] == 0x64 and last[1] == 25
          and last[4] == 3 and last[5] == 1 and last[6] == 0x1000000, last)


if __name__ == "__main__":
    for fn in (test_cmd_packet, test_state_packet, test_state_names,
               test_gain_math, test_dsp_and_clock, test_names,
               test_reset_routing_shape):
        fn()
    print()
    if FAIL:
        print("%d FAILED: %s" % (len(FAIL), ", ".join(FAIL)))
        sys.exit(1)
    print("all checks passed")
