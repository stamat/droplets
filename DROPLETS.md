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
python3 droplets.py apps/myclock      # or any path to the directory
```

Add a Python backend only if the widget needs the system — see
[cmd access](#cmd-access-granulation). Pure web widgets skip `main.py` entirely.

---

## Debugging a droplet

A droplet is a web page, so use the browser's own inspector:

```sh
DROPLETS_DEBUG=1 python3 droplets.py apps/myclock
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
| `icon` | `null` | string | Icon file path. |

### Loading

| Field | Default | Type | Meaning |
|-------|---------|------|---------|
| `origin` | `"local"` | enum `local`\|`remote`\|`hosted` | Security tier (see above). |
| `source` | `"index.html"` | string | Entry document (a URL when `origin: hosted`). |
| `executable` | `"main"` | string | Python module (no `.py`) loaded for the bridge on `local`. |

### Size & shape

| Field | Default | Type | Meaning |
|-------|---------|------|---------|
| `width` | `300` | int | **Mandatory.** Window width. |
| `height` | `300` | int | **Mandatory.** Window height. |
| `resizable` | `false` | bool | Allow the user to resize. |
| `shape` | `"rect"` | enum `rect`\|`roundedrect`\|`circle`\|`mask` | Window silhouette. |
| `corner_radius` | `0` | int | Corner radius when `shape: roundedrect`. |
| `shape_mask` | `null` | string | PNG path for `shape: mask` (arbitrary silhouette). **GTK/X11 only** — no-op elsewhere; use `transparent` + PNG-alpha for cross-platform shaping. |
| `transparent` | `false` | bool | RGBA transparent window (needed for non-rect shapes). |
| `opacity` | `1` | number | Whole-window opacity, `0`–`1`. |

### Window behaviour

| Field | Default | Type | Meaning |
|-------|---------|------|---------|
| `decorated` | `false` | bool | Show the window titlebar/border. |
| `above` | `false` | bool | Keep above other windows. |
| `below` | `false` | bool | Pin to the desktop, behind windows (widget style). |
| `stick` | `false` | bool | Show on all workspaces / Spaces. |
| `drag` | `false` | bool | Drag the window by its body. |
| `hidden` | `false` | bool | Start hidden. |
| `skip_taskbar` | `false` | bool | Hide from the taskbar. |
| `skip_pager` | `false` | bool | Hide from the pager. |
| `default_context_menu` | `false` | bool | Use the webview's native right-click menu. |

> Backend note: `shape: mask`, `skip_taskbar`/`skip_pager` and per-window
> keep-below are strongest on the GTK/X11 backend. On macOS (pywebview)
> keep-below/stick/opacity are recovered natively via `NSWindow`;
> `skip_taskbar` maps to an app-bundle `LSUIElement` key at packaging time.
> See the Backends section of [`README.md`](README.md).

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
| `layouts` | `{}` | same as above, kept per monitor arrangement (pywebview backend) |

Moves and resizes are debounced (`_SETTLE_DELAY`, 0.5s of stillness) so one drag
costs one write, at the end of the drag rather than at close.

On load, `settings.json` is overlaid on top of the authored manifest — so a
stored `width` overrides the manifest default, `x`/`y` restore the last position,
etc. `Manifest.save_setting()` writes it; `Manifest.validate_settings()` rejects
any key outside the table above or with the wrong type. You never author
`settings.json` by hand — the runtime creates and maintains it. Everything else
in `manifest.json` is authored and read-only at runtime.

### Multiple monitors

One `x`/`y` can't describe a widget that lives top-right on the laptop screen and
mid-left on the 4K when docked. So geometry is *also* stored per monitor
arrangement, under `layouts`, keyed by a fingerprint of the attached displays
(`WxH+X+Y` per screen, sorted, joined with `|`):

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
writes one; `_layout_key()` in the pywebview backend builds the fingerprint from
`webview.screens`. Resolution order at startup:

1. `layouts[current fingerprint]` — the position this exact arrangement had.
2. Top-level `x`/`y` — last known anywhere, also what pre-`layouts` settings
   files and the GTK backend hold.
3. The manifest's authored position.

Whichever wins is still dropped if it lands on no attached display
(`_rect_on_screen`), so a widget never restores off in the void. `save_layout`
mirrors to the top-level keys as it writes, so downgrading loses the per-layout
memory but not the last position.

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
to touch the window directly.

---

## Checklist before you ship

- `width`/`height` set; manifest loads without a validation error.
- Smallest `origin` that works (`local` only if you truly need the system).
- If the UI loads anything remote **and** has a backend → set `allowed_methods`.
- Non-rect shape → `transparent: true` and a PNG-alpha or CSS silhouette
  (arbitrary `shape: mask` is GTK/X11-only).
