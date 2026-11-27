#!/usr/bin/env python3
"""End-to-end proof that OUR 0xA0 writes reach the device, with the kernel's
ALSA controls acting as an independent read-back of the same state packet."""
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import uc1810c as uc


def amixer(numid):
    out = subprocess.run(["amixer", "-D", "hw:2", "cget", "numid=%d" % numid],
                         capture_output=True, text=True).stdout
    m = re.search(r"values=(\d+)", out)
    return int(m.group(1)) if m else -1


def amixer_set(numid, value):
    subprocess.run(["amixer", "-D", "hw:2", "cset", "numid=%d" % numid, str(value)],
                   capture_output=True, text=True)


def main():
    d = uc.Dev()
    checks = [("A/B headphone route", uc.CTL_AB_SW, 62, 7),
              ("Line 1/2 source", uc.CTL_LINE_SW, 59, 4)]

    # clean slate
    for _, ctl, _, _ in checks:
        d.set_switch(ctl, 0)
    time.sleep(0.3)

    print("baseline: our state[58..62] = %s | alsa ab=%d line=%d"
          % (d.read_state()[58:63], amixer(7), amixer(4)))

    ok = True
    for label, ctl, field, numid in checks:
        for value in (1, 0):
            d.set_switch(ctl, value)
            time.sleep(0.35)
            ours = d.read_state()[field]
            alsa = amixer(numid)
            agree = (ours == value) and (alsa == value)
            ok = ok and agree
            print("  %-22s write ctl=%d val=%d -> our state[%d]=%d, alsa numid=%d reads %d  %s"
                  % (label, ctl, value, field, ours, numid, alsa,
                     "OK" if agree else "MISMATCH"))

    print("\nfinal: our state[58..62] = %s | alsa ab=%d line=%d"
          % (d.read_state()[58:63], amixer(7), amixer(4)))
    print("\nRESULT:", "0xA0 encoder confirmed against hardware by an independent reader"
          if ok else "still disagreeing")


if __name__ == "__main__":
    main()
