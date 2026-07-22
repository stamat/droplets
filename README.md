![Droplets - Linux html/css/javascript GUI frontend framework for widgets and apps written in Python for GTK+ with webkit webview](droplets_logo.png)
========

Linux HTML/CSS/JavaScript GUI frontend framework for widgets and apps written in Python for GTK+ with webkit webview

Enables you to unleash your creativity while developing GUI frontends for Linux desktop applications or have fancy customizable easy to develop widgets on your desktop. An online store will be included in near future.

It's like Google Chrome packaged apps plus widget engine, but without a lot of constraints, and without Google Chrome. 

![SCREENSHOT](https://i.imgur.com/RUpVIui.jpg)

Security model is very simple: 
* Local apps don’t use the webview to make remote calls (loaded webpage is used only as a GUI interface), they can do everything on the system (even do CURL requests) by the privileges the apps were run on through the Python interface script which functions the JavaScript of the app can call.
* Remote apps don’t have any access to the system, but they are stored locally and can function as any web app making calls to cross domain allowed services, load remote resources or make JSONP requests.
* Hosted apps are hosted remotely, they are exactly like web apps opened in browser.

Or if you haven’t heard about Chrome apps, it is like PhoneGap for the Linux desktop combined with Dashboard Widgets, or Windows Gadgets but more secure.

**Writing a droplet?** See [`DROPLETS.md`](DROPLETS.md) — quick start, every
manifest field, runtime settings, and how to granulate what JavaScript may call
in Python (`allowed_methods`).


Notes
-----
* Origins can be local, remote and hosted. Hosted is a remote origin with a base not loaded localy. With hosted everything except manifest is remote. See how hosted applications can have local setting files

* Widgets can be either completely local or completely remote in a sense of resources. A web widget cannot have a communication with the system, a local widget cannot have a communication to the web through HTTP, only through python interface, thus disabling a chance that it can accidentaly load malicius scripts that can be changed by the third party

* Type can be app or widget. Apps should always have window decoration, widgets should not have decoration, and always have right click menu enabled

* Manifest - everything that makes the app/widget manifest itself on the screen, these values wont be changed by the users interaction
	"title": [null, 0],
	"description": [null, 0],
	"uid": [null, 0], // special identificator, generated after the first run and used for interwidget communication
	"type": ["widget", 0],
	"height": [300, 1],  // default size
	"width": [300, 1], // default size
	"icon": [null, 0],
	"executable": ["main", 0],
	"origin": ["local", 0],
	"source": ["index.html", 0],
	"skip_pager": [false, 0],
	"decorated": [false, 0], 
	"skip_taskbar": [false, 0], 
	"default_context_menu": [false, 0],
	"shape": ["rect", 0],
	"corner_radius": [0, 0],
	"resizable": [false, 0],

* Properties and settings - window behaviour flags andapplication/widget specific variables that an be changed.

TO DOs:
-------
[x] Window shape mask from the image — done: `reshapemask()` in `droplets/droplet.py` loads the PNG with `GdkPixbuf`, makes a cairo surface, and clips via `shape_combine_region` (X11 SHAPE). GTK/X11 only.

[x] Make a JavaScript API — done: the `droplets.send`/`droplets.recieve` bridge is injected as a user script in both backends (`_BRIDGE_SHIM`).

[ ] A way to name the python process? (`procname` link is dead; use `setproctitle` if ever wanted.) Low priority.

[ ] Whenever a droplet is started it invokes the interwidget communicaton system.

[x] Set StatusIcon for the app and widget manager — done on macOS: `menubar: true` adds an `NSStatusItem` whose click shows/hides the window, and `skip_taskbar: true` drops the Dock tile (accessory activation policy). The manager ships with both, so it lives in the menu bar only. GTK equivalent (`AppIndicator`) still open.

[x] Implement json validator to validate manifest — done: `Manifest.validate()` checks mandatory fields, types, enums (`origin`/`type`/`shape`) and `allowed_methods` against `manifest_pattern` (the single source of truth), and runs on every load. Removed the redundant `manifest_schema.json` stub. Field reference: `DROPLETS.md`. Settings validation is pending the settings/manifest split below.

[x] Separate settings from manifest - done: runtime state (`x`, `y`, `screen`, and resized `width`/`height`) is written to a sibling `settings.json` overlaid on load, so store updates never clobber the authored `manifest.json`. `Manifest.save_setting()` replaces the old `dump_manifest` write; `Manifest.validate_settings()` checks it. See `DROPLETS.md`.

[ ] Complete the menu and enable it with basic functionality like move toggle, stick toggle, above toggle, disable, settings invoke, reload

[x] If stick is off, remember the widget screen in settings — done: the GTK backend stores `get_screen().get_number()` to `settings.json` on focus-out when the widget isn't stuck. (Multi-X-screen `set_screen` restore is left as a `ponytail:` ceiling — near-extinct setup.)

[x] If app is resizable store the values in settings — done: both backends persist the resized `width`/`height` to `settings.json` (GTK on focus-out, pywebview on the `resized` event) only when `resizable` is set.

[x] Define a settings file — done: `settings.json`, a sibling of `manifest.json`, holds runtime keys (`x`, `y`, `screen`, `width`, `height`) and is validated by `Manifest.validate_settings()`. Format documented in `DROPLETS.md`.

[x] Build droplet process manager, and settings manager — done: `system/manager` is a droplet that lists everything in `apps/`, turns each on/off (one `droplets.py <dir>` process each, running state read from the process table) and renders a settings form from the `options` schema in each manifest. Geometry names are blacklisted as option names. See [`DROPLETS.md`](DROPLETS.md). Store browsing/installing is the remaining half.

[ ] Disable webkit to resize gtk.Window

[x] Comment the goddamn code!!! >:/ — done in the PyGObject/WebKit2 port; both backends are commented.

[ ] Include some kick ass bootstrap and the ability to theme it

[ ] build a web store service!!! Register, upload, comment and rate, install. Install from inside a droplets manager. Allow remote calls only towards the webstore and only for the manager.

[ ] A way of local widgets to invoke one another and communicate. Maybe some simple communication server like d-bus. Or something like one app can have multiple widgets or windows packed... this is a real advancement, maybe for 2.0 in some not so near future

----

Fun projects to test and perfect the framework(sorted by complexity):

[ ] Build a digital clock, calendar and a weather demo widgets

[ ] Build a simple notepad, music player, browser demo apps

[ ] Build a simple, and later more complex XMPP chat client using strophe.js

[ ] Build dock and application menu, and notification area

[ ] Try to build a live desktop, just for fun.

[ ] Build a desktop environment salvaging Xfce called Puddle that utilizes widgets and apps noted above

[ ] Build a debian distro... i always wanted that, ambicious arent i?


Backends
--------
There are two window/webview backends. The launcher picks one automatically:

* **gtk** (Linux) — GTK 3 + WebKitGTK + Cairo. The only backend with arbitrary
  pixmap window masks (X11 SHAPE). Default on Linux.
* **pywebview** (macOS/Windows) — the platform-native webview (WKWebView on
  macOS, WebView2 on Windows). Lets the project be developed and run on a Mac
  without a Linux VM. No arbitrary mask API — frameless + transparent shaping
  only (rounded/circle/PNG-alpha via CSS).

Both expose the same `droplets.send(cmd)` / `droplets.recieve(result)` JS bridge
and the same `allowed_methods` gate, so widgets run unchanged on either.

Override the auto-pick with `DROPLETS_BACKEND=gtk` or `DROPLETS_BACKEND=pywebview`.

**Running** differs by backend because the deps come from different places:

* **macOS / Windows (pywebview):** `uv sync` once, then `uv run droplets.py <dir>`
  — deps resolve from `pyproject.toml`/`uv.lock`, no manual venv. (See the macOS
  section below.)
* **Linux (gtk):** run with `python3 droplets.py <dir>` — GTK/WebKit come from
  **system** packages `uv` doesn't manage, so use the distro install below, not `uv`.

Linux (gtk backend)
-------------------
The default backend. GTK 3 + WebKitGTK + Cairo — the only backend with arbitrary
pixmap window masks (X11 SHAPE).

**Requirements:** Python 3, PyGObject (`gi`) with GTK 3.0 + WebKit2, and pycairo.
These are system packages, not pip wheels — install them from your distro.

    # Debian / Ubuntu
    sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.1

    # Fedora
    sudo dnf install python3-gobject gtk3 webkit2gtk4.1 python3-cairo

**Run a droplet:**

    python3 droplets.py apps/app-test

**Development:** the GTK backend lives entirely in `droplets/droplet.py` — it's
the only file that imports `gi`. On a Wayland session the X11 SHAPE mask
(`reshapemask`) is a no-op; force `GDK_BACKEND=x11` to route through XWayland and
keep it working:

    GDK_BACKEND=x11 python3 droplets.py apps/your-widget

macOS (pywebview backend)
-------------------------
Lets you develop and run droplets on a Mac without a Linux VM. Uses the native
WKWebView. Selected automatically off Linux; no arbitrary mask API (frameless +
transparent shaping only), but keep-below/stick/opacity are recovered natively
through the underlying `NSWindow` (see `droplet_pywebview.py`).

**Requirements:** Python 3.12+ and pywebview. With [uv](https://docs.astral.sh/uv/)
(`brew install uv`) the dependencies come straight from `pyproject.toml`/`uv.lock`:

    uv sync

pywebview pulls in **pyobjc** (AppKit/Quartz) on macOS automatically — that's
what the native window flags use, no extra install.

**Run a droplet:**

    uv run droplets.py apps/app-test

Without uv, a plain venv works the same: `python3 -m venv .venv && source
.venv/bin/activate && pip install pywebview`, then `python3 droplets.py
apps/app-test`.

**Development:** the macOS backend lives entirely in
`droplets/droplet_pywebview.py`. `backend.py` auto-picks it off Linux; force it
anywhere with `DROPLETS_BACKEND=pywebview`. `app-test` is decorated + hosted, so
it won't exercise transparency/shaping — spin up a `transparent: true`,
`decorated: false` widget to test the shaping and native-flag paths.

_(Windows also uses the pywebview backend — `pip install pywebview` pulls in
pythonnet + WebView2. Transparency is weaker there; the native-flag recovery
above is macOS-only.)_

Literature
----------
http://webkitgtk.org/reference/webkitgtk/stable/webkitgtk-webkitwebview.html

http://www.pygtk.org/docs/pygtk/class-gtkwindow.html


Author
------
Nikola Stamatovic Stamat
ivartech

Licence
-------
MIT — see the `LICENSE` file.

Note: bundled example apps may carry their own third-party licenses. The
`apps/calculator` widget is old Apple Dashboard code and stays Apple Inc.'s
property under Apple's license — see `apps/calculator/NOTICE`. It is not
covered by the MIT license above.
