#!/usr/bin/env python3
"""Level metering for the Studio 1810c, taken from PipeWire.

The interface's firmware does not report levels to the host (see the metering
section of PROTOCOL.md), so the meters are computed from the audio that PipeWire
is already moving. PipeWire shares the device, so this works while a DAW is
recording or playing - nothing is opened exclusively and no ALSA device is
stolen.

Two nodes are read:

  * the interface's capture node  - the physical inputs (14 channels at 96 kHz)
  * the monitor of its playback sink - what is being sent to the outputs
    (8 channels: Main, Line 1/2, Line 3/4, S/PDIF)

Levels are true peak, converted to dBFS, with a short hold and a slow release so
they read like hardware meters instead of flickering.
"""
import array
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time

FRAMES = 512                  # per read block
HOLD_S = 0.20                 # peak hold
RELEASE_DB_S = 14.0           # how fast the bar falls
FLOOR_DB = -96.0
DEVICE_HINT = os.environ.get("UC_METER_DEVICE", "Studio_1810c")

# The kernel exposes the 8 playback channels with generic surround positions:
#   PCM 1/2 = FL/FR, 3/4 = FC/LFE, 5/6 = RL/RR, 7/8 = FLC/FRC
# PipeWire relabels the node as FL FR RL RR FC LFE SL SR, so the pairs land in a
# different order than PCM. This is the PCM order, used to place meter bars on
# the right output pair.
PCM_POSITIONS = ["FL", "FR", "FC", "LFE", "RL", "RR", "FLC", "FRC"]


# pacat spells channel positions out; PipeWire uses short codes
PACAT_NAMES = {
    "FL": "front-left", "FR": "front-right", "FC": "front-center",
    "LFE": "lfe", "RL": "rear-left", "RR": "rear-right", "RC": "rear-center",
    "SL": "side-left", "SR": "side-right", "TC": "top-center",
    "TFL": "top-front-left", "TFC": "top-front-center", "TFR": "top-front-right",
    "TRL": "top-rear-left", "TRR": "top-rear-right", "MONO": "mono",
}


def _pacat_map(positions):
    try:
        return ",".join(PACAT_NAMES[p.upper()] for p in positions)
    except KeyError:
        return ""


def _read_exact(stream, size):
    """Read exactly size bytes: a pipe read may return a short chunk."""
    chunks = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=4).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _pw_nodes():
    """Every PipeWire node as {name, class, channels}, straight from pw-dump."""
    out = _run(["pw-dump"])
    if not out.strip():
        return []
    try:
        data = json.loads(out)
    except ValueError:
        return []
    nodes = []
    for entry in data:
        info = entry.get("info") or {}
        props = info.get("props") or {}
        name = props.get("node.name")
        if not name:
            continue
        try:
            channels = int(props.get("audio.channels") or 0)
        except (TypeError, ValueError):
            channels = 0
        positions = props.get("audio.position") or []
        if isinstance(positions, str):
            positions = [p.strip() for p in positions.strip("[]").split(",") if p.strip()]
        nodes.append({"name": name, "class": props.get("media.class") or "",
                      "channels": channels, "positions": positions})
    return nodes


def find_nodes(hint=DEVICE_HINT):
    """Return (input_source, output_monitor, channels) for the device, or None."""
    src = os.environ.get("UC_METER_INPUT")
    mon = os.environ.get("UC_METER_OUTPUT")
    if src and mon:
        return src, mon, None, None

    best_src = best_mon = None
    for node in _pw_nodes():
        if hint.lower() not in node["name"].lower():
            continue
        cls = node["class"]
        # a source node captures audio; a sink's monitor reflects what it sends
        if cls.startswith("Audio/Source") and not node["name"].endswith(".monitor"):
            if best_src is None or node["channels"] > best_src["channels"]:
                best_src = node
        elif cls.startswith("Audio/Sink"):
            candidate = {"name": node["name"] + ".monitor",
                         "channels": node["channels"],
                         "positions": node["positions"]}
            if best_mon is None or candidate["channels"] > best_mon["channels"]:
                best_mon = candidate

    if not src and best_src:
        src = best_src["name"]
    if not mon and best_mon:
        mon = best_mon["name"]
    return src, mon, best_src, best_mon


class Channel:
    __slots__ = ("db", "held", "held_at")

    def __init__(self):
        self.db = FLOOR_DB
        self.held = FLOOR_DB
        self.held_at = 0.0


class MeterSource:
    """One PipeWire node being metered."""

    def __init__(self, name, channels, positions=None, refresh=None):
        self.name = name
        self.channels = channels
        self.positions = positions or []
        self.refresh = refresh          # re-reads the node before each restart
        self.level = [Channel() for _ in range(channels)]
        self.rate = 0.0
        self.ok = False
        self.note = "starting"
        self._stop = False
        self._thread = None

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._supervise, daemon=True)
            self._thread.start()

    def stop(self):
        self._stop = True

    # -- internals ---------------------------------------------------------
    def _supervise(self):
        while not self._stop:
            try:
                self._capture()
            except Exception as exc:                  # noqa: BLE001
                self.note = str(exc)
                self.ok = False
            if not self._stop:
                time.sleep(2.0)                       # node appeared/disappeared

    def _refresh_layout(self):
        """A rate/altset change can alter the channel count; re-read it.

        Reconnecting with the old count would either fail or read the wrong
        channels, and the meters would lie instead of breaking.
        """
        if not self.refresh:
            return
        try:
            spec = self.refresh()
        except Exception:
            return
        if not spec:
            return
        name, channels, positions = spec
        if channels and channels != self.channels:
            self.channels = channels
            self.level = [Channel() for _ in range(channels)]
        if positions:
            self.positions = positions
        if name:
            self.name = name

    def _capture(self):
        self._refresh_layout()
        pw_cat = shutil.which("pw-cat") or shutil.which("pw-record")
        parec = shutil.which("parec")
        if not pw_cat and not parec:
            self.note = "neither pw-cat nor parec is installed"
            self.ok = False
            return

        has_positions = bool(self.positions) and len(self.positions) == self.channels
        # parec is the reliable reader; pw-cat stays as a fallback for systems
        # where pactl/pulse compatibility is absent
        if pw_cat and not parec:
            # pw-cat speaks PipeWire positions natively and keeps channel order
            cmd = [pw_cat, "--record", "--target", self.name, "--format", "f32",
                   "--rate", "48000", "--channels", str(self.channels)]
            if has_positions:
                cmd += ["--channel-map", ",".join(self.positions)]
            cmd.append("-")
        else:
            cmd = [parec, "--device=" + self.name, "--format=float32le",
                   "--rate=48000", "--channels=%d" % self.channels,
                   "--latency-msec=25"]
            mapping = _pacat_map(self.positions) if has_positions else ""
            if mapping:
                cmd.append("--channel-map=" + mapping)
            cmd.append("--raw")

        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL)
        self.ok = True
        self.note = "ok"
        block = FRAMES * self.channels * 4
        started = time.time()
        frames = 0
        try:
            while not self._stop:
                buf = _read_exact(proc.stdout, block)
                if not buf or len(buf) < block:
                    self.note = "stream ended"
                    break
                samples = array.array("f")
                samples.frombytes(buf)
                self._update(samples)
                frames += FRAMES
                elapsed = time.time() - started
                if elapsed > 1.0:
                    self.rate = frames / elapsed
                    started = time.time()
                    frames = 0
        finally:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except (subprocess.SubprocessError, OSError):
                try:
                    proc.kill()
                except OSError:
                    pass

    def _update(self, samples):
        now = time.time()
        n = self.channels
        for c in range(n):
            col = samples[c::n]
            try:
                hi = max(col)
                lo = min(col)
            except ValueError:
                continue
            peak = hi if hi > -lo else -lo
            db = 20 * math.log10(peak) if peak > 1e-7 else FLOOR_DB
            ch = self.level[c]
            if db >= ch.held - 0.5:
                ch.held = db
                ch.held_at = now
            elif now - ch.held_at > HOLD_S:
                ch.held = max(db, ch.held - RELEASE_DB_S * (now - ch.held_at))
                ch.held_at = now
            ch.db = db


class Meters:
    """Both meter sources, discovered lazily and restarted if they vanish."""

    def __init__(self, start=True):
        self.inputs = None
        self.outputs = None
        self.note = ""
        self._discovered = False
        if start:
            self.discover()

    def discover(self):
        src, mon, src_node, mon_node = find_nodes()
        if src and not self.inputs:
            channels = (src_node or {}).get("channels") or 2
            self.inputs = MeterSource(src, channels, (src_node or {}).get("positions"),
                                      refresh=lambda: self._spec("input"))
            self.inputs.start()
        if mon and not self.outputs:
            channels = (mon_node or {}).get("channels") or 2
            self.outputs = MeterSource(mon, channels, (mon_node or {}).get("positions"),
                                       refresh=lambda: self._spec("output"))
            self.outputs.start()
        self._discovered = bool(src or mon)
        if not self._discovered:
            self.note = ("no PipeWire node matched %r - is PipeWire running?"
                         % DEVICE_HINT)
        elif not src:
            self.note = "no input source found"
        elif not mon:
            self.note = "no output monitor found"

    def _spec(self, kind):
        """Current (name, channels, positions) for input or output."""
        src, mon, src_node, mon_node = find_nodes()
        if kind == "input" and src:
            return (src, (src_node or {}).get("channels") or 0,
                    (src_node or {}).get("positions"))
        if kind == "output" and mon:
            return (mon, (mon_node or {}).get("channels") or 0,
                    (mon_node or {}).get("positions"))
        return None

    def snapshot(self):
        if not self._discovered:
            self.discover()

        def levels(src):
            if src is None:
                return []
            return [round(ch.held, 1) for ch in src.level]

        return {
            "inputs": levels(self.inputs),
            "outputs": levels(self.outputs),
            "input_positions": self.inputs.positions if self.inputs else [],
            "output_positions": self.outputs.positions if self.outputs else [],
            "input_source": self.inputs.name if self.inputs else None,
            "output_source": self.outputs.name if self.outputs else None,
            "input_ok": bool(self.inputs and self.inputs.ok),
            "output_ok": bool(self.outputs and self.outputs.ok),
            "note": self.note,
        }

    def output_pairs(self):
        """Index pairs in the meter arrays for output pairs 0..3."""
        if not self.outputs:
            return []
        pos = self.outputs.positions or PCM_POSITIONS
        pairs = []
        for slot in range(4):
            wanted = (PCM_POSITIONS[slot * 2], PCM_POSITIONS[slot * 2 + 1])
            idx = []
            for want in wanted:
                if want in pos:
                    idx.append(pos.index(want))
            if len(idx) != 2:
                # unknown layout: fall back to plain PCM order
                idx = [slot * 2, slot * 2 + 1]
            pairs.append(idx)
        return pairs

    def describe(self):
        """Small, static description for /api/info."""
        snap = self.snapshot()
        return {
            "available": bool(self.inputs or self.outputs),
            "output_pairs": self.output_pairs(),
            "input_channels": self.inputs.channels if self.inputs else 0,
            "output_channels": self.outputs.channels if self.outputs else 0,
            "input_source": snap["input_source"],
            "output_source": snap["output_source"],
            "note": snap["note"],
        }

    def stop(self):
        for src in (self.inputs, self.outputs):
            if src:
                src.stop()


if __name__ == "__main__":
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0
    m = Meters()
    print("input source :", m.inputs.name if m.inputs else None,
          m.inputs.channels if m.inputs else "")
    print("output source:", m.outputs.name if m.outputs else None,
          m.outputs.channels if m.outputs else "")
    t_end = time.time() + seconds
    while time.time() < t_end:
        s = m.snapshot()
        print("  in : " + " ".join("%5.0f" % v for v in s["inputs"]))
        print("  out: " + " ".join("%5.0f" % v for v in s["outputs"]))
        time.sleep(1.0)
    m.stop()
