' Launches RemotePC.exe silently in the background (0 windows)
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
If CreateObject("Scripting.FileSystemObject").FileExists("dist\RemotePC.exe") Then
    WshShell.Run "dist\RemotePC.exe", 0, False
Else
    WshShell.Run "pythonw server.py", 0, False
End If
