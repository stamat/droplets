"""Droplet backend on pywebview: one widget/app window on the platform-native
webview (WKWebView on macOS, WebView2 on Windows, WebKitGTK on Linux).

This mirrors the GTK backend's public shape so the launcher and widgets don't
care which one runs:
  - same constructor `Droplet(path, custom_manifest=None)`
  - same JS bridge: widgets call `droplets.send(cmd)` and receive
    `droplets.recieve(result)` (the WebKit2 script-message handler is replaced
    by pywebview's `js_api`). Only the `local` tier gets the shim -- it is baked
    into the entry document, and remote/hosted load their URL directly.
    pywebview exposes no user-script API, and those tiers have no bridge
    (`recieve` drops their messages), so nothing is lost.
  - same `allowed_methods` gate on module calls (the hybrid-tier allowlist)
  - same per-tier CSP (droplets/csp.py) so remote subresources are blocked --
    delivered here as a real response header, because local widgets are served
    over loopback (droplets/server.py) rather than read off disk

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

from . import server
from .backend import debug_enabled
from .manifest import Manifest
from .utils import import_from_uri

# JS shim: preserve the widget-facing `droplets.send(cmd)` API but route it
# through pywebview's js_api instead of WebKit2's messageHandlers.
#
# It is baked into the entry document (see prepare_widget) rather than
# evaluate_js'd, because widgets call `droplets.send` from inline script during
# parse -- the GTK backend injects the same shim at UserScriptInjectionTime.START
# for exactly that reason. pywebview only creates `window.pywebview.api` on
# didFinishNavigation, well after parse, so calls made before that are queued
# here and flushed on `pywebviewready`. Without this the widget's first line
# throws ReferenceError and the rest of its script never runs.
_BRIDGE_SHIM = (
    "window.droplets = window.droplets || {};"
    "droplets._queue = [];"
    "droplets.send = function(cmd) {"
    "  if (cmd === undefined || cmd === null) return;"
    "  if (window.pywebview && window.pywebview.api)"
    "    window.pywebview.api.send(String(cmd));"
    "  else droplets._queue.push(String(cmd));"
    "};"
    "window.addEventListener('pywebviewready', function() {"
    "  var q = droplets._queue; droplets._queue = [];"
    "  q.forEach(function(c) { window.pywebview.api.send(c); });"
    "});"
)
_BRIDGE_SHIM_TAG = "<script>" + _BRIDGE_SHIM + "</script>"


def _rect_on_screen(x, y, width, height, screens):
    """True when the window rect overlaps any attached display.

    ponytail: bounding-box overlap only -- close enough to catch a widget
    stranded on a display that is gone. Not a coordinate-system conversion: the
    macOS y-origin flip is irrelevant to whether anything overlaps at all.
    """
    return any(
        x < s.x + s.width and x + width > s.x and y < s.y + s.height and y + height > s.y
        for s in screens
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
        # debug=True turns on developer extras -> right-click "Inspect Element".
        webview.start(debug=debug_enabled())

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

    def on_resized(self, width, height):
        self.temp["width"], self.temp["height"] = int(width), int(height)

    def on_close(self):
        """Persist runtime state (position, resized size) to settings.json.

        ponytail: no 'screen' here -- pywebview has no cross-platform screen-index
        API, so the GTK backend's screen-remember has no equivalent. x/y/size only.
        """
        m = self.manifest
        changed = {}
        if m.x != self.temp["x"] or m.y != self.temp["y"]:
            changed["x"], changed["y"] = self.temp["x"], self.temp["y"]
        if m.resizable and "width" in self.temp:
            if (self.temp["width"], self.temp["height"]) != (m.width, m.height):
                changed["width"], changed["height"] = self.temp["width"], self.temp["height"]
        if changed:
            m.save_setting(**changed)

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
        # Position is NOT passed to create_window: on macOS pywebview moves the
        # window while it is still unordered, and an unordered NSWindow whose
        # frame is off the main display reports screen() as nil -- pywebview's
        # windowDidMove_ then dies on `window.screen().frame()` (AttributeError).
        # Any x on a secondary display trips it. Moving once the window is shown
        # keeps second-screen restore working. Skip positions that land on no
        # attached display at all (a monitor unplugged since the last run),
        # otherwise the widget restores somewhere invisible.
        self._pending_move = None
        if (
            manifest.x is not None
            and manifest.y is not None
            and _rect_on_screen(
                manifest.x, manifest.y, manifest.width, manifest.height, webview.screens
            )
        ):
            self._pending_move = (manifest.x, manifest.y)

        # Local tier: served over loopback (droplets/server.py) rather than read
        # off disk, which is what lets the CSP be a real response header and what
        # gives the widget access to its own assets -- a file:// document created
        # by load_html() has neither. The shim rides along in the same response.
        if manifest.origin == "local":
            self.root_url = server.serve(
                os.path.abspath(path), manifest.source, manifest.origin, _BRIDGE_SHIM_TAG
            )
            kwargs["url"] = self.root_url
        else:
            kwargs["url"] = self._resolve_url(manifest.origin, path + manifest.source)

        # ponytail: pywebview has no API for keep-below, stick, or per-window
        # opacity. On macOS we recover them by reaching the NSWindow pywebview
        # created (see _apply_native_macos). skip-taskbar/pager is an app-bundle
        # LSUIElement key (packaging, not runtime) and arbitrary pixmap masks
        # have no macOS analog -> still unsupported, transparency-shape instead.

        window = webview.create_window(**kwargs)
        self.window = window

        # The NSWindow only exists once webview.start() runs -- window.native is
        # still None here -- so the native-only flags go on the `shown` event.
        window.events.shown += self._apply_native_macos

        if self._pending_move is not None:
            window.events.shown += self._restore_position
        # events.moved / closing exist in pywebview 3.4+; guard for older builds.
        if hasattr(window.events, "moved"):
            window.events.moved += self.on_moved
        if hasattr(window.events, "resized"):
            window.events.resized += self.on_resized
        if hasattr(window.events, "closing"):
            window.events.closing += self.on_close

        return window

    def _apply_native_macos(self):
        # ponytail: darwin-only. Reach the NSWindow pywebview already created and
        # set the widget flags pywebview doesn't surface (keep-below, stick,
        # opacity, keep-above). pyobjc (AppKit/Quartz) ships with pywebview on
        # macOS, so no new dependency. No-op on every other platform.
        if sys.platform != "darwin":
            return
        from AppKit import NSThread, NSFloatingWindowLevel, NSNormalWindowLevel
        from PyObjCTools import AppHelper

        # pywebview fires window events on a worker thread; AppKit setters are
        # main-thread only, so hop before touching the window.
        if not NSThread.isMainThread():
            AppHelper.callAfter(self._apply_native_macos)
            return

        ns = getattr(self.window, "native", None)
        if ns is None:
            # ponytail: pywebview has moved the Cocoa handle across versions;
            # if it's not on .native, skip rather than guess. Widget still runs,
            # just without the native-only flags. Revisit if a version drops it.
            return

        manifest = self.manifest
        if manifest.below:
            # ponytail: one level under normal, NOT kCGDesktopWindowLevel. At the
            # true desktop level the window sits beneath Finder's desktop-icon
            # window, which spans the screen and swallows every click -- drag and
            # any other mouse input die. -1 keeps the widget behind all app
            # windows (the point of keep-below) while staying interactive.
            ns.setLevel_(NSNormalWindowLevel - 1)
        elif manifest.above:
            ns.setLevel_(NSFloatingWindowLevel)
        if manifest.stick:
            # canJoinAllSpaces (1<<0) | stationary (1<<4): show on every Space.
            ns.setCollectionBehavior_((1 << 0) | (1 << 4))
        if manifest.opacity is not None and manifest.opacity < 1:
            ns.setAlphaValue_(manifest.opacity)

    def _restore_position(self):
        self.window.move(*self._pending_move)

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
