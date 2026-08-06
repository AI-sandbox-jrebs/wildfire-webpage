"""Run the cross-view computed-style theme assertion in headless Chromium."""

import base64
import json
import os
import subprocess
import shutil
import tempfile
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CHROME = "/opt/.devin/chrome/chrome/linux-133.0.6943.126/chrome-linux64/chrome"
URL = "http://localhost:8000"
PROPERTIES = (
    "border-radius",
    "border-top-width",
    "border-right-width",
    "border-bottom-width",
    "border-left-width",
    "padding-top",
    "padding-right",
    "padding-bottom",
    "padding-left",
    "font-family",
    "font-size",
    "font-weight",
    "letter-spacing",
    "outline-width",
    "outline-offset",
)

# Surface brightness is the only sanctioned divergence. Every other property
# is compared explicitly, rather than exempting a component or an entire view.
SURFACE_ALLOWLIST = {"color", "background-color", "border-top-color", "border-right-color", "border-bottom-color", "border-left-color", "box-shadow"}

COMPONENTS = {
    "section-title": [".panel--head h1", ".verification-panel h2", ".history-section-heading h2"],
    "eyebrow": [".panel--head .eyebrow", ".verification-panel .eyebrow", ".history-map-section .eyebrow"],
    "card": [".panel--head", ".verification-panel", ".history-year"],
    "button": [".tabs button", ".tabs button", ".history-map-framing button"],
}


def ws_frame(payload):
    data = payload.encode()
    mask = os.urandom(4)
    masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(data))
    length = len(masked)
    header = bytes([0x81])
    if length < 126:
        header += bytes([0x80 | length])
    elif length < 65536:
        header += bytes([0x80 | 126]) + length.to_bytes(2, "big")
    else:
        header += bytes([0x80 | 127]) + length.to_bytes(8, "big")
    return header + mask + masked


def ws_read(sock):
    first = sock.recv(2)
    if not first:
        return ""
    length = first[1] & 127
    if length == 126:
        length = int.from_bytes(sock.recv(2), "big")
    elif length == 127:
        length = int.from_bytes(sock.recv(8), "big")
    if first[1] & 128:
        sock.recv(4)
    return sock.recv(length).decode()


def evaluate(sock, expression, counter):
    counter[0] += 1
    sock.sendall(ws_frame(json.dumps({"id": counter[0], "method": "Runtime.evaluate", "params": {"expression": expression, "returnByValue": True}})))
    while True:
        message = json.loads(ws_read(sock))
        if message.get("id") == counter[0]:
            return message["result"]["result"].get("value")


def run_assertion():
    import socket

    with tempfile.TemporaryDirectory() as profile:
        process = subprocess.Popen(
            [CHROME, "--headless=new", "--no-sandbox", "--disable-gpu", "--window-size=1280,800",
             "--remote-debugging-port=9229", f"--user-data-dir={profile}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            for _ in range(30):
                try:
                    info = json.load(urllib.request.urlopen("http://127.0.0.1:9229/json", timeout=1))[0]
                    break
                except Exception:
                    time.sleep(0.1)
            sock = socket.create_connection(("127.0.0.1", 9229), timeout=5)
            key = base64.b64encode(os.urandom(16)).decode()
            sock.sendall(
                f"GET {info['webSocketDebuggerUrl'].split('9229', 1)[1]} HTTP/1.1\r\n"
                f"Host: 127.0.0.1:9229\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode()
            )
            sock.recv(4096)
            counter = [0]
            results = {}
            for view_index, view in enumerate(("", "updates", "then-vs-now")):
                evaluate(sock, f"location.href='{URL}/#/{view}'", counter)
                time.sleep(1.5)
                results[view] = evaluate(sock, f"""(() => {{
                  const properties = {json.dumps(PROPERTIES)};
                  const components = {json.dumps(COMPONENTS)};
                  const output = {{}};
                  for (const [name, selectors] of Object.entries(components)) {{
                    const element = document.querySelector(selectors[{view_index}]);
                    if (!element) return {{error: `missing ${{name}} in {view}`}};
                    const style = getComputedStyle(element);
                    output[name] = Object.fromEntries(properties.map((property) => [property, style.getPropertyValue(property)]));
                  }}
                  return output;
                }})()""", counter)
            failures = []
            for component in COMPONENTS:
                values = [results[view][component] for view in ("", "updates", "then-vs-now")]
                for prop in PROPERTIES:
                    if len({item[prop] for item in values}) > 1:
                        failures.append(
                            f"{component}.{prop}: Now={values[0][prop]!r}, "
                            f"Updates={values[1][prop]!r}, Then vs Now={values[2][prop]!r}"
                        )
            if failures:
                raise SystemExit("theme computed-style check failed:\n" + "\n".join(failures))
            print("theme computed-style check: pass")
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    run_assertion()
