# Show a short message in a window when this PC has one.
# Prints the same words when it does not.
# Sourced by the other Linux start files. Not a program you double-click.

wims_say() {
  _wims_title=$1
  _wims_text=$2
  if _wims_try_dialog "$_wims_title" "$_wims_text"; then
    return 0
  fi
  printf '%s\n\n%s\n' "$_wims_title" "$_wims_text"
}

_wims_have_display() {
  [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]
}

_wims_try_dialog() {
  _wims_title=$1
  _wims_text=$2
  if ! _wims_have_display; then
    return 1
  fi
  if command -v zenity >/dev/null 2>&1; then
    zenity --info --title="$_wims_title" --text="$_wims_text" --width=480 || true
    return 0
  fi
  if command -v kdialog >/dev/null 2>&1; then
    kdialog --title "$_wims_title" --msgbox "$_wims_text" || true
    return 0
  fi
  if command -v yad >/dev/null 2>&1; then
    yad --title="$_wims_title" --text="$_wims_text" --button=OK:0 --width=480 || true
    return 0
  fi
  if _wims_tk_dialog "$_wims_title" "$_wims_text"; then
    return 0
  fi
  if command -v xmessage >/dev/null 2>&1; then
    xmessage -center -title "$_wims_title" "$_wims_text" || true
    return 0
  fi
  if command -v gxmessage >/dev/null 2>&1; then
    gxmessage -title "$_wims_title" -center "$_wims_text" || true
    return 0
  fi
  if _wims_terminal_dialog "$_wims_text"; then
    return 0
  fi
  return 1
}

# The window library, when it is already installed. A missing library just
# falls through to the next way to show the message.
_wims_tk_dialog() {
  _wims_title=$1
  _wims_text=$2
  if ! command -v python3 >/dev/null 2>&1; then
    return 1
  fi
  WIMS_SAY_TITLE=$_wims_title
  WIMS_SAY_TEXT=$_wims_text
  export WIMS_SAY_TITLE WIMS_SAY_TEXT
  python3 -c '
import os, sys
try:
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass
    messagebox.showinfo(
        os.environ.get("WIMS_SAY_TITLE") or "WIMS",
        os.environ.get("WIMS_SAY_TEXT") or "",
    )
    root.destroy()
except Exception:
    sys.exit(1)
' && return 0
  return 1
}

_wims_terminal_dialog() {
  _wims_text=$1
  WIMS_SAY_TEXT=$_wims_text
  export WIMS_SAY_TEXT
  _wims_body='printf "%s\n\nPress Enter to close.\n" "$WIMS_SAY_TEXT"; read _wims_key || true'
  if command -v x-terminal-emulator >/dev/null 2>&1; then
    x-terminal-emulator -e /bin/sh -c "$_wims_body" && return 0
  fi
  if command -v xfce4-terminal >/dev/null 2>&1; then
    xfce4-terminal -e "/bin/sh -c $_wims_body" && return 0
  fi
  if command -v konsole >/dev/null 2>&1; then
    konsole -e /bin/sh -c "$_wims_body" && return 0
  fi
  if command -v gnome-terminal >/dev/null 2>&1; then
    gnome-terminal -- /bin/sh -c "$_wims_body" && return 0
  fi
  if command -v xterm >/dev/null 2>&1; then
    xterm -e /bin/sh -c "$_wims_body" && return 0
  fi
  return 1
}
