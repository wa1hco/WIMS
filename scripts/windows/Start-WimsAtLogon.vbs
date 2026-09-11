' WIMS — logon entry (no cmd window). Starts WSJT-X / WIMS from seat intent.
Option Explicit
Dim sh, fso, here
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
sh.Run "cmd.exe /c """ & here & "\Start-WimsAtLogon.cmd"" /silent", 0, False
