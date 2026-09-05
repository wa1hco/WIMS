# User-manual screenshots

Same idea as map144’s **View → Screenshots** panel: pick windows/pages, capture to
stable filenames under **`images/`**, optionally with a **suffix** so a contest-run
copy does not overwrite the doc embed.

## Ways to capture

### A. Launcher panel (recommended)

1. Start the site server (and `:8790` if you want local-status shots).
2. Put the UI in the **mode you want documented** (filters, bands, contest log picked, …).  
   For Operate, URL query params also set context for headless grabs, e.g.  
   `/?needed=1&bands=144&maxAge=120&cols=call,to_call,band,snr,age,score`
3. Open the **WIMS launcher** → **Screenshots…**
4. Check the pages/windows you want (catalog entries can encode a context URL).
5. Choose **Standard name** (overwrites `images/<id>.png` used by the manual)  
   or **Add suffix** (e.g. `contest_run` → `site-operate_contest_run.png`).
6. **Capture Selected** or **Capture All**.

Launcher window grab needs ImageMagick (`import`) or `gnome-screenshot` on Linux.

### B. CLI (browser pages)

```bash
scripts/capture-user-manual-shots.sh
scripts/capture-user-manual-shots.sh --only site-operate,site-n1mm
scripts/capture-user-manual-shots.sh --suffix contest_run
WIMS_MANUAL_BASE=http://192.168.1.119:8787 scripts/capture-user-manual-shots.sh
```

Requires Chrome/Chromium. Window shots (`launcher-home`) are skipped here — use the panel.

## Where files go

| Path | Role |
|------|------|
| [`shots.json`](shots.json) | Catalog (id, url/window, caption) |
| [`images/<id>.png`](images/) | Canonical embeds for [User-manual.md](../User-manual.md) |
| `images/<id>_<suffix>.png` | Variant / dated copies (not linked until you choose) |

**You do not edit the Markdown** when refreshing a standard-name shot — the path stays the same.

## Catalog fields

| Field | Meaning |
|-------|---------|
| `id` | Filename stem → `images/<id>.png` |
| `kind` | `url` · `window` (launcher) · `placeholder` (manual drop-in) |
| `url` | Page to capture (`kind=url`) |
| `window` | `launcher` for the Tk window |
| `width` / `height` | Browser size |
| `caption` / `section` | Manual figure text |
| `status` | `active` or `stub` |

## Manual

Operator source: **[../User-manual.md](../User-manual.md)**.
