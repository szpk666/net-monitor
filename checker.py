"""Low-level connectivity check primitives. Stdlib only (no extra pip deps)
so this runs anywhere Python 3 runs -- Windows, Linux, Termux/Android."""

import platform
import re
import subprocess
import time
import ssl
import urllib.request

IS_WINDOWS = platform.system() == "Windows"


def ping_host(host, timeout=3):
    """Ping a host twice. Returns (ok: bool, avg_latency_ms: float|None).

    Windows latency parsing looks for the numeric "=Xms" / "<Xms" pattern
    rather than the English word "Average" -- on non-English Windows that
    word is translated (e.g. Chinese shows "平均 = 12ms"), but the "=Xms"
    shape and the fixed Minimum/Maximum/Average ordering are not, so the
    LAST such match in the output is reliably the average regardless of
    display language. This is also more accurate than timing the whole
    subprocess call, which gets polluted by process-spawn overhead."""
    try:
        if IS_WINDOWS:
            cmd = ["ping", "-4", "-n", "2", "-w", str(timeout * 1000), host]
        else:
            cmd = ["ping", "-c", "2", "-W", str(timeout), host]

        start = time.time()
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 3)
        elapsed_ms = (time.time() - start) * 1000

        if result.returncode != 0:
            return False, None

        if IS_WINDOWS:
            matches = re.findall(r"[=<]\s*(\d+)\s*ms", result.stdout, re.IGNORECASE)
            if matches:
                return True, float(matches[-1])  # last match = Average, any locale
            return True, round(elapsed_ms / 2, 1)  # fallback if output format is unrecognized

        for line in result.stdout.splitlines():
            if "min/avg/max" in line or "rtt" in line.lower():
                try:
                    seg = line.split("=")[1].strip().split()[0]
                    avg = float(seg.split("/")[1])
                    return True, avg
                except Exception:
                    return True, round(elapsed_ms / 2, 1)
        return True, round(elapsed_ms / 2, 1)
    except Exception:
        return False, None


def detect_gateway():
    """Best-effort default gateway detection. Locale-independent (matches
    numeric IPs, not localized column headers)."""
    try:
        if IS_WINDOWS:
            result = subprocess.run(["route", "print", "-4"], capture_output=True, text=True, timeout=5)
            m = re.search(r"^\s*0\.0\.0\.0\s+0\.0\.0\.0\s+(\d+\.\d+\.\d+\.\d+)", result.stdout, re.MULTILINE)
            if m:
                return m.group(1)
        else:
            result = subprocess.run(["ip", "route"], capture_output=True, text=True, timeout=5)
            for line in result.stdout.splitlines():
                if line.startswith("default"):
                    return line.split()[2]
    except Exception:
        pass
    return None


def check_http(url, timeout=5):
    """HEAD request to a URL. Returns (ok: bool, latency_ms: float|None)."""
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "NetMon/1.0"})
        start = time.time()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            elapsed = (time.time() - start) * 1000
            return resp.status < 500, elapsed
    except Exception:
        return False, None
