# Developer tools

Not for contest operation. These build, test, package, or bring up hardware.

- `validate.sh` — Run the unit suites and a no-radio live check.
- `package-release.sh` — Build the release zip and tar.
- `cut-release.sh` — Tag a release.
- `packaging/write_manifest.py` — Write the release manifest.
- `run_ui_fleet.sh` — Start the site server plus the on-screen fleet simulator.
- `run_agent.py` — Seat-agent entry used by the Windows agent launcher.
- `capture-user-manual-shots.sh` — Refresh the user-manual screenshots.
- `capture_user_manual_shots.py` — Screenshot capture used by the shell script.
- `proxmox-clone-wims-seats.sh` — On the Proxmox host, clone the Windows seat guests.
- `_pve_api.py` — Small Proxmox API helper.
- `_pve_spawn_seats.py` — Spawn the lab seat guests.
- `flash_keyline.py` — Program a Keyline board’s USB name. Backups stay under `hardware/keyline_interface/eeprom/`.
- `windows/Start-GrokAtLogon.cmd` — Start the Grok CLI at sign-in.
- `windows/Start-GrokAtLogon.vbs` — Sign-in starter for that Grok command.
- `windows/Install-GrokLogonStartup.cmd` — Add the Grok sign-in shortcut.
- `windows/Install-GrokLogonStartup.ps1` — Helper used by that installer.
