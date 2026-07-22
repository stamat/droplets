"""System stats for the sysmon droplet: CPU, memory, disk, network.

Stdlib only. A droplet ships as a plain directory with no install step, so the
backend can't assume psutil is on the host -- every metric is read from the
platform directly: /proc on Linux, mach/sysctl/BSD tools on macOS.

CPU and network are *rates*: the kernel only exposes cumulative counters, so
each is the delta against the previous call (see _delta). The first call after
launch has no baseline and reports None for both -- the front-end shows a dash.
"""

import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import time

_DARWIN = sys.platform == "darwin"

# name -> (timestamp, counters) of the previous sample, for the rate metrics.
_prev = {}


def _delta(name, counters):
    """Elementwise change in `counters` since the last call, plus seconds elapsed.

    Returns None on the first call for `name` (nothing to diff against).
    """
    now = time.monotonic()
    previous = _prev.get(name)
    _prev[name] = (now, counters)
    if previous is None:
        return None
    then, before = previous
    dt = now - then
    if dt <= 0:
        return None
    return [a - b for a, b in zip(counters, before)], dt


# ---- CPU -----------------------------------------------------------------

if _DARWIN:
    _HOST_CPU_LOAD_INFO = 3  # <mach/host_info.h>; 4 counters: user, system, idle, nice

    class _CpuLoad(ctypes.Structure):
        _fields_ = [("ticks", ctypes.c_uint * 4)]

    _libc = ctypes.CDLL("/usr/lib/libSystem.dylib")
    _libc.mach_host_self.restype = ctypes.c_uint  # mach_port_t, not int


def _cpu_ticks():
    """Cumulative (busy, total) CPU ticks since boot, or None if unreadable."""
    if _DARWIN:
        info = _CpuLoad()
        count = ctypes.c_uint(4)
        if _libc.host_statistics(
            _libc.mach_host_self(), _HOST_CPU_LOAD_INFO, ctypes.byref(info), ctypes.byref(count)
        ) != 0:
            return None
        user, system, idle, nice = info.ticks
        busy = user + system + nice
        return busy, busy + idle
    with open("/proc/stat") as f:
        # cpu user nice system idle iowait irq softirq steal [guest guest_nice]
        fields = [int(x) for x in f.readline().split()[1:8]]
    total = sum(fields)
    return total - fields[3] - fields[4], total  # idle + iowait is not busy


def _cpu_percent():
    change = _delta("cpu", _cpu_ticks() or (0, 0))
    if change is None:
        return None
    (busy, total), _dt = change
    if total <= 0:
        return None
    return round(min(100.0, max(0.0, 100.0 * busy / total)), 1)


# ---- memory ---------------------------------------------------------------

def _memory():
    """(used, total) bytes of physical RAM."""
    if _DARWIN:
        page = os.sysconf("SC_PAGE_SIZE")
        total = os.sysconf("SC_PHYS_PAGES") * page
        out = subprocess.run(["vm_stat"], capture_output=True, text=True).stdout
        pages = {k.strip(): int(v) for k, v in re.findall(r"Pages ([\w ]+):\s+(\d+)\.", out)}
        # ponytail: Activity Monitor's "Memory Used" also weighs compression and
        # file-backed pages; free+inactive+speculative is the reclaimable set and
        # lands within a few percent. Good enough for a widget bar.
        free = sum(pages.get(k, 0) for k in ("free", "inactive", "speculative"))
        return total - free * page, total
    values = {}
    with open("/proc/meminfo") as f:
        for line in f:
            key, _, rest = line.partition(":")
            if key in ("MemTotal", "MemAvailable"):
                values[key] = int(rest.split()[0]) * 1024  # reported in kB
    total = values["MemTotal"]
    return total - values.get("MemAvailable", 0), total


# ---- network --------------------------------------------------------------

def _net_bytes():
    """Cumulative (received, sent) bytes across all non-loopback interfaces."""
    received = sent = 0
    if _DARWIN:
        out = subprocess.run(["netstat", "-ibn"], capture_output=True, text=True).stdout
        lines = out.splitlines()
        if not lines:
            return received, sent
        # Count columns from the right: the Address column is blank on the very
        # rows that carry the link-layer totals, so left-hand offsets shift.
        header = lines[0].split()
        rx_col = header.index("Ibytes") - len(header)
        tx_col = header.index("Obytes") - len(header)
        seen = set()
        for line in lines[1:]:
            fields = line.split()
            name = fields[0] if fields else ""
            # One row per interface: the first is the <Link#n> row holding the
            # totals, the rest repeat them once per bound address.
            if not name or name.startswith("lo") or name in seen:
                continue
            if len(fields) < len(header) - 1 or not fields[rx_col].isdigit():
                continue
            seen.add(name)
            received += int(fields[rx_col])
            sent += int(fields[tx_col])
        return received, sent
    with open("/proc/net/dev") as f:
        for line in f.readlines()[2:]:  # two header lines
            name, _, rest = line.partition(":")
            if name.strip().startswith("lo"):
                continue
            fields = rest.split()
            received += int(fields[0])
            sent += int(fields[8])
    return received, sent


def _net_rates():
    change = _delta("net", _net_bytes())
    if change is None:
        return None
    (received, sent), dt = change
    # Counters wrap (32-bit on some interfaces) and reset when a link drops.
    if received < 0 or sent < 0:
        return None
    return {"rx": received / dt, "tx": sent / dt}


# ---- the one method the front-end calls -----------------------------------

def stats():
    """CPU/memory/disk/network snapshot for the widget."""
    used_memory, total_memory = _memory()
    disk = shutil.disk_usage("/")
    return {
        "cpu": _cpu_percent(),
        "cores": os.cpu_count(),
        "load": [round(x, 2) for x in os.getloadavg()],
        "mem": {"used": used_memory, "total": total_memory},
        "disk": {"used": disk.used, "total": disk.total},
        "net": _net_rates(),
    }


if __name__ == "__main__":
    first = stats()
    assert first["cpu"] is None and first["net"] is None, "no rate without a baseline"
    assert 0 < first["mem"]["used"] < first["mem"]["total"], first["mem"]
    assert 0 < first["disk"]["used"] < first["disk"]["total"], first["disk"]
    time.sleep(0.3)
    second = stats()
    assert 0 <= second["cpu"] <= 100, second["cpu"]
    assert second["net"]["rx"] >= 0 and second["net"]["tx"] >= 0, second["net"]
    print(json.dumps(second, indent=2))
