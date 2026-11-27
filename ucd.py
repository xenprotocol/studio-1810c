#!/usr/bin/env python3
"""
ucd - the daemon behind the Studio 1810c control surface.

Owns the USB device (one process, one lock), exposes a small JSON API on
127.0.0.1 and serves the web UI.  Start it, leave it running.

    ./ucd.py                 # http://127.0.0.1:8777
    ./ucd.py --port 9000 --no-browser
"""

import argparse
import json
import math
import os
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uc1810c as uc

APP = "1810c"
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "uc1810c"
STATE_FILE = CONFIG_DIR / "session.json"
PRESET_DIR = CONFIG_DIR / "presets"
UI_DIR = Path(__file__).resolve().parent / "ui"

PAIR_NAMES = ["Main", "Line 1/2", "Line 3/4", "S/PDIF", "Out 4", "Out 5",
              "Out 6", "Out 7", "Out 8"]
INPUT_GROUPS = [
    ("Analog", [("Analog %d" % (i + 1), i) for i in range(8)]),
    ("S/PDIF", [("S/PDIF %d" % (i + 1), 8 + i) for i in range(2)]),
    ("ADAT", [("ADAT %d" % (i + 1), 10 + i) for i in range(8)]),
    ("DAW", [("DAW %d" % (i + 1), 18 + i) for i in range(18)]),
]
INPUTS = [x for _, group in INPUT_GROUPS for x in group]


def clamp_db(db):
    return max(-96.0, min(10.0, float(db)))


def strip_levels(level_db, pan, mute):
    """Equal-power pan, -3 dB at centre exactly as the device does it.

    pan: -1.0 hard left ... 0.0 centre ... +1.0 hard right
    """
    if mute:
        return 0, 0
    theta = (pan + 1.0) * math.pi / 4.0
    left_db = level_db + (20.0 * math.log10(math.cos(theta)) if math.cos(theta) > 1e-6 else -96.0)
    right_db = level_db + (20.0 * math.log10(math.sin(theta)) if math.sin(theta) > 1e-6 else -96.0)
    return uc.db_to_raw(left_db), uc.db_to_raw(right_db)


def default_state():
    """Mirror what the kernel already programmed at probe time."""
    strips = {}
    for pair in range(4):
        for name, ch in INPUTS:
            strips["%d:%d" % (pair, ch)] = {"level_db": -96.0, "pan": 0.0, "mute": True}
        left = 18 + 2 * pair
        strips["%d:%d" % (pair, left)] = {"level_db": 0.0, "pan": -1.0, "mute": False}
        strips["%d:%d" % (pair, left + 1)] = {"level_db": 0.0, "pan": 1.0, "mute": False}
    return {
        "strips": strips,
        "outputs": {str(p): {"db": 0.0, "mute": False} for p in range(9)},
        "switches": {"48v": False, "line": False, "ab": False, "mute": False, "mono": False},
        "applied_at": None,
    }


class Surface:
    def __init__(self):
        self.lock = threading.RLock()
        self.dev = None
        self.error = None
        self.state = self._load()
        self.telemetry = [0] * 8
        self.sw_read = None
        self.sw_read_at = 0.0
        self._start_device()

    # ---- persistence ------------------------------------------------
    def _load(self):
        try:
            with open(STATE_FILE) as fh:
                data = json.load(fh)
            base = default_state()
            base["strips"].update(data.get("strips", {}))
            base["outputs"].update(data.get("outputs", {}))
            base["switches"].update(data.get("switches", {}))
            # A saved session is not a pushed session. The matrix is write-only,
            # so after a restart we cannot know what the device holds - say so.
            base["applied_at"] = None
            return base
        except (OSError, ValueError):
            return default_state()

    def save(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        with open(tmp, "w") as fh:
            json.dump(self.state, fh, indent=1)
        os.replace(tmp, STATE_FILE)

    # ---- device -----------------------------------------------------
    def _start_device(self):
        try:
            self.dev = uc.Dev()
            self.error = None
        except SystemExit as exc:
            self.dev = None
            self.error = str(exc)

    def require(self):
        if self.dev is None:
            self.error = self.error or "device not connected"
            raise RuntimeError(self.error)
        return self.dev

    def apply_all(self):
        """Push the whole session to the device."""
        dev = self.require()
        with self.lock:
            for key, strip in self.state["strips"].items():
                pair, ch = (int(x) for x in key.split(":"))
                left, right = strip_levels(strip["level_db"], strip["pan"], strip["mute"])
                dev.set_mixer(ch, pair, "L", left)
                dev.set_mixer(ch, pair, "R", right)
            for pair_s, out in self.state["outputs"].items():
                pair = int(pair_s)
                raw = 0 if out["mute"] else uc.db_to_raw(clamp_db(out["db"]))
                dev.set_output(pair, "L", raw)
                dev.set_output(pair, "R", raw)
            for name, value in self.state["switches"].items():
                ctl = {"48v": uc.CTL_48V_SW, "line": uc.CTL_LINE_SW,
                       "ab": uc.CTL_AB_SW, "mute": uc.CTL_MUTE_SW,
                       "mono": uc.CTL_MONO_SW}[name]
                dev.set_switch(ctl, bool(value))
            self.state["applied_at"] = time.strftime("%H:%M:%S")
            self.save()
        return True

    def write_strip(self, pair, ch, strip):
        dev = self.require()
        left, right = strip_levels(strip["level_db"], strip["pan"], strip["mute"])
        with self.lock:
            dev.set_mixer(ch, pair, "L", left)
            dev.set_mixer(ch, pair, "R", right)
        self.state["strips"]["%d:%d" % (pair, ch)] = strip
        self.state["applied_at"] = time.strftime("%H:%M:%S")
        self.save()

    def write_output(self, pair, out):
        dev = self.require()
        raw = 0 if out["mute"] else uc.db_to_raw(clamp_db(out["db"]))
        with self.lock:
            dev.set_output(pair, "L", raw)
            dev.set_output(pair, "R", raw)
        self.state["outputs"][str(pair)] = out
        self.state["applied_at"] = time.strftime("%H:%M:%S")
        self.save()

    def write_switch(self, name, value):
        dev = self.require()
        ctl = {"48v": uc.CTL_48V_SW, "line": uc.CTL_LINE_SW, "ab": uc.CTL_AB_SW,
               "mute": uc.CTL_MUTE_SW, "mono": uc.CTL_MONO_SW}[name]
        with self.lock:
            dev.set_switch(ctl, bool(value))
        self.state["switches"][name] = bool(value)
        self.save()

    def poll(self):
        """Cheap background read: switches + the eight unidentified values."""
        dev = self.dev
        if dev is None:
            # the interface is often plugged in after the window is already open
            now = time.time()
            if now - getattr(self, "_last_probe", 0.0) > 3.0:
                self._last_probe = now
                self._start_device()
            return
        with self.lock:
            try:
                fields = dev.read_state()
            except Exception as exc:  # unplugged or busy
                self.error = str(exc)
                return
        self.telemetry = fields[4:12]
        self.sw_read = {"48v": fields[58], "line": fields[59], "mute": fields[60],
                        "mono": fields[61], "ab": fields[62]}
        self.sw_read_at = time.time()
        self.error = None

    def info(self):
        card = uc.alsa_card()
        out = {"device": None, "card": card, "alsa": {}, "pairs": [], "inputs": [],
               "state": self.state, "telemetry": self.telemetry,
               "switches_read": self.sw_read, "error": self.error}
        if self.dev is not None:
            out["device"] = {"vid": "%04x" % uc.VID, "pid": "%04x" % uc.PID_1810C,
                             "bus": self.dev.dev.bus, "addr": self.dev.dev.address}
        if card is not None:
            try:
                out["alsa"]["model"] = open("/proc/asound/card%d/id" % card).read().strip()
            except OSError:
                pass
            rate = uc.amixer_run(card, "cget", "numid=3")
            out["alsa"]["clock_source"] = uc.alsa_value(3, card)
        try:
            for line in open("/proc/asound/card%d/stream0" % card):
                if "Rates:" in line:
                    out["alsa"]["rates"] = line.split("Rates:")[1].strip()
                    break
        except (OSError, TypeError):
            pass
        out["pairs"] = [{"id": i, "name": n} for i, n in enumerate(PAIR_NAMES)]
        out["inputs"] = [{"group": g, "name": n, "ch": c}
                         for g, items in INPUT_GROUPS for n, c in items]
        return out


SURFACE = None


class Handler(BaseHTTPRequestHandler):
    server_version = "ucd/1"

    def log_message(self, fmt, *a):
        if os.environ.get("UC_DEBUG"):
            sys.stderr.write("http: " + (fmt % a) + "\n")
            sys.stderr.flush()

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, rel):
        path = (UI_DIR / rel).resolve()
        if not str(path).startswith(str(UI_DIR.resolve())) or not path.is_file():
            return self._send(404, {"error": "not found"})
        ctype = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".js": "text/javascript; charset=utf-8",
                 ".svg": "image/svg+xml"}.get(path.suffix, "application/octet-stream")
        self._send(200, path.read_bytes(), ctype)

    def do_GET(self):
        url = urlparse(self.path)
        if os.environ.get("UC_DEBUG"):
            sys.stderr.write("GET %s from %s\n" % (self.path, self.client_address))
            sys.stderr.flush()
        if url.path in ("/", "/index.html"):
            return self._file("index.html")
        if url.path.startswith("/ui/"):
            return self._file(url.path[4:])
        if url.path == "/api/info":
            return self._send(200, SURFACE.info())
        if url.path == "/api/events":
            return self._stream()
        if url.path == "/api/presets":
            PRESET_DIR.mkdir(parents=True, exist_ok=True)
            return self._send(200, sorted(p.stem for p in PRESET_DIR.glob("*.json")))
        return self._send(404, {"error": "no route"})

    def do_POST(self):
        url = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._send(400, {"error": "bad json"})
        try:
            if url.path == "/api/strip":
                pair = int(body["pair"])
                ch = int(body["input"])
                surf = SURFACE
                strip = dict(surf.state["strips"].get("%d:%d" % (pair, ch),
                                                      {"level_db": -96.0, "pan": 0.0, "mute": True}))
                for key in ("level_db", "pan", "mute"):
                    if key in body:
                        strip[key] = body[key]
                strip["level_db"] = clamp_db(strip["level_db"])
                strip["pan"] = max(-1.0, min(1.0, float(strip["pan"])))
                surf.write_strip(pair, ch, strip)
                return self._send(200, {"ok": True, "strip": strip})
            if url.path == "/api/output":
                pair = int(body["pair"])
                surf = SURFACE
                out = dict(surf.state["outputs"].get(str(pair), {"db": 0.0, "mute": False}))
                for key in ("db", "mute"):
                    if key in body:
                        out[key] = body[key]
                out["db"] = clamp_db(out["db"])
                surf.write_output(pair, out)
                return self._send(200, {"ok": True, "output": out})
            if url.path == "/api/switch":
                SURFACE.write_switch(body["name"], bool(body["value"]))
                return self._send(200, {"ok": True})
            if url.path == "/api/apply":
                SURFACE.apply_all()
                return self._send(200, {"ok": True, "applied_at": SURFACE.state["applied_at"]})
            if url.path == "/api/preset":
                PRESET_DIR.mkdir(parents=True, exist_ok=True)
                safe = "".join(c for c in body.get("name", "preset") if c.isalnum() or c in " -_")[:64]
                path = PRESET_DIR / (safe.strip() or "preset")
                path = path.with_suffix(".json")
                with open(path, "w") as fh:
                    json.dump(SURFACE.state, fh, indent=1)
                return self._send(200, {"ok": True, "file": path.name})
            if url.path == "/api/preset/load":
                name = "".join(c for c in body.get("name", "") if c.isalnum() or c in " -_").strip()
                path = PRESET_DIR / (name + ".json")
                if not path.is_file():
                    return self._send(404, {"error": "no such preset"})
                with open(path) as fh:
                    data = json.load(fh)
                SURFACE.state["strips"].update(data.get("strips", {}))
                SURFACE.state["outputs"].update(data.get("outputs", {}))
                SURFACE.state["switches"].update(data.get("switches", {}))
                SURFACE.state["applied_at"] = None  # loaded, not pushed
                SURFACE.save()
                return self._send(200, {"ok": True})
        except RuntimeError as exc:
            return self._send(503, {"error": str(exc)})
        except (KeyError, ValueError, TypeError) as exc:
            return self._send(400, {"error": "bad request: %s" % exc})
        except Exception as exc:
            return self._send(500, {"error": str(exc)})
        return self._send(404, {"error": "no route"})

    def _stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            while True:
                payload = {"telemetry": SURFACE.telemetry,
                           "switches_read": SURFACE.sw_read,
                           "error": SURFACE.error,
                           "applied_at": SURFACE.state["applied_at"]}
                self.wfile.write(b"data: " + json.dumps(payload).encode() + b"\n\n")
                self.wfile.flush()
                time.sleep(1.0)
        except (BrokenPipeError, ConnectionResetError):
            return


def poll_loop():
    while True:
        try:
            SURFACE.poll()
        except Exception:
            pass
        time.sleep(1.0)


def serve(host="127.0.0.1", port=8777):
    """Create the surface and bind the API. Returns (httpd, url, surface).

    Split out from main() so the desktop app can host it in-process.
    """
    global SURFACE
    SURFACE = Surface()
    threading.Thread(target=poll_loop, daemon=True).start()
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    real_port = httpd.server_address[1]
    return httpd, "http://%s:%d/" % (host, real_port), SURFACE


def main():
    ap = argparse.ArgumentParser(description="Studio 1810c control daemon")
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    httpd, url, surface = serve(args.host, args.port)
    print("ucd: serving %s" % url)
    if surface.error:
        print("ucd: device problem: %s" % surface.error)
    else:
        print("ucd: %04x:%04x bus %d addr %d"
              % (uc.VID, uc.PID_1810C, surface.dev.dev.bus, surface.dev.dev.address))
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nucd: stopped")


if __name__ == "__main__":
    main()
