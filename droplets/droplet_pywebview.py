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
import threading
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

# Seconds of stillness that count as "the drag is over". Cocoa's windowDidMove_
# fires on every frame of a drag (easy_drag included), and pywebview has no
# drag-end event, so geometry is written once the stream goes quiet.
_SETTLE_DELAY = 0.5


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


def _layout_key(screens):
    """Fingerprint the current monitor arrangement, e.g.

        "1512x982+0+0|2560x1440-2560+0"

    Geometry is stored per fingerprint, so undocking and redocking each restore
    the position that belonged to that arrangement. Sorted, so the same displays
    enumerated in a different order stay one layout.

    ponytail: size+origin only, no display serial/EDID -- pywebview's Screen
    doesn't expose one. Two identical monitors swapped between ports read as the
    same layout; the widget lands on the other one. Upgrade path is a native
    per-platform display id if that ever bites.
    """
    return "|".join(
        sorted("%dx%d%+d%+d" % (s.width, s.height, s.x, s.y) for s in screens)
    )


def _screen_for(x, y, screens):
    """The screen a saved (x, y) belongs to, or the primary if none claims it.

    Saved coordinates follow what pywebview's `moved` event emits on macOS
    (cocoa.py windowDidMove_): x is global, y is measured downward from the top
    edge of the screen the window was on -- so y lands in [0, that screen's
    height) and x inside its x-range.
    """
    for screen in screens:
        if screen.x <= x < screen.x + screen.width and 0 <= y < screen.height:
            return screen
    return screens[0]  # NSScreen.screens()[0] is the primary


def _top_left_point(x, y, screens):
    """Saved (x, y) -> the window's top-left corner in global Cocoa coordinates,
    which are y-up from the bottom of the primary screen."""
    screen = _screen_for(x, y, screens)
    return x, screen.y + screen.height - y


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
        self._save_timer = None

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
        self._schedule_save()

    def on_resized(self, width, height):
        self.temp["width"], self.temp["height"] = int(width), int(height)
        self._schedule_save()

    def _schedule_save(self):
        """Debounce the move/resize stream: save once the window settles.

        ponytail: a plain restarting threading.Timer, no event-loop scheduling --
        save_geometry only touches self.temp/manifest and writes a file, none of
        which need the UI thread. Timer is cancelled and re-armed per event, so a
        drag of any length costs exactly one write.
        """
        if self._save_timer is not None:
            self._save_timer.cancel()
        self._save_timer = threading.Timer(_SETTLE_DELAY, self.save_geometry)
        self._save_timer.daemon = True
        self._save_timer.start()

    def on_close(self):
        # A drag that ends by closing the window never settles; flush it now.
        if self._save_timer is not None:
            self._save_timer.cancel()
        self.save_geometry()

    def save_geometry(self):
        """Persist runtime state (position, resized size) to settings.json.

        ponytail: no 'screen' here -- pywebview has no cross-platform screen-index
        API, so the GTK backend's screen-remember has no equivalent. x/y/size only.
        """
        m = self.manifest
        # Compare against what this layout already holds, falling back to the
        # manifest for a layout seen for the first time.
        saved = m.layout(self.layout_key)
        changed = {}
        if (saved.get("x", m.x), saved.get("y", m.y)) != (self.temp["x"], self.temp["y"]):
            changed["x"], changed["y"] = self.temp["x"], self.temp["y"]
        if m.resizable and "width" in self.temp:
            size = (self.temp["width"], self.temp["height"])
            if (saved.get("width", m.width), saved.get("height", m.height)) != size:
                changed["width"], changed["height"] = size
        if changed:
            m.save_layout(self.layout_key, **changed)

    # ---- window setup ---------------------------------------------------

    def prepare_widget(self, manifest, module, path):
        self.manifest = manifest
        self.module = module

        # Geometry saved for this exact monitor arrangement wins; a layout with no
        # entry yet (first run, or displays just rearranged) falls back to the
        # manifest, which already carries settings.json's top-level x/y/size.
        self.layout_key = _layout_key(webview.screens)
        saved = manifest.layout(self.layout_key)
        x = saved.get("x", manifest.x)
        y = saved.get("y", manifest.y)
        width = saved.get("width", manifest.width) if manifest.resizable else manifest.width
        height = saved.get("height", manifest.height) if manifest.resizable else manifest.height

        kwargs = dict(
            title=manifest.title or "",
            width=width,
            height=height,
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
            x is not None
            and y is not None
            and _rect_on_screen(x, y, width, height, webview.screens)
        ):
            self._pending_move = (x, y)
            self.temp["x"], self.temp["y"] = x, y

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
        """Put the window back where it was, in the coordinates it was saved in.

        window.move() can't be used on macOS: pywebview reports moves in global
        coordinates (cocoa.py windowDidMove_ sends frame.origin.x straight
        through) but interprets move() relative to `self.screen`, which it fixed
        at window creation to NSScreen.mainScreen() -- the screen holding the key
        window at that moment, not the primary. Feed a global x back to move()
        and it adds that screen's origin a second time, so a widget saved on the
        primary reappears on whatever screen sits left of it, at the same offset.
        Setting the frame ourselves keeps both ends in one coordinate system.
        """
        x, y = self._pending_move
        if sys.platform != "darwin":
            self.window.move(x, y)
            return

        from AppKit import NSPoint, NSThread
        from PyObjCTools import AppHelper

        # pywebview fires `shown` on a worker thread (event.py spawns one per
        # handler); AppKit setters are main-thread only.
        if not NSThread.isMainThread():
            AppHelper.callAfter(self._restore_position)
            return

        ns = getattr(self.window, "native", None)
        if ns is None:
            self.window.move(x, y)  # same fallback as _apply_native_macos
            return
        ns.setFrameTopLeftPoint_(NSPoint(*_top_left_point(x, y, webview.screens)))

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
