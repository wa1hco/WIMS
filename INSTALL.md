# WIMS — Install

Stdlib Python only. No `pip install` for the product path.

**Design (release packages):** [docs/plan/wims_release_packages.md](docs/plan/wims_release_packages.md)  
**Tester tracks:** [docs/tester_quickstart.md](docs/tester_quickstart.md)  
**Roles:** [docs/tester_roles.md](docs/tester_roles.md)

## Get the tree

| Method | Steps |
|--------|--------|
| **Git clone** (lab / updates via git) | `git clone https://github.com/wa1hco/WIMS.git` then `cd WIMS` |
| **GitHub Release** | Download `wims-<ver>-windows-x86_64.zip` or `wims-<ver>-linux-x86_64.tar.gz` from [Releases](https://github.com/wa1hco/WIMS/releases) |
| **Rolling `main` ZIP** | [main.zip](https://github.com/wa1hco/WIMS/archive/refs/heads/main.zip) — unversioned |

Contest Windows install root: **`C:\WIMS`**.  
Release packages **omit** `hardware/` (Keyline flash/KiCad). KEY *software* (`wims.seat --key`) is in `src/`.

Sibling digi builds: [wsjtx-inhibit Releases](https://github.com/wa1hco/wsjtx-inhibit/releases).

## Linux

```bash
sudo apt update
sudo apt install -y git python3 python3-tk   # ≥ 3.10

# from clone or unpacked linux tarball:
./install.sh
# same entry: scripts/install-linux.sh
```

Start: Desktop **WIMS**, or `PYTHONPATH=src python3 -m wims solo`.

## Windows

1. Extract the Windows zip to **`C:\WIMS`** (or use a git clone).
2. Double-click **`scripts\windows\Install-Wims.cmd`** (UAC), or from PowerShell: `.\install.ps1`.
3. Start Desktop **WIMS**.

Install adds/finds Python ≥ 3.10, optional Git, firewall TCP **8787**, Desktop shortcut.  
It does **not** install N1MM, WSJT-X, GridTracker, or radio drivers.

**Bundled private Python** (offline embed + Tk) is specified in the design and lands with the Windows runtime packaging PRs. Until then, Install uses system Python.

Full Windows notes: [scripts/windows/README.md](scripts/windows/README.md).

## Cut a Release (maintainers)

1. Bump `pyproject.toml` and `src/wims/__init__.py` to the **numeric** version only (example: `1.0.0`).
2. Commit. Tag with channel suffix as needed:
   - `git tag v1.0.0-tester` (prerelease)
   - `git tag v1.0.0-rc1` (prerelease)
   - `git tag v1.0.0` (GA)
3. `git push origin <tag>` → Actions **Release** validates, builds allow-list artifacts, publishes.

Mid-cycle lab drop: Actions → **Tester packages** → Run workflow.

Local package smoke:

```bash
scripts/package-release.sh 1.0.0
# writes dist/wims-1.0.0-linux-x86_64.tar.gz
#      dist/wims-1.0.0-windows-x86_64.zip
#      dist/SHA256SUMS
```
