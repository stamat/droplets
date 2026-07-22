"""Backend selection: which Droplet implementation runs on this platform.

Only `droplets/droplet.py` (GTK/WebKitGTK) and `droplets/droplet_pywebview.py`
(native webview) touch a GUI toolkit. Everything else in the package is
backend-agnostic. This module is the single fork point: it picks the backend by
platform so `import gi` never runs on macOS and `import webview` never runs on a
GTK-only Linux box.

Override with the DROPLETS_BACKEND env var ("gtk" or "pywebview").
DROPLETS_DEBUG=1 opens the widget's web inspector to its author.
"""

import os
import sys

_BACKENDS = ("gtk", "pywebview")


def backend_name(platform=None, env=None):
    """Resolve a backend name without importing anything heavy (pure/testable).

    Linux defaults to GTK (the only stack with the X11 SHAPE mask API); every
    other platform defaults to pywebview (native WKWebView on mac, WebView2 on
    Windows). DROPLETS_BACKEND overrides both.
    """
    if platform is None:
        platform = sys.platform
    if env is None:
        env = os.environ
    override = env.get("DROPLETS_BACKEND")
    if override:
        override = override.lower()
        if override not in _BACKENDS:
            raise SystemExit(
                "DROPLETS_BACKEND=%r is not one of %s" % (override, _BACKENDS)
            )
        return override
    return "gtk" if platform.startswith("linux") else "pywebview"


def debug_enabled(env=None):
    """True when DROPLETS_DEBUG asks for the web inspector.

    Both backends can hand the widget author devtools -- WebKitGTK via
    `enable-developer-extras`, WKWebView/WebView2 via pywebview's `debug` flag --
    and both then offer "Inspect Element" on right-click. Off unless asked: a
    local widget's inspector console can call the Python bridge, so it is exactly
    the RCE surface droplets/csp.py exists to close.
    """
    if env is None:
        env = os.environ
    return env.get("DROPLETS_DEBUG", "").lower() not in ("", "0", "false", "no")


def get_droplet():
    """Import and return the Droplet class for this platform's backend."""
    name = backend_name()
    if name == "gtk":
        from droplets.droplet import Droplet
    else:
        from droplets.droplet_pywebview import Droplet
    return Droplet


if __name__ == "__main__":
    assert backend_name("linux", {}) == "gtk"
    assert backend_name("darwin", {}) == "pywebview"
    assert backend_name("win32", {}) == "pywebview"
    assert backend_name("linux", {"DROPLETS_BACKEND": "pywebview"}) == "pywebview"
    assert backend_name("darwin", {"DROPLETS_BACKEND": "GTK"}) == "gtk"
    try:
        backend_name("linux", {"DROPLETS_BACKEND": "qt"})
    except SystemExit:
        pass
    else:
        raise AssertionError("expected SystemExit for unknown backend")
    print("ok")
