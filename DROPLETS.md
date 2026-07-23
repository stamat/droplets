# Droplets — writing a droplet

A **droplet** is a directory with a `manifest.json`, a web front-end
(HTML/CSS/JS), and — for local droplets — an optional Python backend the
front-end calls over a bridge. This is the reference for authoring one:
quick start, every manifest field, runtime settings, and how to granulate what
JavaScript is allowed to call.

For the bigger picture (security tiers, backends) see [`README.md`](README.md);
for packaging/distribution see [`PACKAGING.md`](PACKAGING.md).

---

## Quick start

Minimum viable widget — a directory with two files:

```
myclock/
├── manifest.json
└── index.html
```

`manifest.json` (only `width` and `height` are mandatory):

```json
{
    "title": "My Clock",
    "width": 140,
    "height": 140,
    "decorated": false,
    "transparent": true,
    "shape": "circle",
    "above": true,
    "stick": true,
    "drag": true
}
```

`index.html` — any web page. To talk to Python, use the injected bridge:

```html
<script>
  // send a command to the Python backend; the reply arrives in recieve()
  droplets.recieve = function (result) { console.log("from python:", result); };
  droplets.send(JSON.stringify({ method: "hello", args: {} }));
</script>
```

Run it:

```sh
uv run droplets.py apps/myclock       # or any path to the directory
```

`uv run` pulls the deps from `uv.lock` — no manual venv. That's the
macOS/Windows (pywebview) path. On **Linux/GTK** the webview comes from system
packages `uv` can't see, so run it with `python3 droplets.py apps/myclock`
instead — see [`README.md`](README.md) for the distro packages.

Add a Python backend only if the widget needs the system — see
[cmd access](#cmd-access-granulation). Pure web widgets skip `main.py` entirely.

---

## Debugging a droplet

A droplet is a web page, so use the browser's own inspector:

```sh
DROPLETS_DEBUG=1 uv run droplets.py apps/myclock   # Linux/GTK: python3 droplets.py …
```

Full DOM tree, console, network, JS breakpoints — `console.log` from your widget
shows up there, not in the terminal. How it opens differs per backend:

| Platform | Inspector |
|---|---|
| macOS / Windows | right-click the widget → **Inspect Element** |
| Linux (GTK) | opens on its own at launch, in its own window |

Linux differs because a widget's right-click is already taken: the droplet's own
menu (Move/Stick/Deactivate) is bound to it, and the WebKit context menu is
suppressed unless the manifest sets `default_context_menu`.

The console runs inside your widget, so `droplets.send(...)` is callable from it
— handy for exercising your `main.py` methods by hand. That is also why it stays
off by default: for a `local` droplet the inspector is a direct line to the
Python bridge.

Two things that look like bugs but aren't:

- Errors thrown by the widget go to the inspector console, not the terminal.
  A blank widget with a clean terminal usually means a JS error on the first
  line — open the console.
- Outside Linux a `local` droplet is served from `http://127.0.0.1:<port>/<random>/`,
  not opened as a `file://` path — that is what lets its CSP arrive as a real
  response header and what gives it access to its own assets. The port is stable
  per widget directory; the path segment is new every launch and is not
  guessable, so nothing else on the machine can read the widget over that port.
  You are still editing your own files; nothing is generated or copied.

---

## The three origins (tiers)

`origin` decides how much of the world and the system a droplet can touch. It's
the security model — pick the smallest that works.

| `origin` | Loads from | Web access | Python bridge | Use for |
|----------|-----------|------------|---------------|---------|
| `local` *(default)* | local files | **blocked** (per-tier CSP) | **yes** | widgets that need the system (shell, files, sensors) |
| `remote` | local files | yes (it's a web app) | no | web widgets pulling remote resources / JSONP |
| `hosted` | a remote URL | yes | no | a hosted web app in a frameless window |

Only `local` gets the Python bridge, and only `local` is locked down by CSP so a
remote `<script>` can't smuggle code onto the system. `remote`/`hosted` are
"just a web page" — no bridge, no system reach. See `droplets/csp.py`.

---

## Manifest fields

All fields, their defaults, and what they do. `manifest_pattern` at the repo
root is the source of truth; the loader (`droplets/manifest.py`) validates every
manifest against it on load. **Mandatory:** `width`, `height`. Unknown keys are
allowed (passed through untouched).

### Identity

| Field | Default | Type | Meaning |
|-------|---------|------|---------|
| `title` | `null` | string | Window title / label. |
| `description` | `null` | string | Human description. |
| `uid` | `null` | string | Unique id; generated after first run, used for interwidget comms. |
| `type` | `"widget"` | enum `widget`\|`app` | `app` → decorated window; `widget` → frameless + context menu. |
| `icon` | `null` | string | Icon file path. Also the menu-bar glyph when `menubar` is set. |
| `screenshots` | `[]` | list of strings | Demo image paths, shown as a gallery in the manager. |

### Loading

| Field | Default | Type | Meaning |
|-------|---------|------|---------|
| `origin` | `"local"` | enum `local`\|`remote`\|`hosted` | Security tier (see above). |
| `source` | `"index.html"` | string | Entry document (a URL when `origin: hosted`). |
| `executable` | `"main"` | string | Backend loaded for the bridge on `local`. `main.py` (in-process Python) by default; `main.js`/`main.rb` run as a child process instead — see [Non-Python executables](#non-python-executables-node-ruby). |

### Size & shape

| Field | Default | Type | Meaning |
|-------|---------|------|---------|
| `width` | `300` | int | **Mandatory.** Window width. |
| `height` | `300` | int | **Mandatory.** Window height. |
| `resizable` | `false` | bool | Allow the user to resize. |
| `fit_content` | `false` | bool | Size the window to the document instead of `width`/`height`, and follow it as the content changes (see below). `local` tier only; don't combine with `resizable`. |
| `shape` | `"rect"` | enum `rect`\|`roundedrect`\|`circle`\|`mask` | Window silhouette. |
| `corner_radius` | `0` | int | Corner radius when `shape: roundedrect`. |
| `shape_mask` | `null` | string | PNG path for `shape: mask` (arbitrary silhouette). **GTK/X11 only** — no-op elsewhere; use `transparent` + PNG-alpha for cross-platform shaping. |
| `transparent` | `false` | bool | RGBA transparent window (needed for non-rect shapes). |
| `opacity` | `1` | number | Whole-window opacity, `0`–`1`. |

> **`fit_content`.** A webview never pushes its content size up to the window,
> so with `fit_content: true` a tiny script measures `document.documentElement`
> and resizes the window to match — once at load, then on every change via a
> `ResizeObserver`. `width`/`height` still seed the initial window before the
> first measure. Two things to know:
> - **Height fits for free; width needs CSS.** A block-level `<body>` fills the
>   viewport width, so measured width won't shrink below the window unless your
>   root is content-sized — add `html, body { width: max-content }` (or make the
>   root `display: inline-block`). Height already tracks content.
> - **`local` tier only**, and don't pair it with `resizable` — the auto-size
>   would fight (and overwrite) the user's manual size. Size is not persisted for
>   a `fit_content` widget; it is re-measured every launch.
>
> Any widget can also resize itself on demand — `fit_content` or not — by
> calling `droplets.send(JSON.stringify({ method: "droplet_resize", args: { width, height } }))`.

### Window behaviour

| Field | Default | Type | Meaning |
|-------|---------|------|---------|
| `decorated` | `false` | bool | Show the window titlebar/border. |
| `above` | `false` | bool | Keep above other windows. |
| `below` | `false` | bool | Pin to the desktop, behind windows (widget style). |
| `stick` | `false` | bool | Show on all workspaces / Spaces. |
| `drag` | `false` | bool | Drag the window by its body. |
| `hidden` | `false` | bool | Start hidden. |
| `skip_taskbar` | `false` | bool | Hide from the taskbar — **the Dock on macOS**. |
| `skip_pager` | `false` | bool | Hide from the pager. |
| `menubar` | `false` | bool | macOS: put the droplet in the menu bar; clicking the item shows/hides its window. |
| `default_context_menu` | `false` | bool | Use the webview's native right-click menu. |

Which of the three a droplet should use:

| | Dock / taskbar | Menu bar |
|---|---|---|
| widget (clock, sysmon, …) | no — `skip_taskbar: true` | no |
| app (calculator, a notepad) | yes — leave `skip_taskbar` false | no |
| manager / anything long-running | no — `skip_taskbar: true` | yes — `menubar: true` |

> Backend note: `shape: mask` and `skip_pager` are GTK/X11 only. On macOS
> (pywebview) keep-below/stick/opacity are recovered natively via `NSWindow`;
> `skip_taskbar` sets the accessory activation policy (`LSUIElement` at
> runtime), so the process gets no Dock tile, and `menubar` adds an
> `NSStatusItem` — the droplet's `icon` if it ships one, otherwise the `drop.fill`
> SF Symbol. See the Backends section of [`README.md`](README.md).

---

## Runtime settings (vs. manifest)

The manifest is what the **author** ships and shouldn't change under the user.
Runtime state the app writes back (as the user moves/resizes/places the window)
lives in a **separate `settings.json`**, a sibling of `manifest.json`, so a store
update to the shipped manifest never clobbers the user's placement.

| Setting | Default | Written when |
|---------|---------|--------------|
| `x` | `null` | window stops moving (last known, any layout) |
| `y` | `null` | window stops moving (last known, any layout) |
| `screen` | `0` | window placed on a screen (GTK backend, when not stuck) |
| `width` | `300` | window resized (only when `resizable` is `true`) |
| `height` | `300` | window resized (only when `resizable` is `true`) |
| `layouts` | `{}` | same as above, kept per monitor arrangement (both backends) |
| *(your options)* | as declared | the user edited them in the manager (see below) |

There is deliberately **no** `enabled` field here. Whether a droplet autostarts
is a list the *manager* owns (`system/manager/enabled.json`), never a flag in a
droplet's own file — otherwise a downloaded droplet could ship `enabled: true`
and self-start. A `settings.json` carrying `enabled` is rejected on load.

Moves and resizes are debounced (`_SETTLE_DELAY`, 0.5s of stillness) so one drag
costs one write, at the end of the drag rather than at close.

On load, `settings.json` is overlaid on top of the authored manifest — so a
stored `width` overrides the manifest default, `x`/`y` restore the last position,
etc. `Manifest.save_setting()` writes it; `Manifest.validate_settings()` rejects
any key outside the table above or with the wrong type. You never author
`settings.json` by hand — the runtime creates and maintains it. Everything else
in `manifest.json` is authored and read-only at runtime.

### Multiple monitors & resolution changes

One `x`/`y` can't describe a widget that lives top-right on the laptop screen and
mid-left on the 4K when docked. So geometry is *also* stored per monitor
arrangement, under `layouts`, keyed by a fingerprint of the attached displays
(`WxH+X+Y` per screen, sorted, joined with `|`). **Both backends do this** — each
resolution / monitor setup keeps its own remembered position and size:

```json
{
    "x": 2021,
    "y": 69,
    "layouts": {
        "1512x982+0+0": { "x": 1300, "y": 40 },
        "1512x982+0+0|2560x1440-2560+0": { "x": 2021, "y": 69 }
    }
}
```

`Manifest.layout(key)` reads an entry, `Manifest.save_layout(key, **geometry)`
writes one. The fingerprint is built from the live displays — `_layout_key()` on
pywebview (`webview.screens`), `geometry.layout_key()` on GTK (`Gdk` monitors);
both emit the identical string. **Correcting a widget's spot for one arrangement
is remembered for that arrangement only**, so switching back and forth stops the
two placements from fighting over one `x`/`y`.

**Startup** resolution order:

1. `layouts[current fingerprint]` — the exact spot this arrangement had → restored as-is.
2. No entry yet (this setup is new, or the displays changed while the app was
   closed) → **remap proportionally** from a saved arrangement: the widget's
   fractional place on its old screen, mapped onto the matching current screen.
3. No saved history at all → **clamp** the authored manifest `x`/`y` onto a real
   monitor, so a widget authored for a wider display never opens off-screen.

**While running**, both backends react live to display changes — macOS via
`NSApplicationDidChangeScreenParameters`, Linux via `GdkScreen`
`monitors-changed` / `size-changed`. On a change: if the new arrangement is
already remembered, the widget is put back where it was left on it; otherwise it
is remapped proportionally and that new spot is saved. The pure geometry math
(fingerprint, screen-match, proportional remap, on-screen clamp) lives in
`droplets/geometry.py`, backend-agnostic and unit-tested without a display.

`save_layout` mirrors each write to the top-level `x`/`y`, so an older build that
predates `layouts` still finds the last position, just without the per-setup
memory. The one backend gap: on GTK the `screen` (X-server screen index) is still
stored flat, not per-arrangement.

---

## User options

Geometry is settings the *runtime* writes. `options` is settings the **user**
writes: the manifest declares a form, the manager renders it, and the answers
land in the same `settings.json`.

```json
{
    "width": 200, "height": 210,
    "options": {
        "poll_seconds": {
            "type": "int", "label": "Refresh every",
            "description": "Seconds between samples.",
            "default": 1, "min": 1, "max": 60
        },
        "net_units": {
            "type": "enum", "label": "Network units",
            "choices": ["bytes", "bits"], "default": "bytes"
        }
    }
}
```

| Key | Required | Meaning |
|-----|----------|---------|
| `type` | yes | `string`, `int`, `number`, `bool` or `enum`. |
| `choices` | `enum` only | Non-empty list of strings. |
| `default` | no | Value before the user touches anything. Must match `type` (and be one of `choices`). |
| `min` / `max` | no | Bounds for `int`/`number`, enforced on save *and* on load. |
| `label` | no | Field label in the manager (defaults to the option's name). |
| `description` | no | Hint under the field. |

### Reading them

Values are applied as attributes, so Python reads `manifest.poll_seconds`
directly. JavaScript asks the runner:

```js
droplets.send(JSON.stringify({ method: "droplet_options", args: {} }));
// -> droplets.recieve({ poll_seconds: 1, net_units: "bytes" })
```

`droplet_options` is a built-in action (gate 3), so it works regardless of
`allowed_methods`. Options are read at launch; the manager restarts a running
droplet after a save so a change takes effect immediately.

### Reserved names

An option may not be named after any manifest field or settings key — the whole
geometry set (`x`, `y`, `width`, `height`, `screen`, `layouts`) and every field
in the table above. Two reasons: geometry is auto-populated by the
running window and an option of the same name would fight it, and `settings.json`
is user-editable, so an option called `origin` or `allowed_methods` would be a
way to rewrite the security tier from outside the authored manifest. The loader
rejects the manifest with `option 'x' is a reserved name`.

---

## The manager

`system/manager` is itself a droplet (`type: app`, `origin: local`). It lists
every directory in `apps/` that has a `manifest.json` and shows what the
manifest declares — icon, title, description, `screenshots`, and a form built
from `options`. Switching a droplet on spawns `droplets.py <dir>` as a child of
the manager; switching it off (or quitting the manager) terminates it. What is
running is read from the process table, so a droplet closed from its own context
menu shows as off — and that manual close also drops it from the autostart list,
so it is not brought back next launch.

Run the manager like any droplet — point the runner at its directory:

```sh
uv run droplets.py system/manager        # macOS / Windows (pywebview)
python3 droplets.py system/manager       # Linux (gtk) — system gi, not uv
```

The set of droplets to autostart is a list the manager owns
(`system/manager/enabled.json`), **not** a flag in each droplet's file — a
droplet cannot enable itself. On launch the manager restarts everything on that
list; the same list drives a login item (same mac/linux split):

```sh
uv run system/manager/main.py --autostart          # Linux/GTK: python3 system/manager/main.py …
```

---

## Cmd access granulation

Only `local` droplets can call Python. The front-end sends a JSON command; the
backend dispatches it. There are three concentric gates — pick the tightest that
lets the widget work.

### The bridge

JavaScript sends a packet:

```js
droplets.send(JSON.stringify({ method: "some_function", args: { foo: 1 } }));
```

Python (`droplets/droplet.py` → `recieve`) dispatches `method` to a function in
your module (`executable`, default `main.py`) and returns the result to
`droplets.recieve(result)` in JS. `args` are passed as keyword arguments.

### Gate 1 — origin

`recieve()` returns immediately unless `origin == "local"`. `remote`/`hosted`
droplets have **no bridge at all**. This is the coarse tier gate.

### Gate 2 — `allowed_methods` allowlist (the hybrid tier)

By default (`allowed_methods: null`) **every** function in your module is
callable from JS — full trust. To run a *hybrid* droplet (untrusted-ish web
front-end, gated backend), list exactly the functions JS may call:

```json
{
    "origin": "local",
    "width": 200, "height": 200,
    "allowed_methods": ["get_weather", "get_config"]
}
```

Now only `get_weather` / `get_config` are reachable; anything else is dropped.
Validated as a list of strings. **For any droplet that mixes remote-loaded UI
with a backend, set this** — it's the difference between "web page that can run
two safe functions" and "web page that can run `subprocess`".

| `allowed_methods` | Effect |
|-------------------|--------|
| omitted / `null` | full trust — every module function callable |
| `[]` | no module functions callable (only built-in `droplet_*` actions) |
| `["a", "b"]` | only `a` and `b` callable |

### Gate 3 — built-in `droplet_*` actions

Methods named `droplet_*` (e.g. `droplet_move`, `droplet_drag`) are the runner's
own window actions, always callable from JS regardless of `allowed_methods`.
They act on the window, not your module.

### Injected args

Three arg names, if present in `args`, are filled by the runner with live
objects instead of your JSON value: `gtk` (the GTK module), `browser` (the
webview), `window` (the window handle). Use them when a backend function needs
to touch the window directly. **Python `main.py` only** — a live object can't
cross a process boundary, so a Node/Ruby executable never receives these; it
reaches the window through the built-in `droplet_*` actions instead.

### Non-Python executables (Node, Ruby)

`main.py` is imported and called in-process. When the `executable` resolves to a
non-Python file instead, the runner spawns it as a **child process** and speaks
to it over stdio — so a droplet's backend can be written in any language. The
resolver picks by extension (Python wins if several exist):

| File | Runs as |
|------|---------|
| `main.py` | in-process Python import (the default, unchanged) |
| `main.js` / `main.mjs` / `main.cjs` | `node <file>` |
| `main.rb` | `ruby <file>` |

Everything above is identical from the JS side — same `droplets.send` packet,
same three gates (origin, `allowed_methods`, `droplet_*`). Only the dispatch
changes: instead of a function call, the runner sends the packet to the child.

**Protocol** — one JSON object per line, one reply per request:

```
host  → child : {"method": "<name>", "args": { ... }}
child → host  : {"result": <any>}   OR   {"error": "<message>"}
```

**stdout is the reply channel only.** Send logs/diagnostics to **stderr** — the
runner drains stderr to its own log (and to the terminal). Anything the child
prints to stdout that isn't a reply desyncs the stream and is reported as a
protocol error.

**Errors** surface to the widget: a child that replies `{"error": …}`, crashes,
or exits mid-call delivers `droplets.recieve({ error: "<message>" })` to your JS,
and the child's stderr shows up in the terminal.

**Lifecycle:** the child is spawned once when the droplet loads and killed when
it deactivates. If it dies, the next call respawns it — so any state held in the
executable between calls is lost on a crash; keep durable state in a file, not a
module global.

`main.js`:

```js
const methods = {
  hello: ({ msg }) => `Hello ${msg} world!`,
};
require("readline").createInterface({ input: process.stdin }).on("line", (line) => {
  const { method, args } = JSON.parse(line);
  const fn = methods[method];
  process.stdout.write(JSON.stringify({ result: fn ? fn(args || {}) : null }) + "\n");
});
```

`main.rb`:

```ruby
require "json"
METHODS = { "hello" => ->(a) { "Hello #{a['msg']} world!" } }
STDIN.each_line do |line|
  req = JSON.parse(line)
  fn = METHODS[req["method"]]
  STDOUT.puts JSON.generate("result" => (fn ? fn.call(req["args"] || {}) : nil))
  STDOUT.flush
end
```

`node` / `ruby` must be on `PATH`. The mechanism is backend-agnostic
(`droplets/executable.py`) — it works the same under the GTK and pywebview
backends described in [`README.md`](README.md).

---

## Checklist before you ship

- `width`/`height` set; manifest loads without a validation error.
- Smallest `origin` that works (`local` only if you truly need the system).
- If the UI loads anything remote **and** has a backend → set `allowed_methods`.
- Non-rect shape → `transparent: true` and a PNG-alpha or CSS silhouette
  (arbitrary `shape: mask` is GTK/X11-only).
