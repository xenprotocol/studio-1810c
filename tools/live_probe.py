#!/usr/bin/env python3
"""One-shot live probe of a Studio 1810c: exercises every known vendor request
and diffs state/blob before and after a single matrix change.

Safe: only touches the mixer matrix cell it restores at the end, never flash.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import uc1810c as uc

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "live")
os.makedirs(OUT, exist_ok=True)


def save(name, data):
    path = os.path.join(OUT, name)
    mode = "wb" if isinstance(data, (bytes, bytearray)) else "w"
    with open(path, mode) as fh:
        fh.write(data if mode == "wb" else json.dumps(data, indent=1))
    print("  saved", path)


def main():
    dev = uc.Dev()
    print("device %04x:%04x bus %d addr %d"
          % (dev.dev.idVendor, dev.dev.idProduct, dev.dev.bus, dev.dev.address))

    print("\n[1] state packet (0xA1/0xA2)")
    state0 = dev.read_state()
    save("state_before.json", state0)
    print("  seq=%d  switches: 48v=%d line=%d mute=%d mono=%d ab=%d"
          % (state0[0], state0[58], state0[59], state0[60], state0[61], state0[62]))
    print("  nonzero fields:", [i for i, v in enumerate(state0) if v])

    print("\n[2] clock lock status (0xA4, wValue = source + 1)")
    for src, name in ((0, "internal"), (1, "S/PDIF"), (2, "ADAT")):
        try:
            print("  %-8s %s" % (name, json.dumps(dev.clock_status(src))))
        except Exception as exc:
            print("  %-8s FAILED: %s" % (name, exc))

    print("\n[3] family status word (0xB1, 2 bytes)")
    try:
        raw = dev._in(uc.REQ_B1, 2)
        print("  raw=%s  u16=%d" % (raw.hex(), int.from_bytes(raw, "little")))
    except Exception as exc:
        print("  FAILED:", exc)

    print("\n[4] DSP blob read (0xD1/0xD2)")
    blobs = {}
    for length in (64, 256, 244):
        try:
            data = dev.read_dsp_blob(length)
            blobs[length] = data
            save("blob_%d.bin" % length, data)
            nz = sum(1 for b in data if b)
            print("  len=%-4d returned=%-4d nonzero=%d" % (length, len(data), nz))
        except Exception as exc:
            print("  len=%-4d FAILED: %s" % (length, exc))

    print("\n[5] matrix write probe: DAW 1 -> Main, both sides, -20 dB")
    target_raw = uc.db_to_raw(-20.0)
    dev.set_mixer(18, 0, "L", target_raw)
    dev.set_mixer(19, 0, "R", target_raw)
    print("  wrote raw %#x twice" % target_raw)

    import time
    time.sleep(0.3)
    state1 = dev.read_state()
    save("state_after.json", state1)
    diff = [i for i in range(min(len(state0), len(state1))) if state0[i] != state1[i]]
    print("  state fields that changed:", diff or "none")
    for i in diff:
        print("    [%2d] %#x -> %#x" % (i, state0[i], state1[i]))

    for length, before in blobs.items():
        try:
            after = dev.read_dsp_blob(length)
        except Exception:
            continue
        save("blob_%d_after.bin" % length, after)
        moves = [(i, before[i], after[i]) for i in range(min(len(before), len(after)))
                 if before[i] != after[i]]
        print("  blob len=%d changed bytes: %d" % (length, len(moves)))
        if 0 < len(moves) <= 24:
            for off, b, a in moves:
                print("    %04x %02x -> %02x" % (off, b, a))
        elif moves:
            print("    first:", ["%04x" % m[0] for m in moves[:12]])

    print("\n[6] restore DAW 1/2 -> Main at unity (kernel default)")
    dev.set_mixer(18, 0, "L", uc.UNIT_0DB)
    dev.set_mixer(19, 0, "R", uc.UNIT_0DB)
    print("  restored")

    print("\ndone - artifacts in", OUT)


if __name__ == "__main__":
    main()
