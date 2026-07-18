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
A few fields are **runtime state** the app writes back as the user moves/places
the window:

| Field | Default | Written when |
|-------|---------|--------------|
| `x` | `null` | window moved |
| `y` | `null` | window moved |
| `screen` | `0` | window placed on a screen |

Today these are persisted back into `manifest.json` via
`Manifest.dump_manifest()`. Splitting them into a separate settings file (so a
store update can't clobber the authored manifest) is a planned change — see the
"Separate settings from manifest" TODO in [`README.md`](README.md). Treat
`x`/`y`/`screen` as settings, everything else as authored manifest.

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
