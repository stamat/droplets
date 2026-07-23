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

import collections
import json
import os
import re
import sys
import threading
import traceback
import urllib.request

import webview  # pip install pywebview  (+ pyobjc on macOS, pythonnet on Windows)

from . import server
from .backend import debug_enabled
from .executable import StdioExecutable, load_executable
from .manifest import Manifest
from .utils import DRAG_GRIP_JS

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
# Drag grip (utils.DRAG_GRIP_JS): a full-surface app (the calculator's keypad)
# leaves no bare pixel to grab, and easy_drag=True would hijack every button
# press into a window move. The grip's .pywebview-drag-region hands the move to
# Cocoa natively (customize.js -> pywebviewMoveWindow), sidestepping the
# global/screen-relative coordinate math macOS makes painful here (see
# _apply_native_macos), AND works with easy_drag off -- so it moves the window
# for every widget regardless of the manifest `drag` flag.
_BRIDGE_SHIM_TAG = "<script>" + _BRIDGE_SHIM + DRAG_GRIP_JS + "</script>"

# Seconds of stillness that count as "the drag is over". Cocoa's windowDidMove_
# fires on every frame of a drag (easy_drag included), and pywebview has no
# drag-end event, so geometry is written once the stream goes quiet.
_SETTLE_DELAY = 0.5


# Room left at the top of a display so a clamped widget doesn't land under the
# menu bar. ponytail: a constant, because pywebview's Screen carries frame() and
# not visibleFrame() -- no work area to ask. Raise it if a notch clips a widget.
_TOP_MARGIN = 25


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


def _clamp_on_screen(x, y, width, height, screens):
    """Pull a window rect fully onto the display it lands on.

    The last-resort backstop after _remap_position (or the only step when there
    is no history to remap from): a manifest x/y authored on someone else's
    larger display, or coordinates left over from a display that is no longer
    attached. Trusting those is what opens a widget off screen on its first run.

    x is global while y is measured down from its own screen's top edge (see
    _screen_for), so the two axes clamp against different frames.
    """
    s = _screen_for(x, y, screens)
    return (
        min(max(x, s.x), max(s.x, s.x + s.width - width)),
        min(max(y, _TOP_MARGIN), max(_TOP_MARGIN, s.height - height)),
    )


# A screen recovered from a layout key: same x/y/width/height a webview Screen
# exposes, which is all the geometry helpers touch.
_Rect = collections.namedtuple("_Rect", "x y width height")
_KEY_PART = re.compile(r"^(\d+)x(\d+)([+-]\d+)([+-]\d+)$")


def _screens_from_key(key):
    """Inverse of _layout_key: the screens a saved arrangement was made of.

    Lets a position saved under one arrangement be re-placed under another --
    the old screen sizes are the only extra thing the remap needs, and the key
    already carries them. Empty on a malformed key (never remap off a guess).
    """
    screens = []
    for part in key.split("|"):
        m = _KEY_PART.match(part)
        if not m:
            return []
        w, h, x, y = (int(g) for g in m.groups())
        screens.append(_Rect(x, y, w, h))
    return screens


def _source_layout(x, y, layouts):
    """The layout key whose saved position is (x, y).

    save_layout mirrors every save to the top-level x/y the fallback reads, so
    the arrangement a position was last saved in is the one whose entry matches.
    None when nothing does (nothing saved yet -> no history to remap from).
    """
    for key, geom in layouts.items():
        if geom.get("x") == x and geom.get("y") == y:
            return key
    return None


def _nearest_screen(rect, screens):
    """The current screen whose centre is closest to `rect`'s centre.

    Maps an old screen to its counterpart now: a display left untouched while
    another changed is still nearest itself, so a widget on it stays put; the
    survivor of an unplug is nearest the display that is gone.
    """
    cx, cy = rect.x + rect.width / 2, rect.y + rect.height / 2
    return min(
        screens,
        key=lambda s: (s.x + s.width / 2 - cx) ** 2 + (s.y + s.height / 2 - cy) ** 2,
    )


def _rects(screens):
    """Snapshot the live webview.screens proxy into comparable, stable rects."""
    return [_Rect(s.x, s.y, s.width, s.height) for s in screens]


def _remap_between(x, y, width, height, old_screens, new_screens):
    """Proportional map of a position from one arrangement onto another.

    x is global, y is screen-relative-down (the Cocoa convention _screen_for and
    the stored settings both speak), so the two axes scale against different
    frames. Clamped so rounding or a smaller display can't push it off-screen.
    """
    old = _screen_for(x, y, old_screens)
    new = _nearest_screen(old, new_screens)
    fx = (x - old.x) / old.width
    fy = y / old.height
    nx = new.x + round(fx * new.width)
    ny = round(fy * new.height)
    return _clamp_on_screen(nx, ny, width, height, new_screens)


def _remap_position(x, y, width, height, layouts, screens):
    """Keep a widget at ~the same relative spot when the display setup changed.

    Launch-time counterpart to the live handler (_on_screens_changed): for an
    arrangement seen for the first time -- resolution changed or a monitor was
    added/removed while the widget was NOT running -- recover the fractional
    place from the screens the position was last saved on. Falls back to a plain
    clamp when there is no saved history to read a fraction from (a first-ever
    run off the authored manifest x/y).

    ponytail: matches the source arrangement by (x, y) equality; two arrangements
    saved at the identical spot are indistinguishable, and either is fine to
    scale from. A per-layout save timestamp is the upgrade path if it ever bites.
    """
    key = _source_layout(x, y, layouts)
    old_screens = _screens_from_key(key) if key else []
    if not old_screens:
        return _clamp_on_screen(x, y, width, height, screens)
    return _remap_between(x, y, width, height, old_screens, screens)


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
        # Live screen-change remap (macOS): last-seen layout + the NSNotification
        # observer token, so it can be diffed against and removed on close.
        self._screens = None
        self._screen_observer = None
        # Set only for a `menubar` droplet on macOS (see _install_status_item);
        # their presence is what makes the close button hide instead of quit.
        self._status_item = None
        self._status_target = None
        self._quitting = False

        self.init_widget(path, custom_manifest)
        # Name the Dock/menu-bar before NSApplication registers with the Dock.
        self._set_app_name()
        # debug=True turns on developer extras -> right-click "Inspect Element".
        webview.start(debug=debug_enabled())

    def _set_app_name(self):
        """Rename the menu-bar app menu from `python3.12` to the manifest title.

        A bundle-less Python process shows its executable name. The menu-bar app
        menu reads CFBundleName off the main bundle's info dictionary, so
        overwriting that entry renames it. ponytail: mutating the live info dict
        is the long-standing bundle-less-pyobjc trick (rumps et al). It does NOT
        reach the Dock tile tooltip or Activity Monitor -- those read
        LaunchServices' display name, which has no working runtime lever; a real
        .app bundle with CFBundleName (packaging) is the only fix for those.
        """
        if sys.platform != "darwin" or not self.manifest.title:
            return
        from Foundation import NSBundle

        bundle = NSBundle.mainBundle()
        info = bundle and (bundle.localizedInfoDictionary() or bundle.infoDictionary())
        if info is not None:
            info["CFBundleName"] = self.manifest.title

    # ---- JS <-> Python bridge (mirrors the GTK backend) -----------------

    def recieve(self, msg):
        if msg == "null" or self.manifest.origin != "local":
            return
        packet = json.loads(msg)
        args = packet.get("args", {})
        if packet["method"].startswith("droplet_"):
            fn = getattr(self, packet["method"], None)
            if fn:
                self.send(fn(**args))
            return
        # Optional allowlist: when manifest.allowed_methods is set, only those
        # module functions are callable from JS (the hybrid-tier gate). Absent
        # (null) keeps the legacy behaviour of exposing every module function.
        allowed = getattr(self.manifest, "allowed_methods", None)
        if allowed is not None and packet["method"] not in allowed:
            return
        fn = getattr(self.module, packet["method"], None)
        if not fn:
            return
        # A live window handle is only injectable into an in-process Python
        # module; a StdioExecutable child gets JSON-serialisable args only.
        # (GTK backend also injects gtk/browser; pywebview only has window.)
        if "window" in args and not isinstance(self.module, StdioExecutable):
            args["window"] = self.window
        try:
            self.send(fn(**args))
        except Exception as e:
            # Report to the widget's JS instead of crashing the bridge handler.
            # (StdioExecutable also logs the child's own stderr separately.)
            traceback.print_exc()
            self.send({"error": "%s: %s" % (type(e).__name__, e)})

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

    def droplet_options(self):
        """Current values of the options the manifest declares (user's or default)."""
        return self.manifest.option_values()

    def droplet_deactivate(self):
        self.on_close()
        if isinstance(self.module, StdioExecutable):
            self.module.close()
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

        if self._status_item is not None and not self._quitting:
            # A menu-bar droplet has no Dock tile, so quitting on the close
            # button would strand the user: the window is gone and the only
            # handle left is a status item belonging to a dead process. Hide
            # instead -- Quit lives in that item's menu. Returning False here
            # cancels the close (webview.event.Event.set). Keep the screen
            # observer: the widget is still alive, just hidden.
            self.window.hide()
            return False

        # Real close (not a menu-bar hide): drop the screen observer.
        if self._screen_observer is not None:
            from Foundation import NSNotificationCenter

            NSNotificationCenter.defaultCenter().removeObserver_(self._screen_observer)
            self._screen_observer = None

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
        # keeps second-screen restore working. No x/y at all (nothing authored,
        # nothing saved) leaves the window where pywebview puts it: centred on
        # the primary display.
        self._pending_move = None
        if x is not None and y is not None:
            if "x" not in saved:
                # Not saved for this arrangement -> the display setup changed
                # (resolution, or a monitor added/removed) since this position was
                # stored, or it is an authored manifest x/y. Re-place it at the
                # same relative spot on the current screens; _remap_position falls
                # back to a plain clamp when there is no history to scale from.
                x, y = _remap_position(
                    x, y, width, height,
                    manifest.settings.get("layouts", {}), webview.screens,
                )
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

        # A widget is a fixed-size window, so its page must not reserve a
        # scrollbar gutter (see _hide_scrollbars). `type: app` windows are real
        # windows and keep theirs.
        if manifest.type != "app":
            window.events.loaded += self._hide_scrollbars

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
        from AppKit import (
            NSFloatingWindowLevel,
            NSNormalWindowLevel,
            NSThread,
            NSWindowStyleMaskBorderless,
            NSWindowStyleMaskResizable,
        )
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

        if not manifest.skip_taskbar:
            # A droplet that keeps its Dock tile runs with the generic Python
            # icon. Swap in the manifest icon as the Dock tile.
            # ponytail: setApplicationIconImage_ is the runtime way in -- a real
            # bundle icon (CFBundleIconFile) needs an .app bundle (packaging),
            # and an accessory/menubar droplet has no Dock tile to dress anyway.
            from AppKit import NSApplication, NSImage

            icon = manifest.icon and os.path.join(self.path, manifest.icon)
            image = NSImage.alloc().initWithContentsOfFile_(icon) if icon else None
            if image is not None:
                NSApplication.sharedApplication().setApplicationIconImage_(image)

        # ponytail: the Dock tile tooltip and Activity Monitor read
        # LaunchServices' display name, which is fixed at app registration and
        # has no public runtime API. The private lever
        # (_LSSetApplicationInformationItem / _kLSDisplayNameKey) resolves but
        # did not take, so it's dropped -- the stable fix is a real .app bundle
        # with CFBundleName (packaging). The menu-bar app menu IS renamed via
        # _set_app_name.

        if not manifest.decorated:
            # macOS rounds the corners of every titled window, and pywebview
            # keeps NSTitledWindowMask even for frameless ones (it only adds
            # NSFullSizeContentView on top and hides the buttons). So the
            # widget's own shape -- CSS border-radius, PNG alpha -- ends up
            # clipped by a second rectangle rounded to the system's radius
            # rather than the manifest's. A borderless mask drops the theme
            # frame entirely (NSThemeFrame -> NSNextStepFrame) and the rounding
            # with it. The resizable bit is kept: borderless windows lose
            # edge-resizing otherwise, and it does not bring the rounding back.
            ns.setStyleMask_(
                NSWindowStyleMaskBorderless
                | (NSWindowStyleMaskResizable if manifest.resizable else 0)
            )
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

        if manifest.skip_taskbar:
            # The Dock is macOS's taskbar. Accessory is LSUIElement applied at
            # runtime: no Dock tile, no app menu -- what a widget wants, and what
            # lets the manager live in the menu bar alone. `app` droplets leave
            # skip_taskbar false and keep their Dock tile.
            from AppKit import NSApplication, NSApplicationActivationPolicyAccessory

            NSApplication.sharedApplication().setActivationPolicy_(
                NSApplicationActivationPolicyAccessory
            )
        if manifest.menubar:
            self._install_status_item(ns)

        self._observe_screen_changes()

    def _observe_screen_changes(self):
        """Reposition the widget when the display setup changes while it runs.

        macOS posts NSApplicationDidChangeScreenParameters on any resolution or
        monitor add/remove; pywebview surfaces no such event, so we observe it
        natively (same AppKit reach as the window flags). The block runs on the
        main queue, so _on_screens_changed is already on the main thread. Runs
        once -- _apply_native_macos fires on `shown`, which fires once.
        """
        from AppKit import NSApplication, NSOperationQueue
        from Foundation import NSNotificationCenter

        self._screens = _rects(webview.screens)
        self._screen_observer = NSNotificationCenter.defaultCenter().addObserverForName_object_queue_usingBlock_(
            "NSApplicationDidChangeScreenParametersNotification",
            NSApplication.sharedApplication(),
            NSOperationQueue.mainQueue(),
            lambda note: self._on_screens_changed(),
        )

    def _on_screens_changed(self):
        # The notification also fires for colour-profile/brightness changes, so
        # diff the geometry and do nothing when it did not actually change.
        new = _rects(webview.screens)
        old, self._screens = self._screens, new
        if not old or not new or old == new:
            return

        # The arrangement changed -> so did its fingerprint; save under the new
        # one from here on (see save_geometry).
        self.layout_key = _layout_key(webview.screens)
        saved = self.manifest.layout(self.layout_key)
        if "x" in saved:
            # This arrangement was seen before -> restore its remembered spot
            # rather than re-deriving one (per-resolution memory).
            x, y = saved["x"], saved["y"]
        else:
            width = self.temp.get("width", self.manifest.width)
            height = self.temp.get("height", self.manifest.height)
            x, y = _remap_between(self.temp["x"], self.temp["y"], width, height, old, new)
        if (x, y) == (self.temp["x"], self.temp["y"]):
            return
        self.temp["x"], self.temp["y"] = x, y
        self._pending_move = (x, y)
        self._restore_position()  # already main-thread; sets the NSWindow frame
        self._schedule_save()

    def _install_status_item(self, ns):
        """Put the droplet in the macOS menu bar, with a show/hide + quit menu.

        For a droplet that is not in the Dock (skip_taskbar) this is the only
        handle the user has on it, so it carries the quit action too. Runs on
        the main thread -- _apply_native_macos has already hopped there.
        """
        from AppKit import (
            NSApplication,
            NSImage,
            NSMakeSize,
            NSMenu,
            NSMenuItem,
            NSStatusBar,
            NSVariableStatusItemLength,
        )
        from Foundation import NSObject

        if self._status_item is not None:
            return
        droplet = self

        class _StatusTarget(NSObject):
            # ObjC needs a real object for target/action. Defined here rather
            # than at module scope so importing this module stays platform-free.
            def toggle_(self, _sender):
                if ns.isVisible():
                    ns.orderOut_(None)
                else:
                    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
                    ns.makeKeyAndOrderFront_(None)

            def quit_(self, _sender):
                # terminate_ does not run the closing handler, so geometry is
                # flushed here; the flag keeps on_close from hiding the window
                # instead of letting it go.
                droplet._quitting = True
                droplet.on_close()
                # Let the widget module clean up before the process dies --
                # the manager uses this to terminate the droplets it launched.
                hook = getattr(droplet.module, "on_quit", None)
                if callable(hook):
                    hook()
                NSApplication.sharedApplication().terminate_(None)

        item = NSStatusBar.systemStatusBar().statusItemWithLength_(
            NSVariableStatusItemLength
        )
        button = item.button()
        icon = self.manifest.icon and os.path.join(self.path, self.manifest.icon)
        image = NSImage.alloc().initWithContentsOfFile_(icon) if icon else None
        if image is None and hasattr(NSImage, "imageWithSystemSymbolName_accessibilityDescription_"):
            # No icon shipped: the generic droplet glyph beats a logo squeezed
            # into 18px. SF Symbols is macOS 11+, hence the check.
            image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                "drop.fill", self.manifest.title or "Droplet"
            )
        if image is not None:
            image.setSize_(NSMakeSize(18, 18))
            image.setTemplate_(True)  # tints itself for light/dark menu bars
            button.setImage_(image)
        else:
            button.setTitle_(self.manifest.title or "Droplet")

        target = _StatusTarget.alloc().init()
        menu = NSMenu.alloc().init()
        show = menu.addItemWithTitle_action_keyEquivalent_(
            "Show %s" % (self.manifest.title or "Droplet"), "toggle:", ""
        )
        show.setTarget_(target)
        menu.addItem_(NSMenuItem.separatorItem())
        quit_item = menu.addItemWithTitle_action_keyEquivalent_("Quit", "quit:", "q")
        quit_item.setTarget_(target)
        item.setMenu_(menu)

        # Both held only so ObjC's unowned references stay alive.
        self._status_item, self._status_target = item, target

    def _hide_scrollbars(self):
        """Take the main-frame scrollbar off a widget's page.

        macOS scrollbars set to "Automatic" (the default) means legacy,
        non-overlay scrollbars whenever a mouse is attached, and WebKit then
        reserves a permanent 17px gutter for them. Two things go wrong at once
        on a transparent frameless widget: the page lays out 17px narrower than
        the window it was authored for (measured: clientWidth 203 in a 220px
        window), and the scrollbar track paints an opaque light strip down the
        side of a widget that is otherwise transparent -- which reads as a white
        rectangle sticking out from behind the widget.

        ponytail: overflow on documentElement is the only thing that gives the
        gutter back. ::-webkit-scrollbar rules style the thumb but the main
        frame keeps reserving the space (measured: clientWidth stays 203).
        Elements with their own overflow still scroll; only the window-level
        scroll goes, which a fixed-size widget never wanted.

        Runs on `loaded` so it re-applies on every navigation. Not darwin-gated:
        WebView2 reserves the same gutter.
        """
        self.window.evaluate_js("document.documentElement.style.overflow = 'hidden'")

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
        module = load_executable(os.path.join(path, manifest.executable), True)
        window = self.prepare_widget(manifest, module, path)

        return manifest, module, window
