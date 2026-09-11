' Start Grok CLI at logon (visible TUI, tools auto-approved).
Option Explicit
Dim sh, fso, here
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
' 0 = hide the wrapper cmd; Start-GrokAtLogon.cmd opens its own Grok window.
sh.Run "cmd.exe /c """ & here & "\Start-GrokAtLogon.cmd"" /silent", 0, False
