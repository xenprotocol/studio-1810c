#!/usr/bin/python3
"""Is the in-process daemon's HTTP server usable at all from a normal client?"""
import os
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "vendor"))

import threading
import ucd

httpd, url, surface = ucd.serve("127.0.0.1", 0)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
print("serving", url, flush=True)

try:
    with urllib.request.urlopen(url, timeout=5) as r:
        body = r.read()
        print("urllib: status", r.status, "bytes", len(body), "title-in-body:",
              b"<title>" in body, flush=True)
except Exception as exc:
    print("urllib FAILED:", exc, flush=True)

print("webkit processes:", subprocess.run(
    ["pgrep", "-fa", "WebKit"], capture_output=True, text=True).stdout.strip()[:200], flush=True)
httpd.shutdown()
