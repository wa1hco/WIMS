# Installing WS Hub

WS Hub was called WIMS before version 1.0.18. The download files, the folders, and the Windows install folder still use the old name (`wims-<version>-…`, `C:\WIMS`). That is expected.

This page is the one set of install steps. The other documents link here.

WS Hub needs Python 3.10 or newer and nothing else from the internet. It does **not** install N1MM Logger+, WSJT-X, GridTracker, or radio drivers; install those yourself on the PCs that need them.

## Linux

1. Download `wims-<version>-linux-x86_64.tar.gz` from [GitHub Releases](https://github.com/wa1hco/WS-Hub/releases).
2. Unpack it anywhere. Downloads is fine.
3. Open the unpacked folder, then open **scripts**.
4. Double-click **Install WS Hub**.

WS Hub copies itself to `~/.local/share/ws-hub` in your home folder and puts **WS Hub** on the desktop and in the app menu. A message says so, and says you can delete the download. Delete the unpacked folder and the `.tar.gz`, then double-click **WS Hub**.

The file manager may ask once before **Install WS Hub** runs:

- **Ubuntu and other GNOME desktops:** If a message says the file is not trusted, right-click **Install WS Hub** and click **Allow Launching**. Then double-click it again.
- **KDE:** If a window asks whether to open or run the file, click **Execute**.
- **XFCE:** If a window asks whether to run the file, click **Execute**.
- **Cinnamon:** If a window asks, click **Run**. If it says the file is not trusted, right-click it and click **Allow Launching**, then double-click it again.

If the file opens as a page of text, right-click it, open **Properties**, allow it to run as a program, and double-click it again.

If Python or the window library is missing, a message names what to install. On Ubuntu and Debian the packages are `python3` and `python3-tk`. On Fedora the window library is `python3-tkinter`. Install that, then double-click **Install WS Hub** again.

**Updating.** In the WS Hub window, open **Updates**, pick the new version, and click **Install this update**. WS Hub downloads it, checks it, and replaces the copy in `~/.local/share/ws-hub`. **Go back** returns to the copy it replaced. Installing a newer download with **Install WS Hub** does the same thing.

**Only one copy.** The folder is always `~/.local/share/ws-hub`, with no version in its name. The copy an update replaced is kept at `~/.local/share/ws-hub.previous` for **Go back**; the next update replaces it, so old copies do not pile up.

**A git clone** is not copied. Its **Install WS Hub** puts an icon on the desktop that runs the clone where it is, and the clone updates with git.

## Windows

1. Download `wims-<version>-windows-x86_64.zip` from [GitHub Releases](https://github.com/wa1hco/WS-Hub/releases).
2. Extract it to **`C:\WIMS`**.
3. Open `C:\WIMS\scripts\windows` and double-click **Install-Wims.cmd**. Click **Yes** when Windows asks for permission.
4. Double-click **WS Hub** on the Desktop or in the Start menu.

The installer finds or installs Python, opens TCP port 8787 in the firewall so other PCs can reach the console, and puts **WS Hub** and **Check logs** on the Desktop and in the Start menu. Its log is `scripts\windows\install-log.txt`.

The scripts are not signed yet, so Windows may warn the first time:

- **"Windows protected your PC"** (SmartScreen): click **More info**, then **Run anyway**, if you trust [wa1hco/WS-Hub](https://github.com/wa1hco/WS-Hub).
- **The file is blocked:** right-click the `.zip` before extracting (or `Install-Wims.cmd`), choose **Properties**, check **Unblock**, and click **OK**.

To put the icons back later, double-click `C:\WIMS\scripts\Add WIMS to Desktop.bat`.

**Updating.** A copy installed from the zip opens the release page when an update is available; download the new zip and extract it over `C:\WIMS`. A git clone updates from the **Updates** list in the WS Hub window.

More Windows detail (seat startup, the agent, firewall helpers, troubleshooting): [scripts/windows/README.md](scripts/windows/README.md).

## Where your settings live

Settings are not in the program folder, so installing or updating keeps them.

| | Linux | Windows |
|--|--|--|
| Goal, log choice, contest rules, cluster, heard grids, seats, console window size and place | `~/.config/wims/` | `%APPDATA%\wims\` |
| Seat profile, Firefox console profile | `~/.local/share/wims/` | `%LOCALAPPDATA%\WIMS\` |
| Chromium console profile | `~/.local/state/wims/` | `%LOCALAPPDATA%\WIMS\` |

## After installing

- One PC with WSJT-X: double-click **WS Hub** and click **Start Solo**. The console opens at <http://localhost:8787/>.
- A station with several PCs: one PC runs the site server; see [Operator setup](docs/operator_setup.md) and [Networking](docs/plan/wims_networking.md).
- Using the console: [User manual](docs/User-manual.md).

## Developer

Typed commands are for people changing WS Hub or installing from a shell.

```bash
git clone https://github.com/wa1hco/WS-Hub.git
cd WS-Hub
sudo apt install -y python3 python3-tk   # Debian or Ubuntu; Fedora: python3-tkinter
scripts/install-linux.sh                # same as double-clicking Install WS Hub; a clone stays in place
```

A rolling, unversioned [ZIP of main](https://github.com/wa1hco/WS-Hub/archive/refs/heads/main.zip) also works. Release packages leave out `tools/` (lab benches in `tools/testbed/`, Keyline KiCad and flashing in `tools/hardware/`); the key-line software is in `src/`. On Windows, `scripts\windows\install.ps1` is the PowerShell install entry (before 1.0.20 it was `install.ps1` at the top of the folder).

Sibling digital-mode builds (patched WSJT-X with transmit inhibit): [wsjtx-inhibit Releases](https://github.com/wa1hco/wsjtx-inhibit/releases).

## Cut a Release (maintainers)

Pushing `main` does **not** publish a release. Tag when other PCs should see an update.

1. Set the same numeric version (for example `1.0.20`) in `pyproject.toml` and `src/wims/__init__.py`, and write `docs/releases/v1.0.20.md`. Its first heading becomes the release title.
2. Merge, then tag the merge commit: `git tag -a v1.0.20 -m "WS Hub 1.0.20"` and `git push origin v1.0.20`. Use `-tester` or `-rcN` suffixes for prereleases. `tools/dev/cut-release.sh` does the tagging.
3. The **Release** workflow checks the version, runs the tests, builds `wims-<version>-linux-x86_64.tar.gz`, `wims-<version>-windows-x86_64.zip`, and `SHA256SUMS`, and publishes the release.

Mid-cycle lab drop: Actions → **Tester packages** → Run workflow. Local package check: `tools/dev/package-release.sh 1.0.20` writes the three files to `dist/`. Design: [wims_release_packages.md](docs/plan/wims_release_packages.md).
