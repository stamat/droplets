# Droplet packaging

A droplet is distributed one of two ways, keyed by the manifest `origin`.

## 1. Hosted (internet apps — no system access)

No package at all. Distribute a URL. The store record is just:

```json
{ "origin": "hosted", "source": "https://example.com/widget/", "type": "widget" }
```

The runner loads it in a webview with the system bridge disabled (`recieve()`
already returns early when `origin != "local"`). Same trust level as opening the
page in a browser. Nothing to sign, nothing to unpack.

## 2. Packaged (`.droplet` — remote and local tiers)

A `.droplet` file is a **zip archive** (same idea as `.crx`, `.vsix`, `.wgt`,
`.xpi`). Root of the archive contains the manifest; everything else is the
app's own tree:

```
mywidget.droplet  (zip)
├── manifest.json        # required, at archive root
├── index.html
├── main.py              # only for local/hybrid tiers
├── css/ js/ images/ ...
```

Install = verify signature, unzip into `~/.local/share/droplets/<uid>/`, launch
with the existing `droplets.py <dir>` path. No format change to the runner —
it already loads a directory.

### Tiers map to manifest, not to the package format

| Tier | `origin` | `main.py`? | `allowed_methods` |
|------|----------|-----------|-------------------|
| Internet, no OS access | `hosted` | no | n/a (bridge off) |
| Remote resources, no OS access | `remote` | no | n/a (bridge off) |
| Hybrid: web frontend + gated backend | `local` | yes | **required allowlist** |
| Full local | `local` | yes | omit = full access |

`allowed_methods` (added to the manifest) is the allowlist of backend functions
the frontend may call. For the hybrid tier it should be **mandatory and
non-empty**; a full-trust local app omits it.

### Signing

Sign the zip's manifest + a content hash with the publisher key; the store
serves the public key. Unsigned `.droplet` files install only with an explicit
"developer mode" override. This is what lets the store make trust claims about a
package without re-reviewing every byte.

### Store distribution

- Store index: JSON list of `{uid, name, version, origin, tier, download_url,
  signature, publisher}`.
- Hosted apps ship a URL row; packaged apps ship a `.droplet` download URL.
- The manager (`system/manager`) is the only droplet allowed to call the store
  API (remote calls restricted to the store host, per the README plan).

Reuse `zipfile` from the stdlib for pack/unpack — no new dependency needed.
