#!/usr/bin/env python3
"""Are state fields 4-11 input or output meters? And does a matrix mute change them?

Phases: silence -> tone at unity -> tone with DAW1/2 muted into Main -> silence.
"""
import math
import os
import struct
import subprocess
import sys
import time
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import uc1810c as uc

WAV = "/tmp/uc1810c_tone.wav"


def make_tone(path, seconds=8.0, rate=48000, freq=1000.0):
    n = int(seconds * rate)
    amp = 0.25 * 32767
    with wave.open(path, "w") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(n):
            v = int(amp * math.sin(2 * math.pi * freq * i / rate))
            frames += struct.pack("<hh", v, v)
        w.writeframes(bytes(frames))


def sample(d, seconds=1.2, hz=12):
    rows = []
    end = time.time() + seconds
    while time.time() < end:
        rows.append(d.read_state()[4:12])
        time.sleep(1.0 / hz)
    return rows


def peak(rows, idx):
    return max(r[idx] for r in rows)


def report(label, rows):
    peaks = [peak(rows, i) for i in range(8)]
    print("  %-28s %s" % (label, ["%6d" % p for p in peaks]))
    return peaks


def main():
    if not os.path.exists(WAV):
        make_tone(WAV)
    d = uc.Dev()

    print("phase 1: silence")
    base = report("silence", sample(d))

    print("phase 2: 1 kHz tone, DAW 1/2 -> Main at unity")
    for ch in (18, 19):
        for side in ("L", "R"):
            d.set_mixer(ch, 0, side, uc.UNIT_0DB)
    p = subprocess.Popen(["aplay", "-q", "-D", "hw:2", WAV],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.8)
    tone_on = report("tone, routed", sample(d))
    p.terminate(); p.wait()
    time.sleep(0.4)

    print("phase 3: same tone, DAW 1/2 muted into Main")
    for ch in (18, 19):
        for side in ("L", "R"):
            d.set_mixer(ch, 0, side, uc.MUTE)
    p = subprocess.Popen(["aplay", "-q", "-D", "hw:2", WAV],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.8)
    tone_muted = report("tone, muted", sample(d))
    p.terminate(); p.wait()
    time.sleep(0.4)

    print("phase 4: silence again")
    quiet = report("silence", sample(d))

    print("\ninterpretation")
    for i in range(8):
        rose = tone_on[i] > base[i] * 1.5
        fell = tone_muted[i] < tone_on[i] * 0.6
        kind = "responds to tone"
        if rose and fell:
            kind += " AND to matrix mute -> output meter"
        elif rose:
            kind += " but not to mute -> input meter or pre-matrix"
        else:
            kind = "flat"
        print("  field[%d] %s (silence %d, tone %d, muted %d)"
              % (4 + i, kind, base[i], tone_on[i], tone_muted[i]))

    print("\nrestoring DAW 1/2 -> Main at unity")
    for ch in (18, 19):
        for side in ("L", "R"):
            d.set_mixer(ch, 0, side, uc.UNIT_0DB)


if __name__ == "__main__":
    main()
