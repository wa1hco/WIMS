' WIMS — Desktop shortcut entry (keeps custom .ico; no visible cmd window).
' Delegates to Start-WimsLauncher.cmd for PYTHONPATH / pythonw / seat-local.
Option Explicit
Dim sh, fso, here, cmd
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
cmd = """" & here & "\Start-WimsLauncher.cmd"""
' 0 = hide the brief cmd window; cmd itself starts pythonw via "start".
sh.Run "cmd.exe /c " & cmd, 0, False
