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

The release file is `wims-<ver>-linux-x86_64.tar.gz`. A ZIP of `main` works too.

1. Unpack it and open the WIMS folder.
2. Open **scripts**.
3. Double-click **Add WIMS to Desktop**.

WIMS is then on the desktop and in the app menu. Double-click **WIMS**.

The file manager may ask once:

- **Ubuntu and other GNOME desktops:** If a message says the file is not trusted, right-click **Add WIMS to Desktop** and click **Allow Launching**. Then double-click it again.
- **KDE:** If a window asks whether to open or run the file, click **Execute**.
- **XFCE:** If a window asks whether to run the file, click **Execute**.
- **Cinnamon:** If a window asks, click **Run**. If it says the file is not trusted, right-click it and click **Allow Launching**, then double-click it again.

If the file opens as a page of text, right-click it, open **Properties**, allow it to run as a program, and double-click it again.

If Python or the window library is missing, a message names what to install. Install that, then do what the message says. On Ubuntu and Debian the packages are `python3` and `python3-tk`. On Fedora the window library is `python3-tkinter`.

## Windows

1. Extract the Windows zip to **`C:\WIMS`** (or use a git clone).
2. Clear download blocks if Windows complains (scripts are not Authenticode-signed yet):
   - Prefer **`scripts\windows\Install-Wims.cmd`** (uses `-ExecutionPolicy Bypass` for that run).
   - SmartScreen: **More info** → **Run anyway** if you trust this GitHub project.
   - Explorer → file **Properties** → **Unblock**, or:
     ```powershell
     Unblock-File -Path .\scripts\windows\*.cmd, .\scripts\windows\*.ps1, .\install.ps1
     powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
     ```
3. Double-click **`Install-Wims.cmd`** (UAC), or run the Bypass line above.
4. Start Desktop **WIMS**.

Install adds/finds Python ≥ 3.10, **Git** (clone + in-app GitHub update check; skipped for Release ZIP trees with no `.git`), firewall TCP **8787**, Desktop shortcut.  
It does **not** install N1MM, WSJT-X, GridTracker, or radio drivers.

**Bundled private Python** (offline embed + Tk) is specified in the design and lands with the Windows runtime packaging PRs. Until then, Install uses system Python.

Full Windows notes: [scripts/windows/README.md](scripts/windows/README.md).  
Same unblock / SmartScreen steps are also in the main [README.md](README.md) Windows section.

## Dial frequency (10 m vs 432)

WIMS treats the WSJT-X / N1MM dial as **RF** unless that rig-name is marked.
A Flex 10 m radio at 28.074 MHz shows as **10m**. Roy’s 222 (21 MHz IF) and
432 (28 MHz IF) are marked on the console **Setup** page (or the seat agent
page on that PC). The list is `if_seats.json` under `~/.config/wims/` or
`%APPDATA%\wims\`. You do not set an environment variable for this.

## Developer

Typed commands are for people changing WIMS or installing from a shell.

```bash
sudo apt update
sudo apt install -y python3 python3-tk   # Debian or Ubuntu; Python ≥ 3.10
# Fedora: python3 and python3-tkinter

./install.sh
# same entry: scripts/install-linux.sh
```

## Cut a Release (maintainers)

Pushing `main` does **not** publish a GitHub Release. Tag when other PCs should see **Update available** (launcher, site server, and N1MM agent check Releases at startup — git is not required).

1. Bump `pyproject.toml` and `src/wims/__init__.py` to the **numeric** version only (example: `1.0.0`).
2. Commit. Tag with channel suffix as needed:
   - `git tag v1.0.0-tester` (prerelease)
   - `git tag v1.0.0-rc1` (prerelease)
   - `git tag v1.0.0` (GA)
   - or `tools/dev/cut-release.sh v1.0.1` then `git push origin v1.0.1`
3. `git push origin <tag>` → Actions **Release** validates, builds allow-list artifacts, publishes.

Mid-cycle lab drop: Actions → **Tester packages** → Run workflow.

Local package smoke:

```bash
tools/dev/package-release.sh 1.0.0
# writes dist/wims-1.0.0-linux-x86_64.tar.gz
#      dist/wims-1.0.0-windows-x86_64.zip
#      dist/SHA256SUMS
```
