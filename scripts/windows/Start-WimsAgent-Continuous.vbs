' WIMS — Desktop "WIMS Agent" entry (sticky green icon; no visible cmd).
Option Explicit
Dim sh, fso, here
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
sh.Run "cmd.exe /c """ & here & "\Start-WimsAgent-Continuous.cmd""", 0, False
