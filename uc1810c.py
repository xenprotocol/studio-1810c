#!/usr/bin/env python3
"""
uc1810c - userspace control tool for the PreSonus / Fender Studio 1810c on Linux.

Why this exists
---------------
Linux (sound/usb/mixer_s1810c.c) only exposes four front-panel switches and
hard-wires the internal mixer to a "everything split, DAW 1-8 straight out"
bypass at probe time.  The 18x10 routing matrix, the output faders and the
device's clock/status readback are all behind vendor USB control requests that
ALSA never issues.  This tool speaks that protocol directly from userspace.
It does not touch the audio streams: snd-usb-audio keeps handling those.

Protocol provenance
-------------------
* Requests 0xA0 / 0xA1 / 0xA2 and the packet layouts were documented by Nick
  Kossifidis in the Linux kernel driver (mixer_s1810c.c), from usbmon captures
  of the Windows driver + Universal Control.
* Requests 0xA4 (clock status), 0x42 / 0x43 (audio mode), 0xB1, 0xD0-0xD4 (DSP
  parameter channel) and the model/PID table were recovered by static
  analysis of Universal Control 5.1.1 (Fender_Universal_Control_v5_1_1.dmg):
  Daemon .../ucdaemon.bundle/Contents/hwaccess/dspusbdevice.dylib,
  x86_64 slice, functions 0x7da50-0x7e0b0, 0x81d50, 0x82570, 0x82920.
  Model table: FUN_0006f760 -> 0x1194f010c = "Studio 1810c" (family 4, Demeter).

All traffic is vendor control transfers on EP0, so it works while
snd-usb-audio owns the streaming interfaces.
"""

import argparse
import glob
import json
import math
import os
import struct
import subprocess
import sys

def _ensure_pyusb():
    """Re-exec into ./.venv if the system python has no pyusb (PEP 668 hosts)."""
    try:
        import usb.core  # noqa: F401
    except ImportError:
        here = os.path.dirname(os.path.abspath(__file__))
        venv = os.path.join(here, ".venv", "bin", "python")
        venv_root = os.path.join(here, ".venv")
        if (os.path.exists(venv) and not os.environ.get("UC1810C_REEXEC")
                and os.path.realpath(sys.prefix) != os.path.realpath(venv_root)):
            os.environ["UC1810C_REEXEC"] = "1"
            os.execv(venv, [venv, os.path.abspath(__file__)] + sys.argv[1:])
        raise SystemExit("pyusb missing: python3 -m venv .venv && ./.venv/bin/pip install pyusb")


_ensure_pyusb()

VID = 0x194F
PID_1810C = 0x010C
MODEL_1810C = 0x1194F010C  # (VID << 16 | PID) | 0x100000000, as UC encodes it

# ---- control requests -------------------------------------------------------
RT_OUT = 0x40          # vendor | recipient device | host->device
RT_IN = 0xC0           # vendor | recipient device | device->host

REQ_CMD = 0xA0         # 28-byte "command" packet (mixer cell / output / device ctl)
REQ_SET_STATE = 0xA1   # OUT, wValue = sequence number, 252-byte state packet
REQ_GET_STATE = 0xA2   # IN,  wValue = same sequence number
REQ_CLOCK_STATUS = 0xA4  # IN,  wValue = clock source + 1 (1..3), 8 bytes
RT_IN_IF = 0xC1          # vendor | interface | device-to-host
LEGACY_CTL_IFACE = 3     # the UAC1.0 control interface; 0xA4 only answers here
REQ_AUDIO_MODE_SET = 0x42  # OUT, wIndex = mode (0/1 for Studio series)
REQ_AUDIO_MODE_GET = 0x43  # IN,  wValue = 0x0AFF + source*0x100 on other models
REQ_B1 = 0xB1          # IN, 2 bytes (family specific status)
REQ_DSP_WRITE = 0xD0   # OUT, DSP parameter blob
REQ_DSP_SET = 0xD1     # OUT, wValue = sequence number
REQ_DSP_GET = 0xD2     # IN,  wValue = same sequence number
REQ_DSP_STATUS = 0xD4  # IN,  wValue = 10..13, 8 bytes

TAG_CMD = 0x50617269   # 'Pari'
TAG_STATE = 0x64656D73  # 'dems'
CMD_LEN = 0x14
STATE_LEN = 0xF4
STATE_FIELDS = 63
STATE_BYTES = STATE_FIELDS * 4  # 252: what the kernel sends/reads

SEL_DEVICE = 0x00
SEL_MIXER = 0x64
SEL_OUTPUT = 0x65

CTL_LINE_SW = 0
CTL_MUTE_SW = 1
CTL_MONO_SW = 2      # 1824c only
CTL_AB_SW = 3
CTL_48V_SW = 4

ST_48V, ST_LINE, ST_MUTE, ST_MONO, ST_AB = 58, 59, 60, 61, 62
STATE_NAMES = {ST_48V: "48v", ST_LINE: "line", ST_MUTE: "mute",
               ST_MONO: "mono (1824c)", ST_AB: "headphone A/B"}

UNIT_0DB = 0x01000000   # 2**24
MUTE = 0

OUT_PAIRS = ["Main", "Line 1/2", "Line 3/4", "S/PDIF",
             "Out 4", "Out 5", "Out 6", "Out 7", "Out 8"]


def db_to_raw(db):
    """Slider dB -> 2**24 * 10**(dB/20). 0 dB = 0x1000000, -inf = 0."""
    if db is None or db <= -99.0:
        return MUTE
    return int(round(UNIT_0DB * (10.0 ** (db / 20.0))))


def raw_to_db(raw):
    if raw <= 0:
        return float("-inf")
    return 20.0 * math.log10(raw / float(UNIT_0DB))


def input_name(ch):
    if 0 <= ch <= 7:
        return "Analog %d" % (ch + 1)
    if ch in (8, 9):
        return "S/PDIF %d" % (ch - 7)
    if 10 <= ch <= 17:
        return "ADAT %d" % (ch - 9)
    if 18 <= ch <= 35:
        return "DAW %d" % (ch - 17)
    return "In %d" % ch


class DryRun(Exception):
    pass


class Dev:
    def __init__(self, pid=PID_1810C, dry_run=False, verbose=False, echo=None):
        self.dry = dry_run
        self.verbose = verbose
        self.echo = verbose if echo is None else echo
        self.seq = 1
        self.dsp_seq = 1
        self.dev = None
        self.log = []
        if dry_run:
            return
        import usb.core
        try:
            self.dev = usb.core.find(idVendor=VID, idProduct=pid)
        except usb.core.USBError as exc:
            raise SystemExit("USB access denied (%s) - install 99-presonus-1810c.rules "
                             "or run as root." % exc)
        if self.dev is None:
            raise SystemExit(
                "no %04x:%04x device found - plug the interface in (or see `--dry-run`)."
                % (VID, pid))
        try:
            self.dev.set_configuration()
        except Exception:
            pass  # already configured by snd-usb-audio

    # -- primitives ---------------------------------------------------
    def _out(self, req, data, wvalue=0, windex=0):
        if self.echo:
            print("  OUT bmRequestType=%#04x bRequest=%#04x wValue=%#06x "
                  "wIndex=%#06x len=%d %s"
                  % (RT_OUT, req, wvalue, windex, len(data), bytes(data).hex()),
                  file=sys.stderr)
        self.log.append(("out", req, wvalue, windex, bytes(data)))
        if self.dry:
            return 0
        return self.dev.ctrl_transfer(RT_OUT, req, wvalue, windex, data, timeout=2000)

    def _in(self, req, length, wvalue=0, windex=0, rt=RT_IN):
        if self.echo:
            print("  IN  bmRequestType=%#04x bRequest=%#04x wValue=%#06x "
                  "wIndex=%#06x len=%d" % (rt, req, wvalue, windex, length),
                  file=sys.stderr)
        if self.dry:
            buf = bytes(length)
        else:
            buf = bytes(self.dev.ctrl_transfer(rt, req, wvalue, windex,
                                               length, timeout=2000))
        self.log.append(("in", req, wvalue, windex, buf))
        return buf

    # -- documented requests ------------------------------------------
    def cmd(self, selector, b=0, c=0, d=0, e=0):
        pkt = struct.pack("<7I", selector, b, TAG_CMD, CMD_LEN, c, d, e)
        return self._out(REQ_CMD, pkt)

    def read_state(self):
        # fields[0] must stay 0: the device stalls the SET if it carries anything
        # (the kernel zeroes the whole packet and only sets tag+len).
        pkt = bytearray(STATE_BYTES)
        struct.pack_into("<I", pkt, 8, TAG_STATE)
        struct.pack_into("<I", pkt, 12, STATE_LEN)
        self._out(REQ_SET_STATE, bytes(pkt), wvalue=self.seq)
        raw = self._in(REQ_GET_STATE, STATE_BYTES, wvalue=self.seq)
        self.seq = (self.seq + 1) & 0xFFFF or 1
        if len(raw) < STATE_BYTES:
            raw = raw + bytes(STATE_BYTES - len(raw))
        return list(struct.unpack("<%dI" % STATE_FIELDS, raw))

    def read_dsp_blob(self, length):
        """GetDspParameters: 0xD1 OUT (sequence) then 0xD2 IN (same sequence)."""
        hdr = bytes(length)  # UC sends a zeroed frame; the device answers with data
        self._out(REQ_DSP_SET, hdr, wvalue=self.dsp_seq)
        raw = self._in(REQ_DSP_GET, length, wvalue=self.dsp_seq)
        self.dsp_seq = (self.dsp_seq + 1) & 0xFFFF or 1
        return raw

    def write_dsp_blob(self, data):
        return self._out(REQ_DSP_WRITE, bytes(data))

    def clock_status(self, source=0):
        """0xA4: wValue = source+1, 8 bytes, addressed to the legacy UAC1.0
        control interface (3). Device-recipient stalls; interface 3 answers."""
        raw = self._in(REQ_CLOCK_STATUS, 8, wvalue=(source & 0xFFFF) + 1,
                       windex=LEGACY_CTL_IFACE, rt=RT_IN_IF)
        raw = raw + bytes(max(0, 8 - len(raw)))
        value, locked = struct.unpack("<IB3x", raw[:8])
        return {"source": source, "value": value, "locked": bool(locked)}

    def audio_mode(self):
        raw = self._in(REQ_B1, 2)
        return struct.unpack("<H", (raw + b"\0\0")[:2])[0]

    # -- high level ---------------------------------------------------
    def set_mixer(self, in_ch, pair, side, level):
        self.cmd(SEL_MIXER, in_ch, pair, 1 if side == "R" else 0, level)

    def set_output(self, pair, side, level):
        self.cmd(SEL_OUTPUT, pair, 0, 1 if side == "R" else 0, level)

    def set_switch(self, ctl_id, value):
        self.cmd(SEL_DEVICE, 0, 0, ctl_id, 1 if value else 0)

    def reset_routing(self, in_count=36, pairs=len(OUT_PAIRS)):
        """Kernel-equivalent wiring: outputs at unity, DAW 1-8 -> Main/Line/SPDIF,
        every other matrix cell muted."""
        for pair in range(pairs):
            for side in ("L", "R"):
                self.set_output(pair, side, UNIT_0DB)
        for pair in range(pairs):
            for ch in range(in_count):
                for side in ("L", "R"):
                    self.set_mixer(ch, pair, side, MUTE)
        for pair in range(4):
            left = 18 + 2 * pair
            self.set_mixer(left, pair, "L", UNIT_0DB)
            self.set_mixer(left + 1, pair, "R", UNIT_0DB)


def parse_input(s):
    s = s.strip().lower().replace(" ", "")
    if s.isdigit():
        return int(s)
    for key, base in (("analog", 0), ("mic", 0), ("inst", 0), ("line", 0),
                      ("spdif", 8), ("adat", 10), ("daw", 18), ("usb", 18)):
        if s.startswith(key):
            n = s[len(key):] or "1"
            return base + int(n) - 1
    raise SystemExit("unknown input %r (try: analog1, spdif1, adat3, daw2, or 0-35)" % s)


def parse_pair(s):
    s = s.strip().lower().replace(" ", "")
    if s.isdigit():
        return int(s)
    table = {"main": 0, "1/2": 1, "line1/2": 1, "3/4": 2, "line3/4": 2,
             "spdif": 3, "5/6": 4, "line5/6": 4}
    if s not in table:
        raise SystemExit("unknown output pair %r (main, 1/2, 3/4, spdif, or 0-8)" % s)
    return table[s]


def fmt_state(fields):
    print("state packet (0xA1/0xA2), %d x u32:" % len(fields))
    for i, v in enumerate(fields):
        name = STATE_NAMES.get(i, "")
        shows = ""
        if name:
            shows = "  <- %s = %s" % (name, "ON" if v else "off")
        print("  [%2d] 0x%08x %10d%s" % (i, v, v, shows))
    print("\nFields 0-57 are the DSP parameter block; 58-62 are the front-panel "
          "switches the kernel also decodes. Dump twice with a switch toggled and "
          "diff to map the rest.")


def alsa_card(pid=PID_1810C):
    """Card index whose usbid matches our VID:PID, or None."""
    want = "%04x:%04x" % (VID, pid)
    for path in sorted(glob.glob("/proc/asound/card*/usbid")):
        try:
            if open(path).read().strip().lower() == want:
                return int(path.split("card")[1].split("/")[0])
        except (OSError, ValueError):
            continue
    return None


def amixer_run(card, *args):
    if card is None:
        return ""
    try:
        return subprocess.run(["amixer", "-D", "hw:%d" % card] + list(args),
                              capture_output=True, text=True, timeout=5).stdout
    except (FileNotFoundError, subprocess.SubprocessError):
        return ""


def alsa_value(numid, card=None):
    """Read an ALSA control value, parsed from the ': values=N' line only."""
    import re
    out = amixer_run(card if card is not None else alsa_card(), "cget", "numid=%d" % numid)
    m = re.search(r"^\s*:\s*values=(\d+)", out, re.M)
    return int(m.group(1)) if m else None


def doctor(dev, pid):
    print("uc1810c doctor")
    lsusb = subprocess.run(["lsusb", "-d", "%04x:%04x" % (VID, pid)],
                           capture_output=True, text=True).stdout.strip()
    print("  usb device :", lsusb or "NOT FOUND")
    tree = subprocess.run(["lsusb", "-t"], capture_output=True, text=True).stdout
    driver = "snd-usb-audio" if "snd-usb-audio" in tree else "not bound"
    print("  driver     :", driver)
    cards = []
    for c in sorted(glob.glob("/proc/asound/card*")):
        try:
            name = open(os.path.join(c, "id")).read().strip()
        except OSError:
            continue
        cards.append("%s=%s" % (os.path.basename(c), name))
    print("  alsa cards :", ", ".join(cards) or "none")
    card = alsa_card(pid)
    out = amixer_run(card, "scontents")
    ctl = [l.strip().replace("Simple mixer control ", "")
           for l in out.splitlines() if l.startswith("Simple mixer control")]
    print("  kernel ctls:", ("card %d: " % card if card is not None else "") +
          ("; ".join(ctl) if ctl else "none readable"))
    try:
        params = open("/sys/module/snd_usb_audio/parameters/device_setup").read().strip()
        print("  device_setup:", params)
    except OSError:
        print("  device_setup: (module parameter not exposed)")
    node = "/dev/bus/usb/%03d/%03d" % (dev.dev.bus, dev.dev.address) if dev.dev else None
    if node:
        print("  usbfs node :", node, "writable" if os.access(node, os.W_OK) else "NOT writable (need udev rule)")
    print("\n  Hint: at 96 kHz the 1810c runs 8 out / 14 in, at 192 kHz 6 out / 8 in;"
          "\n  `device_setup` selects the ALTSET the kernel keeps. Rate is chosen by"
          "\n  the ALSA client, not by this tool.")


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="uc1810c",
        description="Studio 1810c mixer/switch control for Linux (vendor USB protocol).")
    ap.add_argument("--pid", type=lambda s: int(s, 0), default=PID_1810C)
    ap.add_argument("--dry-run", action="store_true", help="print transfers, send nothing")
    ap.add_argument("-v", "--verbose", action="store_true", help="hex-dump every transfer")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="USB/ALSA/permission status")
    p = sub.add_parser("state", help="read the 252-byte state packet")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("mix", help="set one matrix cell: input -> output pair")
    p.add_argument("input", help="analog1..8, spdif1/2, adat1..8, daw1..18 or 0-35")
    p.add_argument("pair", help="main, 1/2, 3/4, spdif or 0-8")
    p.add_argument("side", nargs="?", default="LR", choices=["L", "R", "LR"])
    p.add_argument("db", type=float, help="gain in dB; -100 or below = mute")

    p = sub.add_parser("out", help="set an output-pair fader")
    p.add_argument("pair")
    p.add_argument("side", nargs="?", default="LR", choices=["L", "R", "LR"])
    p.add_argument("db", type=float)

    p = sub.add_parser("switch", help="48v / line / ab / mute / mono")
    p.add_argument("name", choices=["48v", "line", "ab", "mute", "mono"])
    p.add_argument("value", choices=["on", "off", "1", "0"])

    sub.add_parser("reset-routing", help="apply the kernel's default direct routing")

    sub.add_parser("verify", help="prove the 0xA0 encoder round-trips on this device")

    p = sub.add_parser("clock", help="read clock-lock status (0xA4)")
    p.add_argument("source", nargs="?", default="0",
                   help="0 = internal, 1 = S/PDIF, 2 = ADAT")

    p = sub.add_parser("blob", help="read the DSP parameter blob (0xD1/0xD2)")
    p.add_argument("--length", type=int, default=256)
    p.add_argument("--out", help="write raw bytes to this file")

    p = sub.add_parser("raw", help="raw vendor control transfer (escape hatch)")
    p.add_argument("req", type=lambda s: int(s, 0))
    p.add_argument("value", type=lambda s: int(s, 0), nargs="?", default=0)
    p.add_argument("index", type=lambda s: int(s, 0), nargs="?", default=0)
    p.add_argument("--in", dest="length", type=lambda s: int(s, 0), default=0,
                   help="read direction, N bytes")
    p.add_argument("--hex", default="", help="payload bytes for OUT, hex string")

    args = ap.parse_args(argv)
    dev = Dev(pid=args.pid, dry_run=args.dry_run, verbose=args.verbose)

    def sides(s):
        return ("L", "R") if s in ("LR", "both") else (s,)

    if args.cmd == "doctor":
        doctor(dev, args.pid)

    elif args.cmd == "state":
        f = dev.read_state()
        if args.json:
            print(json.dumps({"fields": f}))
        else:
            fmt_state(f)

    elif args.cmd == "mix":
        ch = parse_input(args.input)
        pair = parse_pair(args.pair)
        lvl = db_to_raw(args.db)
        if ch > 35:
            raise SystemExit("input channel out of range (0-35)")
        for s in sides(args.side):
            dev.set_mixer(ch, pair, s, lvl)
        print("%s -> %s [%s] = %.2f dB (raw %#x)"
              % (input_name(ch), OUT_PAIRS[pair], args.side, args.db, lvl))

    elif args.cmd == "out":
        pair = parse_pair(args.pair)
        lvl = db_to_raw(args.db)
        for s in sides(args.side):
            dev.set_output(pair, s, lvl)
        print("%s [%s] = %.2f dB (raw %#x)" % (OUT_PAIRS[pair], args.side, args.db, lvl))

    elif args.cmd == "switch":
        ctl = {"48v": CTL_48V_SW, "line": CTL_LINE_SW, "ab": CTL_AB_SW,
               "mute": CTL_MUTE_SW, "mono": CTL_MONO_SW}[args.name]
        val = args.value in ("on", "1")
        dev.set_switch(ctl, val)
        print("%s -> %s" % (args.name, "on" if val else "off"))

    elif args.cmd == "reset-routing":
        dev.reset_routing()
        print("default routing applied (%d packets)" % len(dev.log))

    elif args.cmd == "verify":
        print("0xA0 round-trip check (our write -> device -> state read)")
        ok = True
        for label, ctl, field, numid in (("headphone A/B", CTL_AB_SW, ST_AB, 7),
                                         ("line 1/2 source", CTL_LINE_SW, ST_LINE, 4)):
            for value in (1, 0):
                dev.set_switch(ctl, value)
                import time
                time.sleep(0.35)
                ours = dev.read_state()[field]
                alsa = alsa_value(numid)
                good = ours == value and (alsa is None or alsa == value)
                ok = ok and good
                print("  %-16s ctl=%d -> %d | state[%d]=%d alsa=%s %s"
                      % (label, ctl, value, field, ours,
                         "n/a" if alsa is None else alsa, "OK" if good else "MISMATCH"))
        print("\n", "PASS - encoder verified against hardware" if ok else "FAIL")

    elif args.cmd == "clock":
        src = int(args.source, 0) if args.source.lower().startswith("0x") else int(args.source)
        print(json.dumps(dev.clock_status(src)))

    elif args.cmd == "blob":
        data = dev.read_dsp_blob(args.length)
        if args.out:
            with open(args.out, "wb") as fh:
                fh.write(data)
            print("wrote %d bytes to %s" % (len(data), args.out))
        else:
            for off in range(0, len(data), 16):
                chunk = data[off:off + 16]
                print("%04x  %-47s  %s" % (off, chunk.hex(" "),
                                           "".join(chr(c) if 32 <= c < 127 else "." for c in chunk)))

    elif args.cmd == "raw":
        if args.length:
            data = dev._in(args.req, args.length, wvalue=args.value, windex=args.index)
            print(data.hex())
        else:
            payload = bytes.fromhex(args.hex) if args.hex else b""
            dev._out(args.req, payload, wvalue=args.value, windex=args.index)
            print("sent %d bytes" % len(payload))


if __name__ == "__main__":
    main()
