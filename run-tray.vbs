' Launches RemotePC into the Windows Taskbar Notification Tray with NO console window
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
WshShell.Run "pythonw tray.py", 0, False
