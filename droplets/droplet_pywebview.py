"""Droplet backend on pywebview: one widget/app window on the platform-native
webview (WKWebView on macOS, WebView2 on Windows, WebKitGTK on Linux).

This mirrors the GTK backend's public shape so the launcher and widgets don't
care which one runs:
  - same constructor `Droplet(path, custom_manifest=None)`
  - same JS bridge: widgets call `droplets.send(cmd)` and receive
    `droplets.recieve(result)` (the WebKit2 script-message handler is replaced
    by pywebview's `js_api`)
  - same `allowed_methods` gate on module calls (the hybrid-tier allowlist)
  - same per-tier CSP: local widgets get the CSP meta baked in (droplets/csp.py)
    and are loaded via load_html so remote subresources are blocked

What pywebview can't do that GTK can (see PR review): arbitrary pixmap window
masks (`reshapemask`) have no equivalent — you get frameless + transparent
"technique B" shaping (rounded/circle/PNG-alpha via CSS) only.

Some WM hints have no cross-platform pywebview API (keep-below, stick,
per-window opacity). On macOS they're recovered natively via the NSWindow
pywebview hands us (see `_apply_native_macos`); on Windows they stay dropped.
skip-taskbar/pager is an app-bundle setting (LSUIElement), not a runtime call.
"""

import json
import os
import sys
import urllib.request

import webview  # pip install pywebview  (+ pyobjc on macOS, pythonnet on Windows)

from . import csp
from .manifest import Manifest
from .utils import import_from_uri

# JS shim: preserve the widget-facing `droplets.send(cmd)` API but route it
# through pywebview's js_api instead of WebKit2's messageHandlers. Injected once
# the pywebview API is live (evaluate_js on the `loaded` event).
_BRIDGE_SHIM = (
    "window.droplets = window.droplets || {};"
    "droplets.send = function(cmd) {"
    "  if (cmd !== undefined && cmd !== null)"
    "    window.pywebview.api.send(String(cmd));"
    "};"
)


class _Api:
    """The single method pywebview exposes to JS. Everything funnels through
    `send` (a JSON `{method, args}` packet), so no widget module function is
    reachable by name from JS unless the bridge dispatch allows it."""

    def __init__(self, droplet):
        self._droplet = droplet

    def send(self, cmd):
        self._droplet.recieve(cmd)


class Droplet:
    def __init__(self, path, custom_manifest=None):
        self.window = None
        self.manifest = None
        self.module = None
        self.path = None
        self.temp = {"x": 0, "y": 0}
        self.root_url = None
        # For the local tier we load the CSP-injected entry doc via load_html
        # (needs the GUI live), deferred to _start; see prepare_widget.
        self._pending_html = None
        self._pending_base = None

        self.init_widget(path, custom_manifest)
        webview.start(self._start)

    def _start(self):
        # Runs once the GUI is ready. Load the CSP-injected local document with
        # its own dir as base_uri (file:// origin + relative resources), so the
        # widget never even briefly shows the un-CSP'd file.
        if self._pending_html is not None:
            self.window.load_html(self._pending_html, self._pending_base)

    # ---- JS <-> Python bridge (mirrors the GTK backend) -----------------

    def recieve(self, msg):
        if msg == "null" or self.manifest.origin != "local":
            return
        packet = json.loads(msg)
        if packet["method"].startswith("droplet_"):
            fn = getattr(self, packet["method"], None)
        else:
            # Optional allowlist: when manifest.allowed_methods is set, only those
            # module functions are callable from JS (the hybrid-tier gate). Absent
            # (null) keeps the legacy behaviour of exposing every module function.
            allowed = getattr(self.manifest, "allowed_methods", None)
            if allowed is not None and packet["method"] not in allowed:
                return
            fn = getattr(self.module, packet["method"], None)
            args = packet.get("args", {})
            # GTK backend also injects gtk/browser here; pywebview only has a
            # window handle to hand a module that asks for one.
            if "window" in args:
                args["window"] = self.window
        if fn:
            result = fn(**packet.get("args", {}))
            self.send(result)

    def send(self, msg):
        # json.dumps yields a safe JS literal (same fix as the GTK backend):
        # raw %-interpolation injects/breaks on quotes/newlines/</script>.
        self.window.evaluate_js("droplets.recieve(%s);" % json.dumps(msg))

    # ---- droplet_* actions callable from JS -----------------------------
    # Only the ones with a pywebview equivalent. GTK's GDK-event actions
    # (droplet_connect, drag enable/disable toggles) have no pywebview API;
    # drag is set once at window creation via easy_drag instead.

    def droplet_move(self, x, y):
        self.window.move(int(x), int(y))

    def droplet_deactivate(self):
        self.on_close()
        self.window.destroy()

    # ---- window geometry persistence ------------------------------------

    def on_moved(self, x, y):
        self.temp["x"], self.temp["y"] = int(x), int(y)

    def on_close(self):
        if self.manifest.x != self.temp["x"] or self.manifest.y != self.temp["y"]:
            self.manifest.set("x", self.temp["x"])
            self.manifest.set("y", self.temp["y"])
            self.manifest.dump_manifest(self.manifest.path)

    # ---- window setup ---------------------------------------------------

    def prepare_widget(self, manifest, module, path):
        self.manifest = manifest
        self.module = module

        kwargs = dict(
            title=manifest.title or "",
            width=manifest.width,
            height=manifest.height,
            resizable=manifest.resizable,
            frameless=not manifest.decorated,
            easy_drag=manifest.drag,
            transparent=manifest.transparent,
            on_top=manifest.above,
            hidden=manifest.hidden,
            js_api=_Api(self),
        )
        if manifest.x is not None and manifest.y is not None:
            kwargs["x"], kwargs["y"] = manifest.x, manifest.y

        # Local tier: enforce the per-tier CSP (see droplets/csp.py). Read the
        # entry doc, bake in the CSP meta, and defer loading it via load_html
        # (with the widget dir as base_uri) to _start -- create the window with a
        # blank placeholder so remote subresources can never load first. Every
        # other tier loads its URL directly (remote/hosted may reach the web).
        if manifest.origin == "local":
            src = os.path.abspath(path + manifest.source)
            with open(src, "r", encoding="utf-8") as f:
                self._pending_html = csp.inject(f.read(), manifest.origin)
            self._pending_base = (
                "file://" + urllib.request.pathname2url(os.path.dirname(src)) + "/"
            )
            self.root_url = self._pending_base.rstrip("/")
            kwargs["html"] = "<!doctype html><title></title>"
        else:
            kwargs["url"] = self._resolve_url(manifest.origin, path + manifest.source)

        # ponytail: pywebview has no API for keep-below, stick, or per-window
        # opacity. On macOS we recover them by reaching the NSWindow pywebview
        # created (see _apply_native_macos). skip-taskbar/pager is an app-bundle
        # LSUIElement key (packaging, not runtime) and arbitrary pixmap masks
        # have no macOS analog -> still unsupported, transparency-shape instead.

        window = webview.create_window(**kwargs)
        self.window = window

        self._apply_native_macos(manifest)

        window.events.loaded += self._on_loaded
        # events.moved / closing exist in pywebview 3.4+; guard for older builds.
        if hasattr(window.events, "moved"):
            window.events.moved += self.on_moved
        if hasattr(window.events, "closing"):
            window.events.closing += self.on_close

        return window

    def _apply_native_macos(self, manifest):
        # ponytail: darwin-only. Reach the NSWindow pywebview already created and
        # set the widget flags pywebview doesn't surface (keep-below, stick,
        # opacity, keep-above). pyobjc (AppKit/Quartz) ships with pywebview on
        # macOS, so no new dependency. No-op on every other platform.
        if sys.platform != "darwin":
            return
        ns = getattr(self.window, "native", None)
        if ns is None:
            # ponytail: pywebview has moved the Cocoa handle across versions;
            # if it's not on .native, skip rather than guess. Widget still runs,
            # just without the native-only flags. Revisit if a version drops it.
            return
        from AppKit import NSWindow, NSFloatingWindowLevel  # noqa: F401
        import Quartz

        if manifest.below:
            ns.setLevel_(Quartz.CGWindowLevelForKey(Quartz.kCGDesktopWindowLevelKey))
        elif manifest.above:
            ns.setLevel_(NSFloatingWindowLevel)
        if manifest.stick:
            # canJoinAllSpaces (1<<0) | stationary (1<<4): show on every Space.
            ns.setCollectionBehavior_((1 << 0) | (1 << 4))
        if manifest.opacity is not None and manifest.opacity < 1:
            ns.setAlphaValue_(manifest.opacity)

    def _on_loaded(self):
        self.window.evaluate_js(_BRIDGE_SHIM)

    @staticmethod
    def _resolve_url(origin, source):
        # hosted -> remote URL as authored; everything else -> local file://.
        if origin == "hosted":
            return source
        file = os.path.abspath(source)
        return "file://" + urllib.request.pathname2url(file)

    # ---- loading --------------------------------------------------------

    def init_widget(self, path, custom_manifest=None):
        if not path.endswith("/"):
            path = path + "/"
        self.path = path

        path_to_manifest = (
            custom_manifest if custom_manifest is not None else path + "manifest.json"
        )

        manifest = Manifest(path_to_manifest)
        self.temp["x"] = manifest.x or 0
        self.temp["y"] = manifest.y or 0
        module = import_from_uri(os.path.join(path, manifest.executable), True)
        window = self.prepare_widget(manifest, module, path)

        return manifest, module, window
