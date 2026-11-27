#!/usr/bin/env python3
"""Do state fields 4..11 move with playback? Tone to the S/PDIF output only.

The S/PDIF pair is the least likely output to be connected to anything audible,
so this can run without filling the room with a 1 kHz tone. Main and Line stay at
silence: if the fields react, they are output meters, and this tells us which
playback channels they follow.

    ./.venv/bin/python tools/probe_out_meter.py
"""
import array
import math
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import uc1810c as uc

RATE = 96000
OUT_CH = 8                # 96 kHz altset: 8 playback channels
TONE_CH = (6, 7)          # zero-based: presumed S/PDIF L/R
WAV = "/tmp/uc1810c_spdif.wav"


def build_wav(seconds=4.0):
    frames = array.array("i")
    n = int(RATE * seconds)
    amp = int(0.10 * 2147483647)          # -20 dBFS
    for i in range(n):
        v = int(amp * math.sin(2 * math.pi * 1000 * i / RATE))
        for c in range(OUT_CH):
            frames.append(v if c in TONE_CH else 0)
    with open(WAV, "wb") as fh:
        data_len = frames.itemsize * len(frames)
        fh.write(b"RIFF" + (36 + data_len).to_bytes(4, "little") + b"WAVE")
        fh.write(b"fmt " + (16).to_bytes(4, "little"))
        fh.write((1).to_bytes(2, "little"))            # PCM
        fh.write((OUT_CH).to_bytes(2, "little"))
        fh.write((RATE).to_bytes(4, "little"))
        fh.write((RATE * OUT_CH * 4).to_bytes(4, "little"))
        fh.write((OUT_CH * 4).to_bytes(2, "little"))
        fh.write((32).to_bytes(2, "little"))
        fh.write(b"data" + data_len.to_bytes(4, "little"))
        frames.tofile(fh)


def main():
    dev = uc.Dev()
    build_wav()

    def sample(label, seconds=1.5, hz=15):
        rows = []
        end = time.time() + seconds
        while time.time() < end:
            rows.append(dev.read_state()[4:12])
            time.sleep(1.0 / hz)
        span = []
        for k in range(8):
            col = [r[k] for r in rows]
            span.append((min(col), max(col), sum(col) // len(col)))
        print(label)
        for k, (lo, hi, mean) in enumerate(span):
            print("  field %-2d min=0x%05x max=0x%05x mean=0x%05x  swing=%d"
                  % (k + 4, lo, hi, mean, hi - lo))
        return span

    print("channels %d,%d at %d Hz, amp -20 dBFS\n" % (TONE_CH[0] + 1, TONE_CH[1] + 1, RATE))
    before = sample("SILENCE")

    player = subprocess.Popen(
        ["aplay", "-D", "hw:2", "-f", "S32_LE", "-c", str(OUT_CH), "-r", str(RATE),
         "-q", WAV],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    time.sleep(1.0)
    during = sample("TONE ON S/PDIF")
    player.wait(timeout=10)
    time.sleep(0.5)
    after = sample("SILENCE AGAIN")

    print("\nchange while the tone played (mean vs silence):")
    for k in range(8):
        d = during[k][2] - (before[k][2] + after[k][2]) // 2
        flag = "  <-- follows audio" if abs(d) > max(2000, 0.25 * before[k][2]) else ""
        print("  field %-2d %+d%s" % (k + 4, d, flag))


if __name__ == "__main__":
    main()
