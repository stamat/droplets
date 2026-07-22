"""Backend for the droplet manager: list what is installed, run it, configure it.

Everything the front-end shows comes from each droplet's own `manifest.json`
(title, description, icon, screenshots, and the `options` schema its author
declared); everything the user changes is written to that droplet's
`settings.json` through `Manifest.save_options`, which is what keeps a user's
value from ever landing on a geometry or security field.

On/off is a real process: a droplet runs as its own `droplets.py <dir>`
process, spawned as a child of the manager and tracked by its Popen handle.
"On" spawns one; "off" terminates it; quitting the manager terminates every
one it started (see `terminate_all`), so widgets share the manager's lifetime.
Which droplets are actually running is still read back from the process table,
so a droplet that exits on its own (closed from its context menu, or crashed)
shows as off, and one already running is never double-spawned.

The `enabled` flag in each droplet's settings.json is what survives a full
quit: on the next launch `autostart()` re-runs everything that was on.

ponytail: process lookup shells out to `ps`, so this half is POSIX only. The
GTK and pywebview backends both run on Windows; if the manager needs to, the
upgrade path is a psutil dependency or a WMI query behind the same two
functions (`_running_pids`, `_pids_for`).
"""

import atexit
import base64
import json
import mimetypes
import os
import signal
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APPS = os.path.join(ROOT, "apps")
LAUNCHER = os.path.join(ROOT, "droplets.py")

sys.path.insert(0, ROOT)

from droplets.manifest import Manifest  # noqa: E402

# Screenshots are read on demand (a card only needs the icon), and a droplet
# that ships a 4MB PNG should fail visibly rather than wedge the bridge.
_MAX_MEDIA_BYTES = 4 * 1024 * 1024


# ---- naming ---------------------------------------------------------------


def _dir_for(name):
    """Resolve a droplet's directory name to its path, or raise.

    The front-end addresses droplets by directory name only. Names are checked
    rather than paths joined blindly: `name` arrives from JavaScript and ends up
    as an argv to a spawned process, so `../..` or an absolute path would turn
    "launch a widget" into "launch anything on disk".
    """
    if not name or os.path.sep in name or name in (os.curdir, os.pardir):
        raise ValueError("invalid droplet name %r" % name)
    path = os.path.join(APPS, name)
    if not os.path.isfile(os.path.join(path, "manifest.json")):
        raise ValueError("no droplet named %r" % name)
    return path


def _media_uri(path, base):
    """A `data:` URI for one of a droplet's own image files, or None.

    Manager and droplet are separate origins served from separate directories,
    so the manager cannot link to another droplet's PNG -- the image travels
    over the bridge instead. `base` pins reads inside that droplet's directory.
    """
    if not path:
        return None
    target = os.path.abspath(os.path.join(base, path))
    base = os.path.abspath(base)
    if os.path.commonpath([target, base]) != base or not os.path.isfile(target):
        return None
    if os.path.getsize(target) > _MAX_MEDIA_BYTES:
        return None
    with open(target, "rb") as f:
        data = base64.b64encode(f.read()).decode("ascii")
    mime = mimetypes.guess_type(target)[0] or "application/octet-stream"
    return "data:%s;base64,%s" % (mime, data)


# ---- process table --------------------------------------------------------


def _running_pids():
    """{pid: command line} for every process this user can see."""
    out = subprocess.run(
        ["ps", "-axo", "pid=,command="], capture_output=True, text=True
    ).stdout
    pids = {}
    for line in out.splitlines():
        pid, _, command = line.strip().partition(" ")
        if pid.isdigit():
            pids[int(pid)] = command
    return pids


def _pids_for(path, table=None):
    """Pids of the droplet processes running the droplet at `path`.

    Matching on both the launcher and the directory keeps an unrelated process
    that merely mentions the path (a grep, an editor) from being counted -- or,
    worse, signalled. Recycled pids are a non-issue for the same reason: the
    table is read immediately before it is used.

    The argument is compared by its `apps/<name>` tail rather than in full: the
    manager spawns droplets with an absolute path, but `droplets.py apps/clock`
    from a shell is the documented way to launch one, and a droplet already
    running that way must read as on -- otherwise the switch starts a second
    copy of it.
    """
    if table is None:
        table = _running_pids()
    tail = os.sep + os.path.join(os.path.basename(APPS), os.path.basename(path))
    return [
        pid
        for pid, command in table.items()
        if "droplets.py" in command
        and any(
            arg.rstrip(os.sep).endswith(tail) or arg.rstrip(os.sep) == tail.lstrip(os.sep)
            for arg in command.split()
        )
    ]


# ---- the methods the front-end calls --------------------------------------


def droplets():
    """Every droplet in apps/, with what the manager needs to render it."""
    _reap()
    table = _running_pids()
    listing = []
    for name in sorted(os.listdir(APPS)):
        path = os.path.join(APPS, name)
        if not os.path.isfile(os.path.join(path, "manifest.json")):
            continue
        try:
            manifest = Manifest(os.path.join(path, "manifest.json"))
        except ValueError as error:
            # A broken manifest is the manager's problem to show, not to die on:
            # it is the one place a user can see why a droplet won't start.
            listing.append({"name": name, "title": name, "error": str(error)})
            continue
        listing.append(
            {
                "name": name,
                "title": manifest.title or name,
                "description": manifest.description,
                "type": manifest.type,
                "origin": manifest.origin,
                "icon": _media_uri(manifest.icon, path),
                "has_screenshots": bool(manifest.screenshots),
                "options": manifest.options,
                "values": manifest.option_values(),
                "enabled": bool(manifest.enabled),
                "running": bool(_pids_for(path, table)),
            }
        )
    return listing


def screenshots(name):
    """The droplet's demo images, as data URIs (the store-listing gallery)."""
    path = _dir_for(name)
    manifest = Manifest(os.path.join(path, "manifest.json"))
    return [uri for uri in (_media_uri(s, path) for s in manifest.screenshots) if uri]


# Droplets THIS manager launched, name -> Popen. The handle is what lets quit
# terminate them; the process-table scan is what keeps state honest when one
# exits on its own.
_children = {}


def _terminate(proc):
    """Stop one child, escalating to kill if it ignores the term signal."""
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def _write_enabled(name, value):
    """Persist a droplet's on/off intent to its settings.json."""
    manifest = Manifest(os.path.join(_dir_for(name), "manifest.json"))
    manifest.save_setting(enabled=bool(value))


def _reap():
    """Switch off any child that closed on its own, so autostart won't revive it.

    A droplet the manager launched but did not stop -- the user closed it from
    its own context menu, or it crashed -- is the user saying "off". Clearing
    `enabled` here is what makes that stick across a manager quit: otherwise the
    flag stays on and the next launch's autostart brings the widget back.

    Only children still tracked reach this: stop() and terminate_all() pop what
    the manager itself takes down, so a manager-initiated exit never looks like a
    manual close.
    """
    for name, proc in list(_children.items()):
        if proc.poll() is not None:
            del _children[name]
            _write_enabled(name, False)


def start(name):
    """Launch a droplet as a child of the manager, unless it's already running."""
    path = _dir_for(name)
    # No start_new_session: the child stays tied to the manager so quitting can
    # take it down (terminate_all). The ps guard covers the gap where a previous
    # manager crashed and left an orphan -- don't spawn a second copy of it.
    if not _pids_for(path):
        _children[name] = subprocess.Popen([sys.executable, LAUNCHER, path], cwd=ROOT)
    return {"name": name, "running": True}


def stop(name):
    """Terminate the droplet: the child we own, plus any stray still matching."""
    path = _dir_for(name)
    proc = _children.pop(name, None)
    if proc is not None:
        _terminate(proc)
    # An orphan from a past run, or one launched by hand, has no Popen handle
    # here; signal it by pid so the switch still turns it off.
    for pid in _pids_for(path):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass  # exited between the scan and the signal
    return {"name": name, "running": False}


def terminate_all():
    """Stop every droplet the manager started. Runs when the manager quits.

    A child still alive is taken down *by the quit* and keeps its `enabled` flag,
    so autostart brings it back next launch. A child already gone was closed by
    the user in the gap since the last poll -- treat it like _reap and switch it
    off, so a manual close right before quitting is still remembered as off.

    ponytail: only the manager's own children. A widget started by hand outlives
    it -- there is no handle to it, and the request was to own what the manager
    launched, not to sweep the machine. A manager killed with SIGKILL can't run
    this at all, so its children orphan; the next launch's ps guard keeps that
    from becoming duplicates.
    """
    for name in list(_children):
        proc = _children.pop(name)
        if proc.poll() is None:
            _terminate(proc)
        else:
            _write_enabled(name, False)


def set_enabled(name, enabled):
    """Turn a droplet on or off: run/stop it now, and remember the choice.

    The stored flag is what autostart replays next launch; `running` is the live
    truth, which is why the manager reads both. A later manual close clears the
    flag again (see _reap), so "on" only survives while the user leaves it on.
    """
    _write_enabled(name, enabled)
    return start(name) if enabled else stop(name)


def set_options(name, values):
    """Persist user-edited option values, validated against the manifest schema.

    A running droplet reads its options at launch, so it is restarted here --
    otherwise a saved change appears to do nothing until the next launch.
    """
    path = _dir_for(name)
    manifest = Manifest(os.path.join(path, "manifest.json"))
    try:
        manifest.save_options(values)
    except ValueError as error:
        return {"ok": False, "error": str(error)}
    if _pids_for(path):
        stop(name)
        start(name)
    return {"ok": True, "values": manifest.option_values()}


def autostart():
    """Start every droplet the user left switched on.

    Called on manager launch (the front-end fires it on boot) so the widgets
    that were on last session come back, and also usable standalone as a login
    item via `main.py --autostart`.
    """
    started = []
    for entry in droplets():
        if entry.get("enabled") and not entry.get("running"):
            start(entry["name"])
            started.append(entry["name"])
    return started


# Take the children down with the manager. atexit covers a normal interpreter
# exit (the GTK backend returns from its main loop; SIGINT); a SIGTERM from the
# OS; and, via the backend's on_quit hook, the macOS menu-bar Quit, which calls
# NSApplication terminate_ (a C exit that would skip atexit otherwise).
atexit.register(terminate_all)


def on_quit():
    """Backend hook: the manager is quitting, stop its droplets now."""
    terminate_all()


def _on_signal(_signum, _frame):
    terminate_all()
    os._exit(0)


for _sig in (signal.SIGTERM, signal.SIGINT):
    try:
        signal.signal(_sig, _on_signal)
    except ValueError:
        pass  # not the main thread (e.g. under a test runner) -- atexit still covers it


if __name__ == "__main__":
    if "--autostart" in sys.argv:
        print(json.dumps(autostart()))
        raise SystemExit(0)

    # Name resolution is the trust boundary: it is the only thing between a
    # string from JavaScript and an argv.
    for bad in ("", "..", "../..", "/etc", "clock/../../etc", "nope"):
        try:
            _dir_for(bad)
        except ValueError:
            pass
        else:
            raise AssertionError("_dir_for accepted %r" % bad)
    assert _dir_for("clock").endswith("apps/clock")

    # Media stays inside the droplet it belongs to.
    clock = _dir_for("clock")
    assert _media_uri("clock-face.png", clock).startswith("data:image/png;base64,")
    assert _media_uri("../../manifest_pattern", clock) is None
    assert _media_uri("nope.png", clock) is None

    # A droplet launched by hand with a relative path counts as running; an
    # unrelated process that merely mentions the name does not.
    table = {1: "python droplets.py apps/clock", 2: "vim apps/clock/main.py"}
    assert _pids_for(_dir_for("clock"), table) == [1]
    assert _pids_for(_dir_for("sysmon"), table) == []
    table = {3: "%s %s %s" % (sys.executable, LAUNCHER, _dir_for("sysmon"))}
    assert _pids_for(_dir_for("sysmon"), table) == [3]

    listing = droplets()
    assert listing, "no droplets found in apps/"
    assert all("running" in entry or "error" in entry for entry in listing)
    print(json.dumps([entry["name"] for entry in listing]))
    print("ok")
