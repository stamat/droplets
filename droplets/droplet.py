"""Droplet: a single widget/app window backed by a WebKit2 WebView.

Ported from PyGTK2 + WebKit1 to PyGObject (GTK 3) + WebKit2 / Python 3.
"""

import importlib.util
import json
import math
import os
import re
import urllib.request
from subprocess import call

import cairo
import gi

gi.require_version("Gtk", "3.0")
try:
    gi.require_version("WebKit2", "4.1")
except ValueError:  # older distros ship the libsoup2 build
    gi.require_version("WebKit2", "4.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, WebKit2  # noqa: E402

from . import csp  # noqa: E402
from .backend import debug_enabled  # noqa: E402
from .manifest import Manifest  # noqa: E402

# JS shim: keeps the old `droplets.send(cmd)` API but routes it through the
# WebKit2 script-message handler instead of the WebKit1 document.title hack.
_BRIDGE_SHIM = (
    "window.droplets = window.droplets || {};"
    "droplets.send = function(cmd) {"
    "  if (cmd !== undefined && cmd !== null)"
    "    window.webkit.messageHandlers.droplet.postMessage(String(cmd));"
    "};"
)


class Droplet:
    def __init__(self, path, custom_manifest=None):
        self.window = None
        self.browser = None
        self.manifest = None
        self.module = None
        self.path = None
        self.temp = {"x": 0, "y": 0}
        self.drag_handler_id = None
        self.root_url = None

        self.init_widget(path, custom_manifest)
        Gtk.main()

    # ---- module loading -------------------------------------------------

    def importFromURI(self, uri, absl=False):
        """Import a widget's Python module from a file path (imp is gone in 3.12)."""
        if not absl:
            uri = os.path.normpath(os.path.join(os.path.dirname(__file__), uri))
        path, fname = os.path.split(uri)
        mname, _ext = os.path.splitext(fname)
        source = os.path.join(path, mname) + ".py"
        if not os.path.exists(source):
            return None
        spec = importlib.util.spec_from_file_location(mname, source)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    # ---- window shaping (GTK3: cairo regions, Pixmap is gone) -----------

    @staticmethod
    def _shape(widget, surface):
        """Clip the widget's window to the opaque pixels of an ARGB surface."""
        region = Gdk.cairo_region_create_from_surface(surface)
        widget.shape_combine_region(region)
        widget.show()

    def reshaperect(self, widget, allocation, radius=0):
        w, h = allocation.width, allocation.height
        r = radius
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(surface)
        cr.set_source_rgba(0, 0, 0, 1)
        cr.new_sub_path()
        cr.arc(w - r, r, r, -math.pi / 2, 0)
        cr.arc(w - r, h - r, r, 0, math.pi / 2)
        cr.arc(r, h - r, r, math.pi / 2, math.pi)
        cr.arc(r, r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()
        cr.fill()
        self._shape(widget, surface)

    def reshapecircle(self, widget, allocation):
        w, h = allocation.width, allocation.height
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(surface)
        cr.set_source_rgba(0, 0, 0, 1)
        cr.arc(w / 2, h / 2, min(h, w) / 2, 0, 2 * math.pi)
        cr.fill()
        self._shape(widget, surface)

    def reshapemask(self, widget, allocation, mask):
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(mask)
        surface = Gdk.cairo_surface_create_from_pixbuf(pixbuf, 1, None)
        self._shape(widget, surface)

    # ---- transparency (GTK3: rgba visual + app_paintable) ---------------

    def transparent_window(self, widget):
        screen = widget.get_screen()
        visual = screen.get_rgba_visual()
        if visual is not None:
            widget.set_visual(visual)
            return True
        return False

    def set_to_transparent(self):
        self.transparent_window(self.window)
        self.window.set_app_paintable(True)
        self.browser.set_background_color(Gdk.RGBA(0, 0, 0, 0))

    # ---- window geometry persistence ------------------------------------

    def _clamp_on_monitor(self, x, y):
        """Pull a position fully into the work area of the monitor it lands on.

        A manifest's authored x/y comes from whatever display its author used,
        and a saved one can point at a monitor that has since been unplugged --
        either way the widget opens off screen. get_workarea() already excludes
        panels and docks, so a clamped widget never hides under one.
        """
        display = Gdk.Display.get_default()
        monitor = display.get_monitor_at_point(x, y) or display.get_primary_monitor()
        area = monitor.get_workarea()
        width, height = self.window.get_size()
        return (
            min(max(x, area.x), max(area.x, area.x + area.width - width)),
            min(max(y, area.y), max(area.y, area.y + area.height - height)),
        )

    def on_configure(self, w, e):
        self.temp["x"], self.temp["y"] = w.get_position()

    def on_focus_out(self, w=None, e=None):
        """Persist runtime state (position, resized size, screen) to settings.json."""
        m = self.manifest
        changed = {}
        if m.x != self.temp["x"] or m.y != self.temp["y"]:
            changed["x"], changed["y"] = self.temp["x"], self.temp["y"]
        # Resizable widgets: remember the resized dimensions.
        if m.resizable and self.window is not None:
            width, height = self.window.get_size()
            if (width, height) != (m.width, m.height):
                changed["width"], changed["height"] = width, height
        # Non-stuck widgets: remember which screen they live on.
        # ponytail: stores the X screen index via get_number(); multi-X-screen
        # restore (set_screen) is unbuilt — near-extinct setup, add if it bites.
        if not m.stick and self.window is not None:
            screen = self.window.get_screen().get_number()
            if screen != m.screen:
                changed["screen"] = screen
        if changed:
            m.save_setting(**changed)

    # ---- JS <-> Python bridge -------------------------------------------

    def _on_script_message(self, user_content_manager, message):
        """script-message-received::droplet -> dispatch to widget module."""
        self.recieve(message.get_js_value().to_string())

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
            if "gtk" in args:
                args["gtk"] = Gtk
            if "browser" in args:
                args["browser"] = self.browser
            if "window" in args:
                args["window"] = self.window
        if fn:
            result = fn(**packet.get("args", {}))
            self.send(result)

    def send(self, msg):
        # json.dumps yields a safe JS literal; raw %-interpolation broke (or let
        # a widget inject) on any payload containing quotes/newlines/</script>.
        self._run_js("droplets.recieve(%s);" % json.dumps(msg))

    def _run_js(self, script):
        self.browser.run_javascript(script, None, None, None)

    def event_to_json(self, w, *args):
        """Convert a GDK event (or drag context) to JSON and hand it to a JS callback."""
        data = {}
        if isinstance(args[0], Gdk.Event):
            data = self.attrs_to_dict(args[0])
            data["type"] = args[0].type.value_name
        elif isinstance(args[0], Gdk.DragContext):
            data = {
                "targets": args[0].list_targets(),
                "uris": args[3].get_uris(),
                "x": args[1],
                "y": args[2],
                "text": args[3].get_text(),
            }
        self._run_js("%s('%s');" % (args[-1], json.dumps(data)))

    @staticmethod
    def attrs_to_dict(obj):
        result = {}
        for name in dir(obj):
            attr = getattr(obj, name)
            if isinstance(attr, (str, int, bool, float)):
                result[name] = attr
        return result

    # ---- droplet_* actions callable from JS -----------------------------

    def droplet_connect(self, object, event, callback):
        obj = getattr(self, object)
        obj.connect(event, self.event_to_json, callback)

    def droplet_drag(self, button, x, y, time):
        self.window.begin_move_drag(button, int(x), int(y), time)

    def drag_event_wrapper(self, w, e):
        if e.button == 1:
            self.droplet_drag(e.button, e.x_root, e.y_root, e.time)

    def droplet_move_enable(self, browser=None, manifest=None):
        if browser is None:
            browser = self.browser
        if manifest is None:
            manifest = self.manifest
        self.drag_handler_id = browser.connect("button-press-event", self.drag_event_wrapper)
        manifest.drag = True

    def droplet_move_disable(self, browser=None, manifest=None):
        if browser is None:
            browser = self.browser
        if manifest is None:
            manifest = self.manifest
        browser.disconnect(self.drag_handler_id)
        manifest.drag = False

    def droplet_move(self, x, y):
        self.window.move(int(x), int(y))

    def droplet_deactivate(self, w=None, e=None):
        self.on_focus_out()
        Gtk.main_quit()

    # ---- context menu ---------------------------------------------------

    def toggleProperty(self, w, e):
        label = w.get_label()
        parsed = re.match(r"^(?P<pref>.*:\s*)(?P<state>.*)$", label)
        state = parsed.group("state").lower()
        pref = parsed.group("pref")
        action = re.match(r"^\s*(?P<action>[a-zA-Z]*)\s*:\s*$", pref).group("action").lower()

        if state == "off":
            fn = getattr(self, "droplet_" + action + "_disable")
            w.set_label(pref + "On")
        elif state == "on":
            fn = getattr(self, "droplet_" + action + "_enable")
            w.set_label(pref + "Off")
        fn()

    def widgetContextMenu(self):
        menu = Gtk.Menu()
        properties_menu = Gtk.Menu()
        remove_menu = Gtk.Menu()

        def detachFn(*args):
            print(args)

        menu.attach_to_widget(self.browser, detachFn)

        move = Gtk.MenuItem(label="Move: Off")
        stick = Gtk.MenuItem(label="Stick: Off")
        bottom = Gtk.MenuItem(label="Bottom: Off")
        above = Gtk.MenuItem(label="Above: Off")
        properties = Gtk.MenuItem(label="Properties")
        properties.set_submenu(properties_menu)
        settings = Gtk.MenuItem(label="Settings")

        remove_submenu = Gtk.MenuItem(label="Deactivate")
        remove_submenu.set_submenu(remove_menu)
        remove = Gtk.MenuItem(label="X")
        remove_menu.append(remove)

        properties_menu.append(move)
        properties_menu.append(stick)
        properties_menu.append(bottom)
        properties_menu.append(above)
        menu.append(properties)
        menu.append(settings)
        menu.append(remove_submenu)
        menu.show_all()

        move.connect("button-press-event", self.toggleProperty)
        remove.connect("button-press-event", self.droplet_deactivate)

        def _on_button_press_event(widget, event, menu):
            if event.button == 3:
                menu.popup_at_pointer(event)

        self.browser.connect("button-press-event", _on_button_press_event, menu)

    # ---- window setup ---------------------------------------------------

    def prepare_widget(self, manifest, module, path):
        window = Gtk.Window()
        self.window = window
        self.manifest = manifest
        self.module = module

        # Bridge: JS -> Python over a WebKit2 script-message handler.
        ucm = WebKit2.UserContentManager()
        ucm.register_script_message_handler("droplet")
        ucm.connect("script-message-received::droplet", self._on_script_message)
        ucm.add_script(
            WebKit2.UserScript.new(
                _BRIDGE_SHIM,
                WebKit2.UserContentInjectedFrames.TOP_FRAME,
                WebKit2.UserScriptInjectionTime.START,
                None,
                None,
            )
        )
        browser = WebKit2.WebView.new_with_user_content_manager(ucm)
        self.browser = browser

        if debug_enabled():
            # See backend.debug_enabled. Unlike the pywebview backend we can't
            # rely on right-click -> "Inspect Element": the WebKit context menu
            # is suppressed for widgets (see default_context_menu below) and
            # right-click already pops the droplet's own menu. So open the
            # inspector outright, and keep it detached -- its default is to dock
            # inside the web view, which is useless in a 140x140 widget.
            browser.get_settings().set_enable_developer_extras(True)
            inspector = browser.get_inspector()
            inspector.connect("attach", lambda *a: True)
            # Deferred: at this point the web view isn't realized and the window
            # hasn't been shown yet (window.show_all() is further down).
            GLib.idle_add(inspector.show)

        window.set_resizable(manifest.resizable)
        window.set_keep_below(manifest.below)
        window.set_keep_above(manifest.above)
        window.set_skip_taskbar_hint(manifest.skip_taskbar)
        window.set_skip_pager_hint(manifest.skip_pager)
        window.set_decorated(manifest.decorated)

        if manifest.transparent:
            self.set_to_transparent()

        if manifest.title is not None:
            window.set_title(manifest.title)

        if manifest.stick:
            window.stick()

        if manifest.icon is not None:
            window.set_icon_from_file(path + manifest.icon)

        if manifest.drag:
            self.droplet_move_enable(browser, manifest)

        window.connect("configure-event", self.on_configure)
        window.connect("focus-out-event", self.on_focus_out)
        window.connect("destroy", self.droplet_deactivate)

        settings = browser.get_settings()
        settings.set_property("enable-webaudio", True)
        settings.set_property("enable-webgl", True)
        settings.set_property("default-charset", "utf-8")
        settings.set_property("enable-page-cache", True)
        if manifest.origin == "local":
            settings.set_property("enable-universal-access-from-file-uris", True)

        # No default WebKit context menu unless the manifest asks for it.
        if not manifest.default_context_menu:
            browser.connect("context-menu", lambda *a: True)

        self.widgetContextMenu()

        # Navigation / response policy (replaces WebKit1 *-policy-decision-requested).
        browser.connect("decide-policy", self._on_decide_policy)

        # Subresource isolation (WebKit1's banRemoteRequests) is now handled by
        # the per-tier CSP baked into local documents (see load_widget +
        # droplets/csp.py): remote script/fetch/img/frame are blocked at parse
        # time. decide-policy below still blocks top-level/frame *navigation* off
        # file:// for local origins as a second layer.

        child = browser
        if manifest.type == "app":
            child = Gtk.ScrolledWindow()
            child.add(browser)
        window.add(child)

        window.resize(manifest.width, manifest.height)

        if manifest.shape == "roundedrect":
            window.connect("size-allocate", self.reshaperect, manifest.corner_radius)
        if manifest.shape == "circle":
            window.connect("size-allocate", self.reshapecircle)
        if manifest.shape == "mask":
            window.connect("size-allocate", self.reshapemask, manifest.shape_mask)

        if not manifest.hidden:
            window.show_all()

        if manifest.x is not None and manifest.y is not None:
            window.move(*self._clamp_on_monitor(manifest.x, manifest.y))

        browser.connect("load-changed", self._on_load_changed, manifest.opacity)

        return window, browser

    def _on_load_changed(self, web_view, load_event, opacity):
        if load_event == WebKit2.LoadEvent.FINISHED:
            self.window.set_opacity(opacity)

    def _on_decide_policy(self, web_view, decision, decision_type):
        if decision_type == WebKit2.PolicyDecisionType.RESPONSE:
            # Only render text/html; ignore other main/frame responses.
            if decision.get_response().get_mime_type() != "text/html":
                decision.ignore()
                return True
            return False

        if decision_type not in (
            WebKit2.PolicyDecisionType.NAVIGATION_ACTION,
            WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION,
        ):
            return False

        nav_action = decision.get_navigation_action()
        uri = nav_action.get_request().get_uri()
        is_initial = nav_action.get_navigation_type() == WebKit2.NavigationType.OTHER

        if self.manifest.origin == "local":
            if not uri.startswith("file://"):
                decision.ignore()
                return True
            if is_initial and self.root_url is None:
                self.root_url = uri.rsplit("/", 1)[0]
                decision.use()
                return True
            if not uri.startswith(self.root_url):
                decision.ignore()
                call(["xdg-open", uri])
                return True
            return False

        # remote / hosted
        if is_initial and self.root_url is None:
            self.root_url = uri.rsplit("/", 1)[0]
            decision.use()
            return True
        if not uri.startswith(self.root_url):
            decision.ignore()
            return True
        return False

    # ---- loading --------------------------------------------------------

    def load_widget(self, browser, origin, source):
        if origin == "hosted":
            browser.load_uri(source)
            return
        file = os.path.abspath(source)
        if origin == "local":
            # Enforce the local tier: bake the per-tier CSP into the entry
            # document and load it via load_html against its own directory as
            # base_uri. The file:// base keeps the widget's origin + relative
            # resources working, while the parse-time meta CSP blocks every
            # remote subresource (script/fetch/img/frame) -- the isolation the
            # README promises. Without this a local widget could pull a remote
            # <script> and reach the Python bridge (RCE). See droplets/csp.py.
            base = "file://" + urllib.request.pathname2url(os.path.dirname(file)) + "/"
            with open(file, "r", encoding="utf-8") as f:
                html = csp.inject(f.read(), origin)
            self.root_url = base.rstrip("/")
            browser.load_html(html, base)
            return
        # remote: local files, but the web is allowed (no bridge) -> no CSP.
        browser.load_uri("file://" + urllib.request.pathname2url(file))

    def init_widget(self, path, custom_manifest=None):
        if not path.endswith("/"):
            path = path + "/"

        path_to_manifest = custom_manifest if custom_manifest is not None else path + "manifest.json"

        manifest = Manifest(path_to_manifest)
        self.temp["x"] = manifest.x
        self.temp["y"] = manifest.y
        module = self.importFromURI(os.path.join(path, manifest.executable), True)
        window, browser = self.prepare_widget(manifest, module, path)

        self.load_widget(browser, manifest.origin, path + manifest.source)

        return manifest, module, window, browser
