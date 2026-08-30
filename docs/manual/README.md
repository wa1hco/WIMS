# User-manual screenshots

## Refresh after UI changes

1. Start (or leave running) the site server and any pages you want live shots of.
2. Run:

```bash
scripts/capture-user-manual-shots.sh
```

3. Open [../User-manual.md](../User-manual.md) — image paths are fixed; **you do not edit the Markdown** when shots change.

Optional:

```bash
# Only some shots
scripts/capture-user-manual-shots.sh --only site-operate,site-status

# Point URL shots at another site console
WIMS_MANUAL_BASE=http://192.168.1.119:8787 scripts/capture-user-manual-shots.sh

# Rebuild stub placeholders
scripts/capture-user-manual-shots.sh --force-placeholders
```

## Catalog

Edit **[shots.json](shots.json)** to add/rename shots:

| Field | Meaning |
|-------|---------|
| `id` | Filename stem → `images/<id>.png` |
| `kind` | `url` (Chrome headless) or `placeholder` (stub / manual drop-in) |
| `url` | Page to capture (`kind=url`) |
| `width` / `height` | Browser window size |
| `caption` | Figure caption in the manual |
| `section` | Which manual heading the shot supports |
| `status` | `active` or `stub` |

Tk windows (launcher, Log agent, Key agent) stay `placeholder` until someone drops a PNG over `images/<id>.png`. The capture script **keeps** a real file once present unless `--force-placeholders`.

## Manual

Source of truth for operators: **[../User-manual.md](../User-manual.md)**.
