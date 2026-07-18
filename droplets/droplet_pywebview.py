"""Droplet backend on pywebview: one widget/app window on the platform-native
webview (WKWebView on macOS, WebView2 on Windows, WebKitGTK on Linux).

This mirrors the GTK backend's public shape so the launcher and widgets don't
care which one runs:
  - same constructor `Droplet(path, custom_manifest=None)`
  - same JS bridge: widgets call `droplets.send(cmd)` and receive
    `droplets.recieve(result)` (the WebKit2 script-message handler is replaced
    by pywebview's `js_api`)
  - same `allowed_methods` gate on module calls (the hybrid-tier allowlist)

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

        self.init_widget(path, custom_manifest)
        webview.start()

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

        # ponytail: pywebview has no API for keep-below, stick, or per-window
        # opacity. On macOS we recover them by reaching the NSWindow pywebview
        # created (see _apply_native_macos). skip-taskbar/pager is an app-bundle
        # LSUIElement key (packaging, not runtime) and arbitrary pixmap masks
        # have no macOS analog -> still unsupported, transparency-shape instead.

        url = self._resolve_url(manifest.origin, path + manifest.source)
        window = webview.create_window(url=url, **kwargs)
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
